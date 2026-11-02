"""Small read-only starting-state snapshot; never reads held-out feature payloads."""
import json
import os
import shutil
import sqlite3
import time
import urllib.request
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
config = json.loads((ROOT / 'artifacts/stage6/runtime/config.json').read_text())
db = sqlite3.connect('file:' + str(Path(config['data_dir']) / 'explainnet.sqlite3') + '?mode=ro', uri=True)
batch = json.loads(db.execute("SELECT payload_json FROM dataset_batches WHERE batch_id=?", ('db5a15991774142f0a8ef871522face4d',)).fetchone()[0])
attempts = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM dataset_attempts WHERE batch_id=? ORDER BY rowid', (batch['batch_id'],))]
last = attempts[-1]
last_samples = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM telemetry_samples WHERE run_id=? ORDER BY rowid', (last.get('collector_run_id'),))]
observations = [s for s in last_samples if s.get('source') == 'network_agent']
collector = db.execute('SELECT payload_json FROM telemetry_collectors WHERE run_id=?', (last.get('collector_run_id'),)).fetchone()
counts = dict(db.execute('SELECT partition,count(*) FROM dataset_members WHERE batch_id=? GROUP BY partition', (batch['batch_id'],)))
out = {'at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'uid': os.getuid(),
    'cpus': os.cpu_count(), 'disk_free_bytes': shutil.disk_usage(ROOT).free,
    'memory': Path('/proc/meminfo').read_text().splitlines()[:3],
    'batch': {k: batch.get(k) for k in ('batch_id','state','error','current_episode','phase','recovery_amendment','schedule_hash','config_hash')},
    'accepted_by_split': counts, 'attempt_count': len(attempts),
    'last_attempt': {k: last.get(k) for k in ('attempt_id','instance_id','episode_id','state','error','elapsed_s','collector_run_id','cleanup_verified')},
    'last_collector': json.loads(collector[0]) if collector else None,
    'recent_failed_attempts': [{k: a.get(k) for k in ('episode_id','number','error','elapsed_s','collector_run_id')} for a in attempts if a['state'] != 'completed'][-5:]}
out['last_phases'] = {role: {'run_id':last.get(role+'_traffic',{}).get('run_id'),
    'created_utc':last.get(role+'_traffic',{}).get('created_utc'),
    'ended_utc':last.get(role+'_traffic',{}).get('ended_utc'),
    'reset_utc':last.get(role+'_reset_receipt',{}).get('laboratory_journal',{}).get('deactivated_utc')}
    for role in ('baseline','main','recovery')}
out['last_observation_summary'] = {'count': len(observations),
    'max_collection_ms':max((s.get('collection_duration_ms',0) for s in observations),default=None),
    'last_utc':[s['at_utc'] for s in observations[-4:]],
    'max_gap_s':max((b['monotonic_s']-a['monotonic_s'] for a,b in pairwise(observations)),default=None),
    'completed_runs':list({r['run_id'] for s in observations for r in s.get('completed_runs',[])})}
for name, port, path in [('api',config['port'],'/v1/dashboard/status'),('dashboard',8501,'/_stcore/health')]:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
            text = response.read().decode()
            out[name] = json.loads(text) if name == 'api' else text
    except OSError as exc:
        out[name] = {'error': str(exc)}
(ROOT / 'artifacts/stage13').mkdir(exist_ok=True)
(ROOT / 'artifacts/stage13/starting_state.json').write_text(json.dumps(out,indent=2)+'\n')
out['batch']['recovery_amendment'] = {k:out['batch']['recovery_amendment'][k] for k in ('version','sha256')}
print(json.dumps(out, indent=2))
