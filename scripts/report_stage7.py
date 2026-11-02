"""Snapshot actual readiness and report measured validation only when a trusted bundle exists."""
import importlib.metadata
import json
import sqlite3
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

root = Path(__file__).resolve().parents[1]
runtime = root / 'artifacts/stage6/runtime'
batch_id = 'db5a15991774142f0a8ef871522face4d'
directory = runtime / 'app/data/datasets' / batch_id
manifest = json.loads((directory / 'manifest.json').read_text())
quality = json.loads((directory / 'quality_report.json').read_text())
supervisor = json.loads((runtime / 'supervisor.json').read_text())
with sqlite3.connect(runtime / 'app/data/explainnet.sqlite3') as db:
    batch = json.loads(db.execute('SELECT payload_json FROM dataset_batches WHERE batch_id=?', (batch_id,)).fetchone()[0])
    stored_windows = db.execute('SELECT count(*) FROM dataset_members WHERE batch_id=?', (batch_id,)).fetchone()[0]
    models = db.execute('SELECT payload_json FROM model_bundles ORDER BY created_utc DESC').fetchall()
if models:
    latest = json.loads(models[0][0])
    report = json.loads((Path(latest['directory']) / 'validation_report.json').read_text())
else:
    report = {'schema_version': 1, 'status': 'blocked_dataset_incomplete', 'snapshot_utc': utc_now(),
        'implementation_readiness': 'Implemented; isolated tests are recorded separately in verification_report.json',
        'measured_performance_readiness': False, 'model_id': None, 'bundle_directory': None,
        'dataset_version': manifest['dataset_version'], 'batch_id': batch_id, 'schedule_hash': manifest['schedule_hash'],
        'dataset_state': batch['state'], 'dataset_ready': manifest['dataset_ready'],
        'accepted_export_windows': manifest['accepted_windows'], 'stored_accepted_windows': stored_windows,
        'completed_episodes': manifest['completed_episodes'], 'expected_windows': quality['expected_windows'],
        'expected_episodes': quality['expected_episodes'], 'class_counts': quality['class_counts'],
        'partitions': quality['partitions'], 'independent_episodes_by_class': quality['independent_episodes_by_class'],
        'missing_feature_counts': quality['missing_feature_counts'], 'structural_checks_passed': quality['structural_checks_passed'],
        'shortfalls': quality['shortfalls'], 'calibration_ready': False,
        'training_cross_validation': None, 'validation': None, 'calibration_results': None,
        'actual_measured_validation_inference': 'Not run: reserved validation data unavailable/incomplete',
        'test_partition': 'sealed; no model input conversion, fitting, tuning or scoring',
        'macro_f1_ambition': .85, 'macro_f1_actual': None, 'ambition_met': None,
        'dependencies': {p: importlib.metadata.version(p) for p in ('scikit-learn','numpy','scipy','joblib')},
        'recovery_amendment': batch.get('recovery_amendment'), 'supervisor': supervisor,
        'artifact_paths': {'authoritative_manifest': str(directory / 'manifest.json'),
            'quality_report': str(directory / 'quality_report.json'), 'splits': str(directory / 'splits.json')},
        'blockers': ['Entire measured main batch and reserved validation must pass readiness gates before training'],
        'stage8_ready': False}
atomic_json(root / 'artifacts/model_validation_report.json', report)
print(json.dumps({k: report.get(k) for k in ('status','dataset_state','accepted_export_windows','completed_episodes','model_id','stage8_ready')}, indent=2))
