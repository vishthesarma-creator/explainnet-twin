"""Apply migration 11 while proving prior production evidence is preserved."""
import hashlib
import json
import sqlite3
from pathlib import Path

from explainnet.config import load_settings
from explainnet.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def state(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        tables = ['runs', 'ground_truth', 'jobs', 'telemetry_samples', 'telemetry_windows', 'dataset_members',
            'dataset_batches', 'model_bundles', 'explanations', 'incidents', 'snapshots', 'candidates', 'actions']
        return {'schema_version': db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],
            'counts': {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables},
            'unsealed_members_digest': hashlib.sha256(json.dumps(db.execute("SELECT window_id,partition,window_hash "
                "FROM dataset_members WHERE partition IN ('train','pilot') ORDER BY window_id").fetchall()).encode()).hexdigest(),
            'dataset_states': db.execute('SELECT batch_id,state FROM dataset_batches ORDER BY batch_id').fetchall(),
            'partitions': dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition')),
            'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0]}


def main():
    path = load_settings(ROOT / 'artifacts/stage6/runtime/config.json').database_path
    (ROOT / 'artifacts/stage12').mkdir(exist_ok=True)
    before = state(path)
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as source, sqlite3.connect(ROOT / 'artifacts/stage12/before_migration.sqlite3') as target:
        source.backup(target)
    Store(path).initialize()
    after = state(path)
    preserved = all(before[k] == after[k] for k in ('counts', 'unsealed_members_digest', 'dataset_states', 'partitions'))
    assert preserved and after['integrity_check'] == 'ok'
    report = {'path': str(path), 'before': before, 'after': after, 'prior_records_preserved': preserved,
        'sealed_test_measurements_read': False}
    (ROOT / 'artifacts/stage12/storage_migration.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
