#!/usr/bin/env python3
"""Explicit Stage 13 continuation: wait for data gate, then run existing local steps.

Root supervises only; all application/model commands execute as the ordinary user.
No failed data campaign is automatically restarted. No Stage 14 command exists.
"""
import argparse
import json
import os
import pwd
import sqlite3
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--detach',action='store_true'); args=parser.parse_args()
    if args.detach:
        pid=os.fork()
        if pid:
            print(json.dumps({'pipeline_pid':pid,'checkpoint':str(OUT/'pipeline.json')})); return
        os.setsid()
        fd=os.open(OUT/'pipeline.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
        os.dup2(fd,1); os.dup2(fd,2); os.close(fd); os.dup2(os.open('/dev/null',os.O_RDONLY),0)
    uid=1000; gid=pwd.getpwuid(uid).pw_gid
    env=os.environ|{'PYTHONPATH':str(ROOT/'src'),'MPLCONFIGDIR':'/tmp/explainnet-stage13-matplotlib'}
    config=ROOT/'artifacts/stage6/runtime/config.json'
    record={'stage':13,'pid':os.getpid(),'started_utc':datetime.now(UTC).isoformat(),'state':'waiting_for_dataset','steps':[]}
    def save():
        temp=OUT/'pipeline.json.tmp'; temp.write_text(json.dumps(record,indent=2)+'\n'); temp.replace(OUT/'pipeline.json')
    def run(name,argv,timeout,privileged=False):
        record['state']=name; save(); started=time.monotonic()
        with (OUT/(name+'_execution.log')).open('a') as output:
            result=subprocess.run(argv,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=timeout,
                user=None if privileged else uid,group=None if privileged else gid,extra_groups=[],check=False)
        step={'name':name,'exit_code':result.returncode,'elapsed_ms':(time.monotonic()-started)*1000}
        record['steps'].append(step); save(); print(json.dumps(step),flush=True)
        if result.returncode: raise RuntimeError(name+' failed; inspect its execution log. No automatic retry.')
    python=str(ROOT/'.venv/bin/python')
    api=None
    try:
        deadline=time.monotonic()+10800
        while time.monotonic()<deadline:
            cfg=json.loads(config.read_text())
            with sqlite3.connect('file:'+cfg['data_dir']+'/explainnet.sqlite3?mode=ro',uri=True,timeout=5) as db:
                row=db.execute('SELECT state FROM dataset_batches WHERE batch_id=?',('db5a15991774142f0a8ef871522face4d',)).fetchone()
            record['dataset_state']=row[0]; save()
            if row[0]=='completed': break
            if row[0] in {'failed','canceled','interrupted'}: raise RuntimeError('Dataset '+row[0]+'; preserve checkpoint and fix cause before explicit resume')
            time.sleep(15)
        else: raise TimeoutError('Bounded dataset wait expired')
        # The dataset supervisor owns its services and finishes scoped archive first.
        until=time.monotonic()+180
        while Path(cfg['agent_socket']).exists() and time.monotonic()<until: time.sleep(1)
        if Path(cfg['agent_socket']).exists(): raise RuntimeError('Dataset agent cleanup still active')
        for action in ('audit','train','score'):
            run(action,[python,str(ROOT/'scripts/evaluate_stage13.py'),action],600)
        cli=[python,'-m','explainnet.cli','--config',str(config)]
        api_log=(OUT/'canonical_api.log').open('a')
        api=subprocess.Popen([*cli,'serve'],cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[],stdout=api_log,stderr=subprocess.STDOUT)
        record['canonical_api_pid']=api.pid; save()
        until=time.monotonic()+70
        while time.monotonic()<until:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/v1/health",timeout=5) as response:
                    if json.load(response)['worker_live']: break
            except OSError: pass
            if api.poll() is not None: raise RuntimeError('Canonical API exited; inspect canonical_api.log')
            time.sleep(.5)
        else: raise RuntimeError('Canonical API readiness deadline')
        run('backend',[python,str(ROOT/'scripts/evaluate_stage13.py'),'backend'],1200)
        run('labs',['/usr/bin/python3',str(ROOT/'scripts/stage13_lab_supervisor.py')],10800,privileged=True)
        run('report',[python,str(ROOT/'scripts/evaluate_stage13.py'),'report'],180)
        run('dashboard',[python,str(ROOT/'scripts/check_stage13_dashboard.py')],700)
        record['state']='evaluation_steps_finished'; record['ended_utc']=datetime.now(UTC).isoformat(); save()
    except Exception as exc:  # noqa: BLE001 - durable bounded pipeline failure, no hidden retries
        record.update(state='blocked',error=str(exc),ended_utc=datetime.now(UTC).isoformat()); save()
        print(json.dumps({'pipeline_error':str(exc)}),flush=True)
        return 1
    # Leave the ordinary API/dashboard available for review; native supervisor
    # already stopped its agent and verified its owned bridges are removed.
    return 0


if __name__=='__main__': raise SystemExit(main())
