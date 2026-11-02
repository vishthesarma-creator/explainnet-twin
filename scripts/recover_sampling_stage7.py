"""One further bounded recovery after measured failure of duration-only recovery."""
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
if batch['recovery_amendment']['version'] != 'sampling_recovery_v2':
    old = batch['recovery_amendment']
    completed = {a['episode_id'] for a in repo.attempts(batch['batch_id']) if a['state'] == 'completed'}
    amendment = {'version': 'sampling_recovery_v2', 'created_utc': utc_now(),
        'original_schedule_hash': batch['schedule_hash'], 'measurement_s': 100,
        'reason': '100-second attempts still yielded fewer than six windows; reduce all-lost ping wait and rebuild history on window cadence/native completion',
        'previous_amendment': old,
        'episodes': {e['episode_id']: {'attempt_limit': max(2, len(repo.attempts(batch['batch_id'], e['episode_id'])) + 2)}
            for e in batch['schedule']['episodes'] if e['episode_id'] not in completed}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    repo.save_batch(batch)
    store.audit('stage7-prerequisite-recovery', 'dataset_sampling_recovery', amendment, subject_id=batch['batch_id'])
atomic_json(Path('artifacts/stage7/dataset_sampling_recovery.json'), batch['recovery_amendment'])
store.initialize()  # Previous supervisor has stopped; additive migration is now safe.
report = export_dataset(store, batch['batch_id'])
print(json.dumps({'batch_id': batch['batch_id'], 'accepted': report['quality']['accepted_windows'],
    'structural_checks_passed': report['quality']['structural_checks_passed']}))
if not report['quality']['structural_checks_passed']:
    raise ValueError('resume audit failed')
