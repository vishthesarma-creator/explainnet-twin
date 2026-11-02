"""Checkpointed episode attempts and accepted-window membership, separate from features."""

import json

from explainnet.dataset_contracts import digest
from explainnet.storage import utc_now


class DatasetRepository:
    def __init__(self, store):
        self.store = store

    def batch(self, batch_id):
        with self.store.connection() as db:
            row = db.execute("SELECT payload_json FROM dataset_batches WHERE batch_id=?", (batch_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def batches(self):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM dataset_batches ORDER BY rowid DESC")]

    def save_batch(self, batch):
        batch["updated_utc"] = utc_now()
        with self.store.connection() as db:
            db.execute("INSERT INTO dataset_batches VALUES(?,?,?,?,?) ON CONFLICT(batch_id) DO UPDATE SET "
                "state=excluded.state,payload_json=excluded.payload_json", (batch["batch_id"], batch["state"],
                batch["schedule_hash"], batch["owner_pid"], json.dumps(batch, allow_nan=False)))

    def attempts(self, batch_id, episode_id=None):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM dataset_attempts WHERE batch_id=? "
                "AND (? IS NULL OR episode_id=?) ORDER BY rowid", (batch_id, episode_id, episode_id))]

    def attempt_summaries(self, batch_id):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT attempt_id,episode_id,state, "
                "json_extract(payload_json,'$.number') AS number, json_extract(payload_json,'$.error') AS error, "
                "json_extract(payload_json,'$.partition') AS partition, "
                "json_extract(payload_json,'$.cleanup_verified') AS cleanup_verified "
                "FROM dataset_attempts WHERE batch_id=? ORDER BY rowid", (batch_id,))]

    def attempt(self, attempt_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM dataset_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        if not row:
            raise ValueError('unknown attempt')
        return json.loads(row[0])

    def iter_attempts(self, batch_id):
        """Bounded-memory full native records; yields one decoded attempt at a time."""
        with self.store.connection() as db:
            for row in db.execute('SELECT payload_json FROM dataset_attempts WHERE batch_id=? ORDER BY rowid', (batch_id,)):
                yield json.loads(row[0])

    def audit_summaries(self, batch_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT attempt_id,episode_id,state,json_extract(payload_json,'$.error') AS error, "
                "json_extract(payload_json,'$.rejected_windows') AS rejected_windows FROM dataset_attempts WHERE batch_id=? ORDER BY rowid", (batch_id,)).fetchall()
        return [dict(r) | {'rejected_windows':json.loads(r['rejected_windows'] or '[]')} for r in rows]

    def save_attempt(self, attempt):
        attempt["updated_utc"] = utc_now()
        with self.store.connection() as db:
            db.execute("INSERT INTO dataset_attempts VALUES(?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET "
                "state=excluded.state,payload_json=excluded.payload_json", (attempt["attempt_id"], attempt["batch_id"],
                attempt["episode_id"], attempt["state"], json.dumps(attempt, allow_nan=False)))

    def accept(self, attempt, episode, windows):
        """Commit membership and completion atomically after verified restoration."""
        if not attempt.get("restoration_verified") or not attempt.get("application_verified"):
            raise ValueError("successful application and restoration receipts are required")
        with self.store.connection() as db:
            for window in windows:
                row = (window["window_id"], attempt["batch_id"], episode.episode_id, episode.family_id,
                       episode.partition, attempt["attempt_id"], digest(window))
                old = db.execute("SELECT * FROM dataset_members WHERE window_id=?", (window["window_id"],)).fetchone()
                if old and tuple(old) != row:
                    raise ValueError("conflicting or cross-partition measurement membership")
                db.execute("INSERT OR IGNORE INTO dataset_members VALUES(?,?,?,?,?,?,?)", row)
            attempt.update(state="completed", accepted_window_ids=[w["window_id"] for w in windows],
                           updated_utc=utc_now())
            db.execute("UPDATE dataset_attempts SET state='completed',payload_json=? WHERE attempt_id=?",
                       (json.dumps(attempt, allow_nan=False), attempt["attempt_id"]))

    def members(self, batch_id):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM dataset_members WHERE batch_id=? ORDER BY episode_id,window_id", (batch_id,))]
