"""Bounded, compact progress for the active Stage 13 collection."""
import json
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT/'artifacts/stage6/runtime/config.json').read_text())
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/v1/health",timeout=5) as r:
        print('health',r.read().decode())
except OSError as e:
    print('health',str(e))
with sqlite3.connect('file:'+cfg['data_dir']+'/explainnet.sqlite3?mode=ro',uri=True,timeout=5) as db:
    batch = json.loads(db.execute('SELECT payload_json FROM dataset_batches WHERE batch_id=?',('db5a15991774142f0a8ef871522face4d',)).fetchone()[0])
    print('batch',json.dumps({k:batch.get(k) for k in ('state','error','phase','current_episode')}))
    print('amendment',batch.get('recovery_amendment',{}).get('version'))
    print('members',list(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition')))
    completed = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM dataset_attempts WHERE state='completed'")]
    main_completed = [a for a in completed if a['batch_id']==batch['batch_id']]
    new_completed = [a for a in main_completed if a['started_utc']>='2026-10-16T00:00:00']
    mean = sum(a['elapsed_s'] for a in new_completed)/len(new_completed) if new_completed else None
    progress = {'at_utc':datetime.now(UTC).isoformat(),'state':batch['state'],
        'completed_episodes':len(main_completed),'target_episodes':60,
        'mean_recent_episode_s':mean,'estimated_remaining_collection_minutes':(60-len(main_completed))*mean/60 if mean else None}
    print('progress',json.dumps(progress))
    (ROOT/'artifacts/stage13/collection_progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    print('jobs',list(db.execute("SELECT id,type,state,error FROM jobs ORDER BY rowid DESC LIMIT 4")))
    for row in db.execute('SELECT payload_json FROM dataset_attempts ORDER BY rowid DESC LIMIT 2'):
        a = json.loads(row[0])
        print('attempt',json.dumps({k:a.get(k) for k in ('attempt_id','episode_id','state','error','number','elapsed_s','collector_run_id','cleanup_verified')}))
        if a.get('collector_run_id'):
            c = json.loads(db.execute('SELECT payload_json FROM telemetry_collectors WHERE run_id=?',(a['collector_run_id'],)).fetchone()[0])
            print('collector',json.dumps({k:c.get(k) for k in ('state','sample_count','last_observation_utc','errors')}))
