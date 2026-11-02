"""Apply additive dataset/job-origin migrations and preserve existing production rows."""

import json
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.storage import Store, utc_now

store = Store(load_settings(Path("config/example.yaml")).database_path)
tables = ("runs", "ground_truth", "jobs", "network_instances", "telemetry_samples", "telemetry_windows")
with store.connection() as db:
    columns = {table: ",".join(r[1] for r in db.execute(f"PRAGMA table_info({table})")) for table in tables}


def snapshot():
    with store.connection() as db:
        return {table: [tuple(r) for r in db.execute(f"SELECT {columns[table]} FROM {table} ORDER BY 1")] for table in tables}


before = snapshot()
with store.connection() as db:
    old = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
store.initialize()
after = snapshot()
assert before == after
with store.connection() as db:
    new = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
assert new == 5
report = {"at_utc": utc_now(), "from": old, "to": new, "prior_rows_unchanged": True,
          "prior_content_sha256": digest(before), "record_counts": {key: len(value) for key, value in before.items()}}
Path("artifacts/stage6/migration_report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
