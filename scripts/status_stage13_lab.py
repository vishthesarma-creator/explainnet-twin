"""Compact read-only native campaign checkpoint and runtime-based estimate."""
import json
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'artifacts/stage13/lab_report.json'
report=json.loads(path.read_text())
cases=report['cases']
finished=[c for c in cases.values() if c.get('finished')]
durations=[c['total_trial_ms']/1000 for c in finished if 'total_trial_ms' in c]
remaining=len(report.get('declared_order',[]))-len(finished)
live=[]
for name,case in cases.items():
    if case.get('finished'):
        continue
    config=json.loads(Path(case['config']).read_text())
    database=Path(config['data_dir'])/'explainnet.sqlite3'
    if not database.exists():
        continue
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        workflow=db.execute('SELECT state FROM recovery_workflows WHERE instance_id=? ORDER BY rowid DESC LIMIT 1',
            (case['instance_id'],)).fetchone()
        experiment=db.execute("SELECT state,json_array_length(json_extract(payload_json,'$.trials')) FROM recovery_experiments ORDER BY rowid DESC LIMIT 1").fetchone()
        action=db.execute('SELECT state FROM lab_action_state WHERE instance_id=? ORDER BY rowid DESC LIMIT 1',
            (case['instance_id'],)).fetchone()
    live.append({'case':name,'workflow':workflow[0] if workflow else None,
        'latest_twin_experiment':{'state':experiment[0],'saved_trials':experiment[1]} if experiment else None,
        'original_action':action[0] if action else None})
print(json.dumps({'campaign_id':report['campaign_id'],'status':report['status'],
    'finished':len(finished),'planned':len(report.get('declared_order',[])),
    'outcomes':dict(Counter(c['state'] for c in finished)),
    'active':[n for n,c in cases.items() if not c.get('finished')],
    'live_checkpoint':live,
    'recent_mean_s':statistics.mean(durations[-3:]) if durations else None,
    'estimated_remaining_s':remaining*statistics.mean(durations[-3:]) if durations else None,
    'errors':report['errors'][-3:]},indent=2))
