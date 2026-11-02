"""Bounded recovery matching measured sampler latency; quality/partition gates unchanged."""
import json
from pathlib import Path

from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store, utc_now

runtime = Path('artifacts/stage6/runtime')
supervisor = json.loads((runtime / 'supervisor.json').read_text())
if supervisor['state'] != 'failed' or not supervisor['cleanup_preserved_bridges'] or supervisor['agent_socket_present']:
    raise ValueError('verified supervisor cleanup is required')
repo = DatasetRepository(Store(runtime / 'app/data/explainnet.sqlite3'))
batch = repo.batch('db5a15991774142f0a8ef871522face4d')
if batch['state'] != 'failed':
    raise ValueError('failed batch required; do not race a running collector')
if batch['recovery_amendment']['version'] != 'cadence_recovery_v3':
    completed = {a['episode_id'] for a in repo.attempts(batch['batch_id']) if a['state'] == 'completed'}
    amendment = {'version': 'cadence_recovery_v3', 'created_utc': utc_now(), 'sample_interval_s': 2,
        'measurement_s': 100, 'original_schedule_hash': batch['schedule_hash'],
        'reason': 'Measured 80 snapshots and four steady windows under 1-second nominal cadence; actual gaps exceeded overrun allowance. Declare 2-second cadence, 35-second native arrival grace and 300-second collector bound; min coverage/probes/receiver gates unchanged',
        'previous_amendment': batch['recovery_amendment'],
        'episodes': {e['episode_id']: {'attempt_limit': max(2, len(repo.attempts(batch['batch_id'], e['episode_id'])) + 2)}
            for e in batch['schedule']['episodes'] if e['episode_id'] not in completed}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    repo.save_batch(batch)
    repo.store.audit('stage7-prerequisite-recovery', 'dataset_cadence_recovery', amendment, subject_id=batch['batch_id'])
atomic_json(Path('artifacts/stage7/dataset_cadence_recovery.json'), batch['recovery_amendment'])
print(json.dumps({'batch_id': batch['batch_id'], 'recovery': batch['recovery_amendment']['version'], 'schedule_hash': batch['schedule_hash']}))
