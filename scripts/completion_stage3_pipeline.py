"""Bounded resumable root supervisor; application/model work always runs as UID1000."""
import argparse
import fcntl
import json
import os
import pwd
import signal
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/completion_stage3'
PYTHON=ROOT/'.venv/bin/python'
CONFIG=OUT/'runtime/config.json'


def read(path): return json.loads(path.read_text())


def write(path,value):
    temp=path.with_suffix('.tmp'); temp.write_text(json.dumps(value,indent=2)+'\n'); temp.replace(path)


def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
    except OSError:
        return False


def http(cfg,route,body=None):
    req=urllib.request.Request(f"http://127.0.0.1:{cfg['port']}"+route,
        data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r: return json.load(r)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','status'])
    parser.add_argument('--resume',action='store_true'); parser.add_argument('--detach',action='store_true')
    args=parser.parse_args()
    if args.action=='status':
        print(json.dumps(read(OUT/'pipeline.json'),indent=2)); return
    if os.geteuid()!=0: raise ValueError('Use root OS Python for supervision; application children are UID1000')
    if args.detach:
        pid=os.fork()
        if pid:
            print(json.dumps({'pipeline_pid':pid,'checkpoint':str(OUT/'pipeline.json')})); return
        os.setsid()
        fd=os.open(OUT/'pipeline.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
        os.dup2(fd,1);os.dup2(fd,2);os.close(fd);os.dup2(os.open('/dev/null',os.O_RDONLY),0)
    uid=1000; gid=pwd.getpwuid(uid).pw_gid
    cfg=read(CONFIG); protocol=read(OUT/'protocol.json'); env=os.environ|{'PYTHONPATH':str(ROOT/'src')}
    api=agent=None
    with (OUT/'pipeline.lock').open('a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Existing completion3 pipeline owns lock; no duplicate launched'); return
        old=read(OUT/'pipeline.json') if (OUT/'pipeline.json').exists() else None
        if old and not args.resume: raise ValueError('Existing checkpoint requires --resume')
        if old and old.get('retained_analysis_services'):
            raise ValueError('Retained analysis ownership requires explicit reconciliation; no new owner or mutation replay launched')
        state=old or {'protocol_hash':protocol['protocol_hash'],'steps':[],'started_utc':datetime.now(UTC).isoformat()}
        if state['protocol_hash']!=protocol['protocol_hash']: raise ValueError('Protocol changed; resume refused')
        state.update(pid=os.getpid(),state='checking_pilot',error=None)
        stopping=False
        def stop(_s,_f):
            nonlocal stopping
            stopping=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        def save():
            state['updated_utc']=datetime.now(UTC).isoformat();write(OUT/'pipeline.json',state)
        def ordinary(argv,timeout=60):
            return subprocess.run([str(PYTHON),*argv],cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[],
                capture_output=True,text=True,timeout=timeout,check=False)
        def status():
            result=ordinary(['scripts/status_completion_stage3.py'],60)
            if result.returncode: state['report_error']=result.stderr[-2000:];save()
        def run_step(name,timeout):
            if stopping:raise RuntimeError('Stop requested before '+name+'; no new phase submitted')
            if any(s['name']==name and s.get('exit_code')==0 for s in state['steps']): return
            state['state']=name;save();start=time.monotonic()
            with (OUT/(name+'.log')).open('a') as log:
                child=subprocess.Popen([str(PYTHON),'scripts/complete_stage3_analysis.py',name,'--config',str(CONFIG)],
                    cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            state['active_child']={'name':name,'pid':child.pid};save()
            while child.poll() is None:
                if stopping or time.monotonic()-start>timeout:
                    child.terminate()
                    try: child.wait(180)
                    except subprocess.TimeoutExpired: raise RuntimeError('Child shutdown unresolved; retained owner, no forced replay') from None
                    raise RuntimeError(name+' canceled or exceeded declared timeout; inspect checkpoint before resume')
                time.sleep(10)
            state['steps'].append({'name':name,'exit_code':child.returncode,'elapsed_ms':(time.monotonic()-start)*1000})
            state.pop('active_child',None);save();status()
            if child.returncode: raise RuntimeError(name+' failed; no automatic retry, inspect '+name+'.log')
        try:
            save();status()
            pilot=read(OUT/'dataset/pilot_quality_report.json')
            if not pilot['structural_checks_passed'] or pilot['shortfalls'] or pilot['accepted_windows']!=10:
                raise ValueError('Five-class measured pilot has not qualified; long collection prohibited')
            prior=read(OUT/'runtime/supervisor.json')
            if prior.get('state')=='completed' and alive(prior['supervisor_pid']):
                deadline=time.monotonic()+180
                while alive(prior['supervisor_pid']) and time.monotonic()<deadline:time.sleep(1)
                if alive(prior['supervisor_pid']):raise RuntimeError('Prior supervisor cleanup/archive still active')
            import sqlite3
            with sqlite3.connect('file:'+cfg['data_dir']+'/explainnet.sqlite3?mode=ro',uri=True) as db:
                row=db.execute("SELECT batch_id,state FROM dataset_batches WHERE json_extract(payload_json,'$.schedule.schedule_id')='c3_representative_v1'").fetchone()
            if not row or row[1]!='completed':
                state['state']='collecting';save()
                sup=read(OUT/'runtime/supervisor.json')
                active=(sup.get('schedule')==str(OUT/'schedule.json') and sup.get('state')=='running' and alive(sup.get('supervisor_pid',0)))
                if not active:
                    argv=['/usr/bin/python3','scripts/dataset_supervisor.py','--schedule',str(OUT/'schedule.json'),
                        '--runtime',str(OUT/'runtime'),'--uid','1000','--detach']
                    if row: argv+=['--resume',row[0]]
                    result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=30,check=True)
                    state['collection_launch']=json.loads(result.stdout); save()
                start=state.setdefault('collection_started_monotonic_s',time.monotonic()); last_status=0
                save()
                while True:
                    sup=read(OUT/'runtime/supervisor.json')
                    if sup.get('schedule')==str(OUT/'schedule.json'):
                        state['collection']={k:sup.get(k) for k in ['batch_id','state','accepted_windows','completed_episodes','current_episode','error']};save()
                        if sup['state'] in {'failed','canceled','interrupted'}:
                            raise RuntimeError('Collection '+sup['state']+': '+str(sup.get('error') or sup.get('errors')))
                        if sup['state']=='completed' and not alive(sup['supervisor_pid']):break
                    if stopping or time.monotonic()-start>172800:
                        if sup.get('batch_id'): http(cfg,'/v1/datasets/cancel',{'batch_id':sup['batch_id']})
                        raise RuntimeError('Collection canceled or48-hour supervision bound reached; typed cleanup requested, checkpoint retained')
                    if time.monotonic()-last_status>60:status();last_status=time.monotonic()
                    time.sleep(10)
            # Collection supervisor has finished scoped cleanup/archive. The same
            # isolated owner/store is reused for ordinary training/backend checks.
            if stopping:raise RuntimeError('Stop requested; no postcollection analysis launched')
            state['state']='starting_analysis_backend';save()
            root_state=f"/var/lib/explainnet-stage6-{cfg['port']}"
            with (OUT/'analysis_agent.log').open('a') as log:
                agent=subprocess.Popen(['/usr/bin/python3','-m','explainnet.agent_server','--allow-uid','1000',
                    '--socket',cfg['agent_socket'],'--state-dir',root_state,'--stream-receivers'],cwd=ROOT,env=env,
                    stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+30
            while not Path(cfg['agent_socket']).exists() and time.monotonic()<deadline:
                if agent.poll() is not None:raise RuntimeError('Analysis owner startup failed; no global cleanup')
                time.sleep(.2)
            with (OUT/'analysis_api.log').open('a') as log:
                api=subprocess.Popen([str(PYTHON),'-m','explainnet.cli','--config',str(CONFIG),'serve'],cwd=ROOT,env=env,
                    user=uid,group=gid,extra_groups=[],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                try:
                    if http(cfg,'/v1/health')['worker_live']:break
                except OSError:pass
                if api.poll() is not None:raise RuntimeError('Analysis API startup failed')
                time.sleep(.5)
            else:raise RuntimeError('Analysis API readiness timeout')
            state['analysis_processes']={'api_pid':api.pid,'agent_pid':agent.pid};save()
            for name,timeout in [('train',3600),('evaluate',7200),('backend',1800),('labs',43200),('report',300)]:
                run_step(name,timeout)
            state['state']='finished';save()
        except Exception as exc:  # noqa: BLE001 - durable terminal checkpoint; never retry silently
            state.update(state='blocked',error=str(exc));save()
        finally:
            settled=True
            if api and api.poll() is None:
                try:
                    http(cfg,'/v1/lab/automation/stop',{})
                    control=http(cfg,'/v1/lab/control')
                    if control.get('active_workflow_id'):
                        http(cfg,'/v1/lab/cancel',{'workflow_id':control['active_workflow_id']})
                    end=time.monotonic()+180
                    while control.get('active_workflow_id') and time.monotonic()<end:
                        time.sleep(.5);control=http(cfg,'/v1/lab/control')
                    if control.get('active_workflow_id'):raise RuntimeError('Active verification/rollback has not settled')
                    for action in control.get('unsettled_action_ids',[]):
                        state.setdefault('cleanup_rollbacks',[]).append(http(cfg,'/v1/lab/actions/'+action+'/rollback',{}));save()
                    control=http(cfg,'/v1/lab/control')
                    if control.get('unsettled_action_ids') or control.get('cleanup_pending_workflow_ids'):
                        raise RuntimeError('Action/twin ownership remains unsettled; preserve services for explicit reconciliation')
                    http(cfg,'/v1/control/stop',{});api.wait(180)
                except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
                    settled=False
                    state.update(cleanup_error='API cleanup unresolved: '+str(exc),retained_analysis_services=True,state='blocked');save()
            if settled and agent and agent.poll() is None:
                agent.terminate()
                try:agent.wait(90)
                except subprocess.TimeoutExpired:
                    state.update(cleanup_error='Root owner cleanup unresolved; no forced kill',retained_analysis_services=True,state='blocked');save()
            status()
            fcntl.flock(lock,fcntl.LOCK_UN)
    print(json.dumps({'state':state['state'],'error':state.get('error')}),flush=True)


if __name__=='__main__': main()
