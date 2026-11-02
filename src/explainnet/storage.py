"""SQLite migrations and small repositories; no implicit database creation."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from explainnet.contracts import JobState
from explainnet.scenario_contracts import ExperimentGroundTruth

MIGRATIONS = [
    """
    CREATE TABLE runs (
        id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, config_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE TABLE ground_truth (
        run_id TEXT PRIMARY KEY REFERENCES runs(id), payload_json TEXT NOT NULL
    );
    CREATE TABLE incidents (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
        created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY, type TEXT NOT NULL, state TEXT NOT NULL,
        created_utc TEXT NOT NULL, started_utc TEXT, ended_utc TEXT,
        elapsed_ms REAL, result_json TEXT, error TEXT, request_id TEXT NOT NULL
    );
    CREATE INDEX jobs_state_created ON jobs(state, created_utc);
    CREATE TABLE snapshots (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
        config_hash TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
        created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE candidates (
        id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
        created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE actions (
        id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
        snapshot_id TEXT REFERENCES snapshots(id), created_utc TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT NOT NULL,
        actor TEXT NOT NULL, event_type TEXT NOT NULL, request_id TEXT,
        subject_id TEXT, payload_json TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE jobs ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}';
    CREATE TABLE network_instances (
        instance_id TEXT PRIMARY KEY, state TEXT NOT NULL, config_hash TEXT,
        config_version TEXT, ownership_json TEXT NOT NULL, updated_utc TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE telemetry_collectors (
        run_id TEXT PRIMARY KEY REFERENCES runs(id), instance_id TEXT NOT NULL,
        state TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_start_ticks TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE UNIQUE INDEX one_running_collector ON telemetry_collectors(instance_id)
        WHERE state IN ('starting','running','stopping');
    CREATE TABLE telemetry_samples (
        sample_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL,
        at_utc TEXT NOT NULL, raw_path TEXT NOT NULL, raw_offset INTEGER NOT NULL,
        content_hash TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE INDEX telemetry_sample_run ON telemetry_samples(run_id);
    CREATE TABLE telemetry_windows (
        window_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), instance_id TEXT NOT NULL,
        end_monotonic_s REAL NOT NULL, complete INTEGER NOT NULL, inference_ready INTEGER NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE INDEX telemetry_window_instance ON telemetry_windows(instance_id,end_monotonic_s);
    CREATE VIEW inference_ready_windows AS SELECT window_id,run_id,
        json_extract(payload_json,'$.features') AS features_json FROM telemetry_windows WHERE inference_ready=1;
    CREATE TABLE telemetry_references (instance_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
    CREATE TABLE baseline_alerts (window_id TEXT PRIMARY KEY REFERENCES telemetry_windows(window_id),
        instance_id TEXT NOT NULL, payload_json TEXT NOT NULL);
    """,
    """
    CREATE TABLE dataset_batches (
        batch_id TEXT PRIMARY KEY, state TEXT NOT NULL, schedule_hash TEXT NOT NULL,
        owner_pid INTEGER NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE UNIQUE INDEX one_active_dataset_batch ON dataset_batches((1)) WHERE state='running';
    CREATE TABLE dataset_attempts (
        attempt_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES dataset_batches(batch_id),
        episode_id TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE dataset_members (
        window_id TEXT PRIMARY KEY REFERENCES telemetry_windows(window_id),
        batch_id TEXT NOT NULL REFERENCES dataset_batches(batch_id), episode_id TEXT NOT NULL,
        family_id TEXT NOT NULL, partition TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES dataset_attempts(attempt_id), window_hash TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE jobs ADD COLUMN origin TEXT NOT NULL DEFAULT 'external';
    """,
    """
    CREATE TABLE model_bundles (
        model_id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE TABLE model_activation (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), model_id TEXT NOT NULL REFERENCES model_bundles(model_id)
    );
    CREATE TABLE diagnoses (
        diagnosis_id TEXT PRIMARY KEY, window_id TEXT NOT NULL REFERENCES telemetry_windows(window_id),
        model_id TEXT NOT NULL REFERENCES model_bundles(model_id), mode TEXT NOT NULL CHECK(mode IN ('live','recorded')),
        created_utc TEXT NOT NULL, window_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
        UNIQUE(window_id,model_id,mode)
    );
    """,
    """
    CREATE TABLE incident_state (
        incident_id TEXT PRIMARY KEY REFERENCES incidents(id), context_key TEXT NOT NULL,
        state TEXT NOT NULL, last_observation_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE INDEX incident_context ON incident_state(context_key,state);
    CREATE TABLE incident_events (
        event_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
        window_id TEXT NOT NULL REFERENCES telemetry_windows(window_id), diagnosis_id TEXT REFERENCES diagnoses(diagnosis_id),
        observation_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE explanation_backgrounds (
        recipe_key TEXT PRIMARY KEY, model_id TEXT NOT NULL REFERENCES model_bundles(model_id),
        content_hash TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE explanations (
        explanation_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL UNIQUE,
        window_id TEXT NOT NULL REFERENCES telemetry_windows(window_id), model_id TEXT NOT NULL REFERENCES model_bundles(model_id),
        diagnosis_id TEXT REFERENCES diagnoses(diagnosis_id), incident_id TEXT REFERENCES incidents(id),
        state TEXT NOT NULL CHECK(state IN ('pending','ready','failed','unsupported')),
        created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE twin_snapshots (
        snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id), request_key TEXT NOT NULL UNIQUE,
        snapshot_hash TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE twin_instances (
        twin_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES twin_snapshots(snapshot_id),
        state TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE twin_trials (
        trial_id TEXT PRIMARY KEY, twin_id TEXT NOT NULL REFERENCES twin_instances(twin_id),
        state TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE recovery_experiments (
        operation_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES twin_snapshots(snapshot_id),
        twin_id TEXT NOT NULL, state TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    """
,
    """
    CREATE TABLE recovery_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload_json TEXT NOT NULL);
    CREATE TABLE recovery_workflows (
        workflow_id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, instance_id TEXT NOT NULL,
        incident_id TEXT REFERENCES incidents(id), state TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE UNIQUE INDEX one_live_recovery_workflow ON recovery_workflows(instance_id)
        WHERE state IN ('observing','diagnosing','validating','recommended','applying','verifying','rolling_back') AND COALESCE(json_extract(payload_json,'$.finished'),0)=0;
    CREATE TABLE lab_action_state (
        action_id TEXT PRIMARY KEY REFERENCES actions(id), request_key TEXT NOT NULL UNIQUE,
        instance_id TEXT NOT NULL, state TEXT NOT NULL, created_utc TEXT NOT NULL,payload_json TEXT NOT NULL
    );
    """

,
    """
    CREATE TABLE job_idempotency (
        idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
        job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id), created_utc TEXT NOT NULL
    );
    """
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._connection_lock = threading.RLock()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # Serialize this application's short SQLite transactions on the Windows-mounted
        # filesystem. Collector/dataset/job threads share one Store; read snapshots and
        # writes must not upgrade conflicting simultaneous transactions.
        with self._connection_lock, self._open_connection() as db:
            yield db

    @contextmanager
    def _open_connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise FileNotFoundError(f"database is not initialized: {self.path}")
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_utc TEXT NOT NULL)")
            current = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            for version, migration in enumerate(MIGRATIONS, start=1):
                if version not in current:
                    db.executescript(
                        f"BEGIN; {migration} "
                        f"INSERT INTO schema_migrations VALUES ({version}, '{utc_now()}'); COMMIT;"
                    )
        finally:
            db.close()

    def healthy(self) -> bool:
        try:
            with self.connection() as db:
                return db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
        except (sqlite3.Error, FileNotFoundError):
            return False

    def insert_record(self, table: str, record_id: str, payload: dict[str, Any], **refs: str | None) -> None:
        allowed = {
            "runs": ("config_hash",),
            "ground_truth": (),
            "incidents": ("run_id",),
            "snapshots": ("run_id", "config_hash", "snapshot_hash"),
            "candidates": ("snapshot_id",),
            "actions": ("incident_id", "snapshot_id"),
        }
        if table not in allowed or set(refs) != set(allowed[table]):
            raise ValueError("invalid repository table or references")
        key = "run_id" if table == "ground_truth" else "id"
        columns = [key, *refs, "payload_json"]
        values: list[Any] = [record_id, *refs.values(), json.dumps(payload)]
        if table != "ground_truth":
            columns.insert(-1, "created_utc")
            values.insert(-1, utc_now())
        with self.connection() as db:
            db.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                values,
            )

    def get_record(self, table: str, record_id: str) -> dict[str, Any] | None:
        if table not in {"runs", "ground_truth", "incidents", "snapshots", "candidates", "actions"}:
            raise ValueError("invalid repository table")
        key = "run_id" if table == "ground_truth" else "id"
        with self.connection() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE {key}=?", (record_id,)).fetchone()
            return dict(row) | {"payload": json.loads(row["payload_json"])} if row else None

    def audit(self, actor: str, event_type: str, payload: dict[str, Any], request_id: str | None = None,
              subject_id: str | None = None) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO audit_events(at_utc,actor,event_type,request_id,subject_id,payload_json) VALUES(?,?,?,?,?,?)",
                (utc_now(), actor, event_type, request_id, subject_id, json.dumps(payload)),
            )

    def list_audit(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM audit_events ORDER BY id")]

    def create_job(self, job_id: str, job_type: str, request_id: str, payload: dict[str, Any] | None = None,
                   origin: str = "external", idempotency_key: str | None = None) -> str:
        if origin not in {"external", "dataset"}:
            raise ValueError("invalid job origin")
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            request_hash = self.job_request_hash(job_type, payload or {})
            if idempotency_key:
                old = db.execute('SELECT request_hash,job_id FROM job_idempotency WHERE idempotency_key=?', (idempotency_key,)).fetchone()
                if old:
                    if old['request_hash'] != request_hash:
                        raise ValueError('idempotency key reused with different operation or inputs')
                    return old['job_id']
            db.execute(
                "INSERT INTO jobs(id,type,state,created_utc,request_id,payload_json,origin) VALUES(?,?,?,?,?,?,?)",
                (job_id, job_type, JobState.queued, utc_now(), request_id, json.dumps(payload or {}), origin),
            )
            if idempotency_key:
                db.execute('INSERT INTO job_idempotency VALUES(?,?,?,?)', (idempotency_key, request_hash, job_id, utc_now()))
            return job_id

    @staticmethod
    def job_request_hash(operation, payload):
        import hashlib
        return hashlib.sha256(json.dumps([operation, payload], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    def idempotent_job(self, key, operation=None, payload=None):
        with self.connection() as db:
            row = db.execute('SELECT request_hash,job_id FROM job_idempotency WHERE idempotency_key=?', (key,)).fetchone()
        if row and operation is not None and row['request_hash'] != self.job_request_hash(operation, payload or {}):
            raise ValueError('idempotency key reused with different operation or inputs')
        return row['job_id'] if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            raw_result = result.pop("result_json")
            result["result"] = json.loads(raw_result) if raw_result else None
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def next_queued(self) -> dict[str, Any] | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,type,request_id,payload_json,origin FROM jobs WHERE state=? ORDER BY created_utc LIMIT 1",
                             (JobState.queued,)).fetchone()
            if not row:
                return None
            changed = db.execute(
                "UPDATE jobs SET state=?,started_utc=? WHERE id=? AND state=?",
                (JobState.running, utc_now(), row["id"], JobState.queued),
            ).rowcount
            return dict(row) | {"payload": json.loads(row["payload_json"])} if changed == 1 else None

    def finish_job(self, job_id: str, state: JobState, elapsed_ms: float,
                   result: dict[str, Any] | None = None, error: str | None = None) -> bool:
        if state not in {JobState.succeeded, JobState.failed, JobState.canceled}:
            raise ValueError("invalid final state")
        with self.connection() as db:
            return db.execute(
                "UPDATE jobs SET state=?,ended_utc=?,elapsed_ms=?,result_json=?,error=? WHERE id=? AND state=?",
                (state, utc_now(), elapsed_ms, json.dumps(result) if result is not None else None,
                 error, job_id, JobState.running),
            ).rowcount == 1

    def cancel_job(self, job_id: str) -> bool:
        with self.connection() as db:
            return db.execute("UPDATE jobs SET state=?,ended_utc=? WHERE id=? AND state=?",
                              (JobState.canceled, utc_now(), job_id, JobState.queued)).rowcount == 1

    def interrupt_running(self) -> int:
        with self.connection() as db:
            return db.execute("UPDATE jobs SET state=?,ended_utc=?,error=? WHERE state=?",
                              (JobState.interrupted, utc_now(), "service restarted", JobState.running)).rowcount

    def save_instance(self, record: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO network_instances VALUES(?,?,?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET "
                "state=excluded.state, config_hash=COALESCE(excluded.config_hash,config_hash), "
                "config_version=COALESCE(excluded.config_version,config_version), ownership_json=excluded.ownership_json, "
                "updated_utc=excluded.updated_utc",
                (record["instance_id"], record["state"], record.get("config_hash"), record.get("config_version"),
                 json.dumps(record), utc_now()),
            )

    def list_instances(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [json.loads(row["ownership_json"]) for row in db.execute("SELECT * FROM network_instances")]

    def update_run(self, run_id: str, payload: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute("UPDATE runs SET payload_json=? WHERE id=?", (json.dumps(payload), run_id))

    def save_scenario_result(self, result: dict[str, Any]) -> None:
        """Observed runs and experimental truth use separate tables, including reset times."""
        journal = result.get("laboratory_journal")
        if not journal:
            return
        with self.connection() as db:
            for run in result["traffic_runs"]:
                db.execute("INSERT INTO runs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                           "payload_json=excluded.payload_json",
                           (run["run_id"], run["created_utc"], run["config_hash"], json.dumps(run)))
                kind = journal["configuration"]["kind"]
                truth = {"schema_version": 1, "run_id": run["run_id"], "fault_label": kind,
                         "configuration": journal["configuration"], "injected_parameters": journal["parameters"] | {
                             "offered_demand_bps": journal.get("offered_demand_bps"),
                             "shared_capacity_bps": journal.get("capacity_bps"),
                             "qos_capacity_bps": journal.get("qos_capacity_bps")},
                         "intended_location": None if kind == "healthy" else "s3->s5" if kind == "qos" else "s2->s3",
                         "activated_utc": journal["activated_utc"], "deactivated_utc": journal["deactivated_utc"],
                         "state": journal["state"], "restore_errors": journal.get("restore_errors", [])}
                truth["affected_directions"] = journal.get("modified_directions", [])
                truth['activated_monotonic_s'] = journal.get('activated_monotonic_s')
                truth['deactivated_monotonic_s'] = journal.get('deactivated_monotonic_s')
                truth = ExperimentGroundTruth.model_validate(truth).model_dump(mode="json")
                db.execute("INSERT INTO ground_truth VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET "
                           "payload_json=excluded.payload_json", (run["run_id"], json.dumps(truth)))
