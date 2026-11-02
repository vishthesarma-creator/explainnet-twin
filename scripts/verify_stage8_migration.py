"""Migrate a SQLite backup, preserving every existing row; never migrate the source."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now


def table_hashes(connection, tables):
    return {table: {'rows': len(rows := connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()),
        'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()} for table in tables}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    if args.target.exists():
        raise ValueError('target backup already exists; choose a new snapshot path')
    args.target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source.resolve().as_uri() + '?mode=ro', uri=True) as source:
        tables = [r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
        before = table_hashes(source, tables)
        source_version = source.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        with sqlite3.connect(args.target) as target:
            source.backup(target)
        Store(args.target).initialize()
        with sqlite3.connect(args.target) as target:
            after = table_hashes(target, tables)
            final_version = target.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        preserved = before == after == table_hashes(source, tables)
    report = {'at_utc': utc_now(), 'source': str(args.source), 'snapshot': str(args.target),
        'source_version': source_version, 'snapshot_version': final_version,
        'existing_rows_preserved': preserved, 'tables': before, 'source_database_migrated': False}
    atomic_json(args.target.parent / 'migration_verification.json', report)
    if not preserved:
        raise ValueError('snapshot migration changed an existing row')
    print(json.dumps({k: v for k, v in report.items() if k != 'tables'}))


if __name__ == '__main__':
    main()
