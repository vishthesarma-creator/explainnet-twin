#!/usr/bin/env python3
"""Sequential root agent / ordinary-user API and evaluation driver; scoped cleanup."""
import argparse
import fcntl
import json
import os
import pwd
import socket
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--detach',action='store_true')
    parser.add_argument('--resume',help='Existing campaign directory name, only completed cases are skipped')
    args=parser.parse_args()
    tag=args.resume or uuid4().hex[:8]
    if not tag.isalnum() or len(tag)>16: raise ValueError('Invalid campaign ID')
    out=ROOT/'artifacts/stage13/labs'/tag; out.mkdir(parents=True,exist_ok=True)
    if args.detach:
        pid=os.fork()
        if pid:
            print(json.dumps({'supervisor_pid':pid,'campaign_id':tag,'report':str(out/'report.json')})); return
        os.setsid()
        fd=os.open(out/'supervisor.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
        os.dup2(fd,1); os.dup2(fd,2); os.close(fd)
        os.dup2(os.open('/dev/null',os.O_RDONLY),0)
    uid=1000; gid=pwd.getpwuid(uid).pw_gid
    lock_path=Path('/var/tmp/explainnet-experiment-1000.lock')
    try:
        lock_fd=os.open(lock_path,os.O_RDONLY|os.O_NOFOLLOW)
    except FileNotFoundError:
        lock_fd=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_RDONLY|os.O_NOFOLLOW,0o600)
        os.fchown(lock_fd,uid,gid)
    lock=os.fdopen(lock_fd,'r')  # Held through owned cleanup; flock needs no write/create access.
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    attempt=uuid4().hex[:8]
    data=Path('/tmp')/('explainnet-stage13-'+tag+'-'+attempt)/'data'
    data.mkdir(parents=True); os.chown(data.parent,uid,gid); os.chown(data,uid,gid)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
    sock=Path('/run')/('explainnet-stage13-'+tag+'-'+attempt)/'agent.sock'
    state=Path('/var/lib')/('explainnet-stage13-'+tag+'-'+attempt)
    cfg=out/('config_'+attempt+'.json')
    cfg.write_text(json.dumps({'schema_version':1,'data_dir':str(data),'runtime_dir':str(out/('run_'+attempt)),
        'agent_socket':str(sock),'port':port,'topology_file':str(ROOT/'config/topology.yaml'),
        'traffic_profiles_file':str(ROOT/'config/traffic.yaml'),'lab_test_hooks':False,
        'telemetry':{'sample_interval_s':2.5,'window_s':10,'max_cpu_busy_fraction':.85,'max_memory_used_fraction':.85},
        'objective':{'max_rtt_ms':100,'max_loss_fraction':.02,'min_goodput_bps':1000000}},indent=2))
    env=os.environ|{'PYTHONPATH':str(ROOT/'src')}
    cli=[str(ROOT/'.venv/bin/python'),'-m','explainnet.cli','--config',str(cfg)]
    before=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
    agent=api=driver=None
    outcome={'campaign_id':tag,'attempt_id':attempt,'started_utc':datetime.now(UTC).isoformat(),'bridges_before':before}
    with (out/('agent_'+attempt+'.log')).open('w') as agent_log,(out/('api_'+attempt+'.log')).open('w') as api_log:
        try:
            subprocess.run([*cli,'init'],env=env,cwd=ROOT,user=uid,group=gid,extra_groups=[],timeout=60,check=True)
            agent=subprocess.Popen(['/usr/bin/python3','-m','explainnet.agent_server','--allow-uid',str(uid),
                '--socket',str(sock),'--state-dir',str(state),'--stream-receivers'],env=env,cwd=ROOT,stdout=agent_log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+25
            while not sock.exists() and time.monotonic()<deadline and agent.poll() is None: time.sleep(.2)
            if not sock.exists(): raise RuntimeError('Agent startup failed')
            api=subprocess.Popen([*cli,'serve'],env=env,cwd=ROOT,user=uid,group=gid,extra_groups=[],stdout=api_log,stderr=subprocess.STDOUT)
            driver=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/stage13_lab_driver.py'),str(cfg),tag],
                env=env,cwd=ROOT,user=uid,group=gid,extra_groups=[])
            outcome['driver_exit_code']=driver.wait(timeout=10800)
        except Exception as exc:  # noqa: BLE001 - durable supervisor failure evidence
            outcome['error']=str(exc)
        finally:
            for process in (driver,api,agent):
                if process and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=100)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=10)
            after=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
            outcome.update(ended_utc=datetime.now(UTC).isoformat(),bridges_after=after,
                preexisting_bridges_preserved=set(before)<=set(after),owned_bridges_removed=set(before)==set(after))
            if state.exists():
                archive=out/('root_'+attempt+'.tar.gz')
                with tarfile.open(archive,'x:gz') as tar: tar.add(state,arcname='root_state')
            archive=out/('data_'+attempt+'.tar.gz')
            with tarfile.open(archive,'x:gz') as tar: tar.add(data,arcname='data')
            (out/('cleanup_'+attempt+'.json')).write_text(json.dumps(outcome,indent=2)+'\n')
            print(json.dumps(outcome),flush=True)
            lock.close()
    return 0 if outcome.get('driver_exit_code')==0 and outcome.get('owned_bridges_removed') else 1


if __name__=='__main__': raise SystemExit(main())
