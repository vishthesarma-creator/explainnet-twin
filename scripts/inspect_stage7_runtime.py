"""Compact read-only runtime diagnostics, excluding feature/test exploration."""
import json
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store

config = json.loads(Path('artifacts/stage6/runtime/config.json').read_text())
batch_id = 'db5a15991774142f0a8ef871522face4d'
repo = DatasetRepository(Store(Path(config['data_dir']) / 'explainnet.sqlite3'))
batch = repo.batch(batch_id)
print('batch', {k: batch.get(k) for k in ('state','phase','error','owner_pid','current_episode','updated_utc')})
for a in repo.attempts(batch_id, 'main_qos_f2_r0'):
    print('attempt', {k: a.get(k) for k in ('number','state','error','cleanup_verified','started_utc','ended_utc')})
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{config['port']}/v1/datasets/{batch_id}", timeout=10) as response:
        status = json.load(response)
    print('live', status['live'])
except (urllib.error.URLError, TimeoutError) as exc:
    print('API unavailable; persisted state above is historical', str(exc))
