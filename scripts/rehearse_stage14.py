#!/usr/bin/env python3
"""Bounded one-case supervisor. Root runs only stdlib/agent; app/UI use the ordinary UID."""
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
    parser.add_argument('--app-uid',type=int,default=1000)
    parser.add_argument('--dashboard-port',type=int,default=8502)
    args=parser.parse_args()
    if os.geteuid()!=0 or args.app_uid<1:
        raise ValueError('Run supervisor with OS Python as root and a non-root application UID')
    if not 1<=args.dashboard_port<=65535: raise ValueError('Invalid dashboard port')
    tag=uuid4().hex[:8]
    out=ROOT/'artifacts/stage14/rehearsals'/tag; out.mkdir(parents=True)
    if args.detach:
        pid=os.fork()
        if pid:
            print(json.dumps({'supervisor_pid':pid,'tag':tag,'report':str(out/'report.json')})); return 0
        os.setsid()
        fd=os.open(out/'supervisor.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
        os.dup2(fd,1); os.dup2(fd,2); os.close(fd); os.dup2(os.open('/dev/null',os.O_RDONLY),0)
    uid=args.app_uid; user=pwd.getpwuid(uid); gid=user.pw_gid
    lock_path=Path(f'/var/tmp/explainnet-experiment-{uid}.lock')
    try: fd=os.open(lock_path,os.O_RDONLY|os.O_NOFOLLOW)
    except FileNotFoundError:
        fd=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_RDONLY|os.O_NOFOLLOW,0o600); os.fchown(fd,uid,gid)
    lock=os.fdopen(fd,'r')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with socket.socket() as probe:
        probe.settimeout(.3)
        if probe.connect_ex(('127.0.0.1',args.dashboard_port))==0:
            raise ValueError('Rehearsal dashboard port occupied; no process stopped or network started')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
    data=Path(user.pw_dir)/'.local/share/explainnet/stage14/rehearsals'/tag/'data'
    subprocess.run(['/usr/bin/python3','-c','import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=False)',str(data)],
        user=uid,group=gid,extra_groups=[],timeout=10,check=True)
    socket_path=Path('/run')/('explainnet-stage14-'+tag)/'agent.sock'
    state=Path('/var/lib')/('explainnet-stage14-'+tag)
    cfg=out/'config.json'
    cfg.write_text(json.dumps({'schema_version':1,'data_dir':str(data),'runtime_dir':str(out/'run'),
        'agent_socket':str(socket_path),'host':'127.0.0.1','port':port,
        'topology_file':str(ROOT/'config/topology.yaml'),'traffic_profiles_file':str(ROOT/'config/stage14_traffic.yaml'),
        'lab_test_hooks':False,'telemetry':{'sample_interval_s':2.5,'window_s':10,'max_cpu_busy_fraction':.85,'max_memory_used_fraction':.85},
        'objective':{'max_rtt_ms':100,'max_loss_fraction':.02,'min_goodput_bps':1000000}},indent=2)+'\n')
    plan={'stage':14,'tag':tag,'declared_utc':datetime.now(UTC).isoformat(),'config':str(cfg),
        'scenario':'Five-switch high one-way latency, 8 Mbps critical / 5 Mbps bulk UDP, 1200-byte packets',
        'inference_mode':'Explicit observed-only; calibrated model/SHAP checked separately in canonical backend',
        'policy':'Existing frozen pilot fidelity, workflow_v1 and Stage 10/11 quality/service/protected-flow/rollback gates unchanged',
        'expected_path':['healthy refusal','persistent incident','snapshot','separate twin controls/candidates','recommendation or refusal',
            'explicit assisted application if eligible','two settled original verification windows','applicable Undo','scoped cleanup'],
        'source_workload_duration_s':900,'collector_duration_s':600,'driver_deadline_s':1400,
        'max_rehearsal_attempts_this_command':1,'retries':'No automatic retries or gate changes',
        'cleanup':'Stop automation, finish verification/rollback, stop collector, reset owned scenario, clean owned source; terminate only owned child services and agent',
        'dashboard_url':f'http://127.0.0.1:{args.dashboard_port}','no_test_scoring_or_training':True}
    (out/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    env=os.environ|{'PYTHONPATH':str(ROOT/'src')}
    cli=[str(ROOT/'.venv/bin/python'),'-m','explainnet.cli','--config',str(cfg)]
    before=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
    agent=api=ui=driver=None
    result={'stage':14,'tag':tag,'started_utc':datetime.now(UTC).isoformat(),'bridges_before':before,'app_uid':uid}
    logs={name:(out/(name+'.log')).open('w') for name in ('agent','api','dashboard')}
    try:
        subprocess.run([*cli,'init'],env=env,cwd=ROOT,user=uid,group=gid,extra_groups=[],timeout=60,check=True)
        agent=subprocess.Popen(['/usr/bin/python3','-m','explainnet.agent_server','--allow-uid',str(uid),
            '--socket',str(socket_path),'--state-dir',str(state),'--stream-receivers'],cwd=ROOT,env=env,
            stdout=logs['agent'],stderr=subprocess.STDOUT)
        end=time.monotonic()+30
        while not socket_path.exists() and time.monotonic()<end and agent.poll() is None: time.sleep(.2)
        if not socket_path.exists(): raise RuntimeError('Separate root agent failed startup')
        api=subprocess.Popen([*cli,'serve'],cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[],stdout=logs['api'],stderr=subprocess.STDOUT)
        ui=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/launch_dashboard.py'),'--config',str(cfg),
            '--port',str(args.dashboard_port)],cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[],start_new_session=True,
            stdout=logs['dashboard'],stderr=subprocess.STDOUT)
        driver=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/stage14_rehearsal_driver.py'),
            '--config',str(cfg),'--tag',tag],cwd=ROOT,env=env,user=uid,group=gid,extra_groups=[])
        result['driver_exit_code']=driver.wait(timeout=1400)
    except Exception as exc:  # noqa: BLE001 - preserve actual blocker without restarting a campaign
        result['error']=str(exc)
    finally:
        for child in (driver,api):
            if child and child.poll() is None:
                child.terminate()
                try: child.wait(timeout=110)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=10)
        if ui and ui.poll() is None:
            # This group contains only the explicitly owned launcher/Streamlit child.
            os.killpg(ui.pid,15)
            try: ui.wait(timeout=20)
            except subprocess.TimeoutExpired: os.killpg(ui.pid,9); ui.wait(timeout=10)
        if agent and agent.poll() is None:
            agent.terminate()
            try: agent.wait(timeout=110)
            except subprocess.TimeoutExpired: agent.kill(); agent.wait(timeout=10)
        after=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
        result.update({'ended_utc':datetime.now(UTC).isoformat(),'bridges_after':after,
            'owned_bridges_removed':set(before)==set(after),'preexisting_bridges_preserved':set(before)<=set(after),
            'socket_removed':not socket_path.exists()})
        archive=out/'rehearsal_evidence.tar.gz'
        with tarfile.open(archive,'x:gz') as output:
            if state.exists(): output.add(state,arcname='root_state')
            output.add(data,arcname='app_data')
        result['archive']=str(archive.relative_to(ROOT))
        (out/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n')
        (ROOT/'artifacts/stage14/latest_rehearsal.json').write_text(json.dumps({'tag':tag,'directory':str(out)},indent=2)+'\n')
        for log in logs.values(): log.close()
        lock.close()
        print(json.dumps(result),flush=True)
    return 0 if result.get('driver_exit_code')==0 and result.get('owned_bridges_removed') and result.get('socket_removed') else 1


if __name__=='__main__': raise SystemExit(main())
