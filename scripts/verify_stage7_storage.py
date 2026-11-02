"""Actual additive migration verification using a SQLite snapshot; source is not modified."""
import hashlib
import json
import sqlite3
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import Store

source = Path('/var/tmp/explainnet/data/explainnet.sqlite3')
target = Path('artifacts/stage7/foundation_migration_snapshot.sqlite3')
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    raise ValueError('preserve prior verification snapshot; choose a new path explicitly')
with sqlite3.connect(source) as original, sqlite3.connect(target) as copied:
    original.backup(copied)

def inventory(path):
    with sqlite3.connect(path) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
        return {t: {'rows': db.execute('SELECT count(*) FROM ' + t).fetchone()[0],
            'sha256': hashlib.sha256(json.dumps(db.execute('SELECT * FROM ' + t + ' ORDER BY rowid').fetchall(),
                sort_keys=True, default=str).encode()).hexdigest()} for t in tables}

before = inventory(target)
with sqlite3.connect(target) as db:
    version_before = db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
Store(target).initialize()
Store(target).initialize()
after = inventory(target)
assert all(after[t] == record for t, record in before.items())
with sqlite3.connect(target) as db:
    version_after = db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
report = {'schema_version': 1, 'source': str(source), 'snapshot': str(target), 'version_before': version_before,
    'version_after': version_after, 'repeated_init_passed': True, 'prior_tables_preserved': before,
    'new_tables': sorted(set(after) - set(before))}
atomic_json(Path('artifacts/stage7/migration_report.json'), report)
print(json.dumps(report, indent=2))
