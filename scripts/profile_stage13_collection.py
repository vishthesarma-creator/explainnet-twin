"""Read the rejected train episode and measure local storage latency separately."""
import json
import sqlite3
import tempfile
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path

from explainnet.dataset_export import atomic_json, phase_for_window

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT/'artifacts/stage6/runtime/config.json').read_text())
with sqlite3.connect('file:'+cfg['data_dir']+'/explainnet.sqlite3?mode=ro',uri=True) as db:
    attempt = json.loads(db.execute('SELECT payload_json FROM dataset_attempts WHERE attempt_id=?',('a22ba11c84eaf48a2af57d0bd885e063b',)).fetchone()[0])
    windows = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM telemetry_windows WHERE run_id=?',(attempt['collector_run_id'],))]
    samples = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM telemetry_samples WHERE run_id=? AND source='network_agent' ORDER BY rowid",(attempt['collector_run_id'],))]
out = {'attempt_id':attempt['attempt_id'],'error':attempt['error'],
    'collection_ms':[s['collection_duration_ms'] for s in samples],
    'gaps_s':[b['monotonic_s']-a['monotonic_s'] for a,b in pairwise(samples)],
    'windows':[{'window_id':w['window_id'],'phase':phase_for_window(w,attempt['main_reset_receipt'],attempt['main_traffic']),
        'coverage':w['data_quality']['coverage_fraction'],'reasons':w['data_quality']['reasons']} for w in windows]}
out['storage_benchmark'] = {}
for label,directory in [('windows_mount',ROOT/'artifacts/stage13'),('linux','/tmp')]:
    values=[]
    with tempfile.TemporaryDirectory(prefix='stage13-io-',dir=directory) as folder:
        path=Path(folder)/'probe.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE probes(id INTEGER PRIMARY KEY,payload TEXT)')
            for i in range(20):
                start=time.monotonic()
                db.execute('INSERT INTO probes VALUES(?,?)',(i,'x'*50000))
                db.commit()
                values.append((time.monotonic()-start)*1000)
    out['storage_benchmark'][label]={'commits':20,'mean_ms':sum(values)/len(values),'max_ms':max(values)}
atomic_json(ROOT/'artifacts/stage13/collection_timing_diagnosis.json',out)
print(json.dumps({'error':out['error'],'mean_agent_collection_ms':sum(out['collection_ms'])/len(out['collection_ms']),
    'mean_observation_gap_s':sum(out['gaps_s'])/len(out['gaps_s']),
    'rejection_reasons':dict(Counter(r for w in out['windows'] for r in w['reasons'])),
    'storage_benchmark':out['storage_benchmark']},indent=2))
