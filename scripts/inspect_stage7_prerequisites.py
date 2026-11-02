"""Read-only Stage 7 prerequisite inspection; no test feature analysis."""
import importlib.metadata
import json
from collections import Counter
from pathlib import Path

from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store

store = Store(Path('artifacts/stage6/runtime/app/data/explainnet.sqlite3'))
repo = DatasetRepository(store)
batch = repo.batch('db5a15991774142f0a8ef871522face4d')
print('dependencies', {p: importlib.metadata.version(p) for p in ['scikit-learn','numpy','scipy','joblib','pandas']})
with store.connection() as db:
    w = json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?',
        ('w6a0007d8ebb3eb703b2c11505fcc247a',)).fetchone()[0])
    print('duration', repr(w['end_monotonic_s'] - w['start_monotonic_s']), w['start_monotonic_s'])
for a in repo.attempts(batch['batch_id'], 'main_qos_f2_r0'):
    print('failed attempt', a['attempt_id'], a.get('error'), Counter(r for w in a['rejected_windows'] for r in w['reasons']))
    with store.connection() as db:
        windows = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM telemetry_windows WHERE run_id=?', (a['collector_run_id'],))]
    for w in windows:
        print(w['window_id'], w['inference_ready'], w['data_quality'])
