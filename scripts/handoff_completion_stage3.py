"""Upgrade only the idle collection-watching controller; retain the active owner."""
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/completion_stage3'


def identity(pid):
    base=Path('/proc')/str(pid)
    stat=base.joinpath('stat').read_text().rsplit(')',1)[1].split()
    return {'pid':pid,'state':stat[0],'start_ticks':int(stat[19]),'uid':base.stat().st_uid,
        'cwd':str(base.joinpath('cwd').resolve()),
        'argv':[s.decode() for s in base.joinpath('cmdline').read_bytes().split(b'\0') if s]}


def write(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def same(left,right):
    return {k:v for k,v in left.items() if k!='state'}=={k:v for k,v in right.items() if k!='state'}


def main():
    if os.geteuid()!=0:raise ValueError('Root controller identity is required; application/owner processes are not signaled')
    receipt=OUT/'controller_handoff.json'
    if receipt.exists():raise ValueError('One-time handoff already attempted; inspect receipt, no replay')
    state=json.loads((OUT/'pipeline.json').read_text());sup=json.loads((OUT/'runtime/supervisor.json').read_text())
    if state['state']!='collecting' or state.get('active_child') or state.get('analysis_processes'):
        raise ValueError('Only a controller watching active collection can be handed off')
    owner=identity(state['pid'])
    if (owner['uid']!=0 or owner['cwd']!=str(ROOT) or len(owner['argv'])<3
            or str((ROOT/owner['argv'][1]).resolve())!=str(ROOT/'scripts/completion_stage3_pipeline.py')
            or owner['argv'][2]!='run' or owner['state']=='Z'):
        raise ValueError('Controller identity mismatch; nothing signaled')
    dispositions=dict(line.split(':',1) for line in Path(f"/proc/{owner['pid']}/status").read_text().splitlines() if ':' in line)
    bit=1<<(signal.SIGUSR2-1)
    if int(dispositions['SigCgt'],16)&bit or int(dispositions['SigIgn'],16)&bit:
        raise ValueError('Controller SIGUSR2 disposition differs; nothing signaled')
    kept={k:identity(sup[k]) for k in ['supervisor_pid','agent_pid','api_pid']}
    if sup['state']!='running' or any(v['state']=='Z' or v['cwd']!=str(ROOT) for v in kept.values()):
        raise ValueError('Collection is not independently live; nothing signaled')
    if (kept['supervisor_pid']['uid']!=0 or kept['agent_pid']['uid']!=0 or kept['api_pid']['uid']!=1000
            or 'scripts/dataset_supervisor.py' not in kept['supervisor_pid']['argv']
            or 'explainnet.agent_server' not in kept['agent_pid']['argv']
            or kept['api_pid']['argv']!=[str(ROOT/'.venv/bin/python'),str(ROOT/'.venv/bin/explainnet'),
                '--config',str(OUT/'runtime/config.json'),'serve']):
        raise ValueError('Collection service identity mismatch')
    record={'at_utc':datetime.now(UTC).isoformat(),'before_controller':owner,'preserved':kept,
        'batch_id':sup['batch_id'],'accepted_before':sup['accepted_windows'],'signal':'SIGUSR2 to controller only',
        'reason':'Replace the detached watch-only controller without its SIGTERM dataset-cancel handler; no laboratory/API/collector process is restarted',
        'state':'intent_persisted'}
    write(receipt,record)
    if not same(identity(owner['pid']),owner):raise ValueError('Controller changed after checkpoint')
    os.kill(owner['pid'],signal.SIGUSR2)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        try:
            if identity(owner['pid'])['state']=='Z':break
        except FileNotFoundError:break
        time.sleep(.1)
    else:raise RuntimeError('Prior controller remains live; no new controller launched')
    for key,expected in kept.items():
        if not same(identity(expected['pid']),expected):raise RuntimeError('Preserved service identity changed: '+key)
    state=json.loads((OUT/'pipeline.json').read_text())
    state['collection_started_monotonic_s']=owner['start_ticks']/os.sysconf('SC_CLK_TCK')
    state['controller_handoff_receipt']=str(receipt)
    write(OUT/'pipeline.json',state)
    result=subprocess.run(['/usr/bin/python3','scripts/completion_stage3_pipeline.py','run','--resume','--detach'],
        cwd=ROOT,env=os.environ|{'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=30,check=True)
    record.update(state='new_controller_launched',launch=json.loads(result.stdout),preserved_after=kept)
    write(receipt,record);print(json.dumps(record['launch']))


if __name__=='__main__':main()
