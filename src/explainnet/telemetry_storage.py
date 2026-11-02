"""Append-first, fsynced JSONL with idempotent SQLite indexes and tail recovery."""

import hashlib
import json
import os
import threading

from explainnet.telemetry_contracts import FEATURES

FORBIDDEN = {"fault_label", "label", "scenario", "severity", "laboratory_journal", "injected_parameters",
             "injection_parameters", "intended_location", "activated_utc", "deactivated_utc", "netem_seed",
             "activated_monotonic_s", "deactivated_monotonic_s"}


def reject_ground_truth(value):
    if isinstance(value, dict):
        if set(value) & FORBIDDEN:
            raise ValueError("experimental ground truth is forbidden in telemetry payloads")
        for child in value.values():
            reject_ground_truth(child)
    elif isinstance(value, list):
        for child in value:
            reject_ground_truth(child)


class TelemetryRepository:
    def __init__(self, store):
        self.store = store
        self.directory = store.path.parent / "raw" / "telemetry"
        self.lock = threading.RLock()

    def ingest(self, record, append=True, offset=0):
        reject_ground_truth(record)
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        path = self.directory / f"{record['run_id']}.jsonl"
        with self.lock, self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT content_hash FROM telemetry_samples WHERE sample_id=?", (record["sample_id"],)).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError("sample ID reused with different contents")
                return False
            if append:
                self.directory.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as output:
                    offset = output.tell()
                    output.write(payload.encode() + b"\n")
                    output.flush()
                    os.fsync(output.fileno())
            db.execute("INSERT INTO telemetry_samples VALUES(?,?,?,?,?,?,?,?)",
                (record["sample_id"], record["run_id"], record["source"], record["at_utc"], str(path), offset, digest, payload))
        return True

    def recover(self, run_id):
        path = self.directory / f"{run_id}.jsonl"
        if not path.exists():
            return {"recovered": 0, "partial_tail_bytes": 0}
        data = path.read_bytes()
        boundary = data.rfind(b"\n") + 1
        partial = data[boundary:]
        if partial:
            path.with_suffix(".partial").write_bytes(partial)
            with path.open("r+b") as output:
                output.truncate(boundary)
        recovered, offset = 0, 0
        for line in data[:boundary].splitlines(keepends=True):
            record = json.loads(line)
            if record["run_id"] != run_id:
                raise ValueError("raw run identity mismatch")
            recovered += self.ingest(record, append=False, offset=offset)
            offset += len(line)
        return {"recovered": recovered, "partial_tail_bytes": len(partial)}

    def ingest_many(self, records):
        """One fsynced append and index transaction per bounded native arrival.

        As with ingest, an interrupted index commit leaves recoverable JSONL.
        Conflicting IDs are rejected before appending any data.
        """
        if len(records) > 2048:
            raise ValueError('native arrival batch exceeds 2048 records')
        if not records:
            return 0
        run_ids = {r['run_id'] for r in records}
        if len(run_ids) != 1:
            raise ValueError('native arrival batch must belong to one collector')
        encoded = {}
        for record in records:
            reject_ground_truth(record)
            payload = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            prior = encoded.get(record['sample_id'])
            if prior and prior[2] != content_hash:
                raise ValueError('sample ID reused with different contents')
            encoded[record['sample_id']] = (record, payload, content_hash)
        path = self.directory / (next(iter(run_ids)) + '.jsonl')
        with self.lock, self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = []
            for sample_id, (record, payload, content_hash) in encoded.items():
                old = db.execute('SELECT content_hash FROM telemetry_samples WHERE sample_id=?', (sample_id,)).fetchone()
                if old:
                    if old[0] != content_hash:
                        raise ValueError('sample ID reused with different contents')
                    continue
                pending.append((record, payload, content_hash))
            if not pending:
                return 0
            self.directory.mkdir(parents=True, exist_ok=True)
            rows = []
            with path.open('ab') as output:
                offset = output.tell()
                for record, payload, content_hash in pending:
                    line = payload.encode() + b'\n'
                    output.write(line)
                    rows.append((record['sample_id'], record['run_id'], record['source'], record['at_utc'],
                        str(path), offset, content_hash, payload))
                    offset += len(line)
                output.flush()
                os.fsync(output.fileno())
            db.executemany('INSERT INTO telemetry_samples VALUES(?,?,?,?,?,?,?,?)', rows)
            return len(rows)

    def samples(self, run_id):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM telemetry_samples WHERE run_id=? ORDER BY rowid", (run_id,))]

    def save_windows(self, windows, alerts):
        with self.store.connection() as db:
            for window, alert in zip(windows, alerts, strict=True):
                reject_ground_truth(window)
                if set(window["features"]) != FEATURES:
                    raise ValueError("window features do not match the explicit allowlist")
                db.execute("INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?) ON CONFLICT(window_id) DO UPDATE SET "
                    "complete=excluded.complete,inference_ready=excluded.inference_ready,payload_json=excluded.payload_json",
                    (window["window_id"], window["run_id"], window["instance_id"], window["end_monotonic_s"],
                     window["complete"], window["inference_ready"], json.dumps(window, allow_nan=False)))
                db.execute("INSERT INTO baseline_alerts VALUES(?,?,?) ON CONFLICT(window_id) DO UPDATE SET payload_json=excluded.payload_json",
                    (window["window_id"], window["instance_id"], json.dumps(alert, allow_nan=False)))

    def windows(self, instance_id, limit=50, ready_only=False):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM telemetry_windows WHERE instance_id=? "
                "AND (?=0 OR inference_ready=1) ORDER BY end_monotonic_s DESC LIMIT ?", (instance_id, ready_only, limit))]

    def reference(self, instance_id):
        with self.store.connection() as db:
            row = db.execute("SELECT payload_json FROM telemetry_references WHERE instance_id=?", (instance_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_reference(self, instance_id, payload):
        with self.store.connection() as db:
            db.execute("INSERT INTO telemetry_references VALUES(?,?) ON CONFLICT(instance_id) DO UPDATE SET payload_json=excluded.payload_json",
                       (instance_id, json.dumps(payload)))

    def collectors(self, instance_id=None):
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM telemetry_collectors WHERE (? IS NULL OR instance_id=?) ORDER BY rowid DESC",
                (instance_id, instance_id))]

    def save_collector(self, payload):
        with self.store.connection() as db:
            db.execute("INSERT INTO telemetry_collectors VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "state=excluded.state,payload_json=excluded.payload_json", (payload["run_id"], payload["instance_id"],
                payload["state"], payload["owner_pid"], payload["owner_start_ticks"], json.dumps(payload)))
