"""Apply verified additive schema only after the collection owner has stopped."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from verify_stage8_migration import table_hashes

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    supervisor = json.loads((args.config.parent / 'supervisor.json').read_text())
    if supervisor['state'] not in {'failed', 'completed'} or not supervisor.get('cleanup_preserved_bridges') or supervisor.get('agent_socket_present'):
        raise ValueError('verified supervisor cleanup required before changing its schema')
    for key in ('supervisor_pid', 'api_pid', 'agent_pid'):
        try:
            os.kill(supervisor[key], 0)
        except ProcessLookupError:
            continue
        raise ValueError(f'{key} still exists; refuse to migrate a loaded old application')
    settings = load_settings(args.config)
    store = Store(settings.database_path)
    with sqlite3.connect(store.path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        if connection.execute("SELECT 1 FROM dataset_batches WHERE state='running'").fetchone():
            raise ValueError('collection is still running')
        before_version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
        before = table_hashes(connection, tables)
    store.initialize()
    with sqlite3.connect(store.path) as connection:
        after = table_hashes(connection, tables)
        version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    report = {'at_utc': utc_now(), 'database': str(store.path), 'before_version': before_version,
        'after_version': version, 'all_existing_rows_preserved': before == after,
        'owner_processes_absent': True, 'collector_restarted': False, 'tables': before}
    atomic_json(Path('artifacts/stage8/applied_migration.json'), report)
    if before != after:
        raise ValueError('an existing record changed')
    print(json.dumps({k: v for k, v in report.items() if k != 'tables'}))


if __name__ == '__main__':
    main()
