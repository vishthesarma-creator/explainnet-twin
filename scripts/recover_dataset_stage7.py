"""Record one evidence-based recovery amendment, audit, then use supervisor resume."""
import json
from pathlib import Path

from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json, export_dataset
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store, utc_now
from explainnet.telemetry_service import owner_ticks

store = Store(Path('artifacts/stage6/runtime/app/data/explainnet.sqlite3'))
repo = DatasetRepository(store)
batch = repo.batch('db5a15991774142f0a8ef871522face4d')
if batch['state'] == 'running' and owner_ticks(batch['owner_pid']) == batch['owner_start_ticks']:
    raise ValueError('live batch; recovery must not race collection')
if 'recovery_amendment' not in batch:
    completed = {a['episode_id'] for a in repo.attempts(batch['batch_id']) if a['state'] == 'completed'}
    amendment = {'version': 'coverage_recovery_v1', 'created_utc': utc_now(),
        'original_schedule_hash': batch['schedule_hash'], 'measurement_s': 100,
        'reason': 'Measured QoS sampling overruns caused 4/6 and 5/6 steady-window shortfalls; quality gates unchanged',
        'episodes': {e['episode_id']: {'attempt_limit': max(2, len(repo.attempts(batch['batch_id'], e['episode_id'])) + 2)}
            for e in batch['schedule']['episodes'] if e['episode_id'] not in completed}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    repo.save_batch(batch)
    store.audit('stage7-prerequisite-recovery', 'dataset_recovery_amendment', amendment, subject_id=batch['batch_id'])
atomic_json(Path('artifacts/stage7/dataset_recovery_amendment.json'), batch['recovery_amendment'])
report = export_dataset(store, batch['batch_id'])
print(json.dumps({'batch_id': batch['batch_id'], 'quality': report['quality']}, indent=2))
if not report['quality']['structural_checks_passed']:
    raise ValueError('resume blocked by structural audit')
