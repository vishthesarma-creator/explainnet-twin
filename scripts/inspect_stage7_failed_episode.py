"""Read-only verification of actual saved recovery evidence and steady-window quality."""
import json
from pathlib import Path

from explainnet.dataset_export import phase_for_window
from explainnet.dataset_repository import DatasetRepository
from explainnet.dataset_service import receiver_summary
from explainnet.storage import Store

store = Store(Path('artifacts/stage6/runtime/app/data/explainnet.sqlite3'))
repo = DatasetRepository(store)
attempt = repo.attempts('db5a15991774142f0a8ef871522face4d', 'main_qos_f2_r0')[-1]
print('fields', sorted(attempt))
for role in ('baseline', 'main', 'recovery'):
    traffic = attempt.get(role + '_traffic')
    if traffic:
        print(role, traffic['state'], receiver_summary(traffic))
receipt = attempt.get('cleanup_scenario_reset', {}).get('laboratory_journal', {})
print('cleanup reset', {k: receipt.get(k) for k in ('state','activated_utc','deactivated_utc','restore_errors','configuration')})
with store.connection() as db:
    session = json.loads(db.execute('SELECT payload_json FROM telemetry_collectors WHERE run_id=?', (attempt['collector_run_id'],)).fetchone()[0])
    windows = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM telemetry_windows WHERE run_id=?', (attempt['collector_run_id'],))]
print('collector', session['state'], 'sample_count', session['sample_count'], 'errors', session['errors'])
for w in windows:
    print(w['window_id'], phase_for_window(w, attempt['main_reset_receipt'], attempt['main_traffic'], 5), w['data_quality']['reasons'], w['data_quality']['coverage_fraction'])
