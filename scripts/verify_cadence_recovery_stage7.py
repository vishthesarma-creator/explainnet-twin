"""Real saved QoS recovery evidence; no training or test-feature analysis."""
import json
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.dataset_repository import DatasetRepository
from explainnet.dataset_service import receiver_summary, verify_healthy
from explainnet.storage import Store, utc_now

store = Store(Path('artifacts/stage6/runtime/app/data/explainnet.sqlite3'))
repo = DatasetRepository(store)
batch_id = 'db5a15991774142f0a8ef871522face4d'
attempt = repo.attempts(batch_id, 'main_qos_f2_r0')[-1]
if attempt['state'] != 'completed':
    print(json.dumps({'state': attempt['state'], 'error': attempt.get('error'), 'attempt_number': attempt['number']}))
    raise SystemExit(2)
assert attempt['application_verified'] and attempt['restoration_verified'] and attempt['cleanup_verified']
assert len(attempt['accepted_window_ids']) == 6
with store.connection() as db:
    session = json.loads(db.execute('SELECT payload_json FROM telemetry_collectors WHERE run_id=?', (attempt['collector_run_id'],)).fetchone()[0])
    windows = [json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (wid,)).fetchone()[0])
        for wid in attempt['accepted_window_ids']]
assert session['settings']['sample_interval_s'] == 2
assert all(w['inference_ready'] and w['complete'] and w['data_quality']['coverage_fraction'] >= .65 for w in windows)
report = {'schema_version': 1, 'at_utc': utc_now(), 'batch_id': batch_id, 'episode_id': attempt['episode_id'],
    'attempt_id': attempt['attempt_id'], 'attempt_number': attempt['number'], 'accepted_windows': len(windows),
    'partition': attempt['partition'], 'sampler_interval_s': session['settings']['sample_interval_s'],
    'raw_path': attempt['raw_path'], 'raw_sha256': attempt['raw_sha256'],
    'native_baseline': verify_healthy(attempt['baseline_traffic']), 'native_fault': receiver_summary(attempt['main_traffic']),
    'native_recovery': verify_healthy(attempt['recovery_traffic']), 'application_restore_cleanup_verified': True,
    'windows': [{'window_id': w['window_id'], 'coverage_fraction': w['data_quality']['coverage_fraction'],
        'transmitted_probes': w['data_quality']['transmitted_probes'], 'receiver_duration_s': w['data_quality']['receiver_duration_s']}
        for w in windows], 'kind': 'measured collection prerequisite recovery, not model-quality evidence'}
atomic_json(Path('artifacts/stage7/cadence_recovery_verification.json'), report)
print(json.dumps(report, indent=2))
