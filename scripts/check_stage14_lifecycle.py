"""Fresh-shell local process/API/UI checks; no Mininet network or fault is created."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from explainnet.app_launcher import request
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now

ROOT=Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        return reservation.getsockname()[1]


def main():
    tag=uuid4().hex[:8]
    out=ROOT/'artifacts/stage14/lifecycle'/tag; out.mkdir(parents=True)
    data=Path.home()/'.local/share/explainnet/stage14/lifecycle'/tag
    config={'schema_version':1,'data_dir':str(data),'runtime_dir':str(out/'run'),
        'agent_socket':'/run/explainnet-stage14-unavailable-'+tag+'/agent.sock',
        'port':free_port(),'topology_file':str(ROOT/'config/topology.yaml'),'traffic_profiles_file':str(ROOT/'config/traffic.yaml')}
    cfg=out/'config.json'; cfg.write_text(json.dumps(config,indent=2)+'\n')
    ui_port=free_port()
    result={'stage':14,'at_utc':utc_now(),'tag':tag,'kind':'Actual ordinary-user local process/HTTP lifecycle; no packet laboratory',
        'commands':[],'checks':{},'app_uid':os.geteuid(),'no_network_created':True}
    base=[sys.executable,str(ROOT/'scripts/manage_app.py'),'--config',str(cfg),'--dashboard-port',str(ui_port)]
    env=os.environ|{'PYTHONPATH':str(ROOT/'src')}
    def run(command,expected=0):
        start=time.monotonic()
        r=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180,check=False)
        result['commands'].append({'argv':command,'exit_code':r.returncode,'elapsed_ms':(time.monotonic()-start)*1000,
            'stdout':r.stdout,'stderr':r.stderr})
        atomic_json(out/'report.json',result)
        if expected==0 and r.returncode: raise RuntimeError('Lifecycle command failed: '+r.stderr[-1500:])
        if expected!=0 and not r.returncode: raise RuntimeError('Occupied-port start unexpectedly succeeded')
        return r
    try:
        run([sys.executable,'-m','explainnet.cli','--config',str(cfg),'init'])
        run([*base,'check'])
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1',0)); unrelated.listen(16)
            blocked=config|{'port':unrelated.getsockname()[1]}
            blocked_cfg=out/'occupied_config.json'; blocked_cfg.write_text(json.dumps(blocked))
            run([sys.executable,str(ROOT/'scripts/manage_app.py'),'--config',str(blocked_cfg),'--dashboard-port',str(ui_port),'start'],expected=1)
            assert unrelated.getsockname()[1]==blocked['port'] and unrelated.fileno()>=0
            result['checks']['occupied_unrelated_listener_preserved']=True
        run([*base,'start'])
        state=json.loads(run([*base,'status']).stdout)
        assert all(c['owned'] and c['ready'] for c in state['components'].values())
        assert not state['readiness']['agent']['available']
        assert state['readiness']['models']['registered_count']==0
        assert not state['readiness']['control']['auto_enabled'] and not state['readiness']['control']['allow_observed_only']
        result['checks']['fresh_shell_start_and_actual_http']=True
        result['checks']['missing_agent_and_model_visible']=True
        store=Store(data/'explainnet.sqlite3')
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM network_instances').fetchone()[0]==0
        t=time.monotonic(); stopped=request(f"http://127.0.0.1:{config['port']}/v1/lab/automation/stop",{})
        result['checks']['stop_automation_response_ms']=(time.monotonic()-t)*1000
        assert stopped['new_actuation_prevented']
        run([*base,'stop'])
        after=json.loads(run([*base,'status']).stdout)
        assert not any(c['port_occupied'] for c in after['components'].values())
        result['checks']['bounded_owned_shutdown']=True
        run([*base,'start'])
        restarted=json.loads(run([*base,'status']).stdout)
        assert not restarted['readiness']['control']['auto_enabled'] and not restarted['readiness']['control']['allow_observed_only']
        result['checks']['restart_flags_disabled']=True
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM network_instances').fetchone()[0]==0
        result['checks']['no_automatic_jobs_or_network_on_start']=True
        result['status']='passed'
    except Exception as exc:
        result.update(status='failed',error=str(exc)); raise
    finally:
        try: run([*base,'stop'])
        except Exception as exc: result['cleanup_error']=str(exc)  # noqa: BLE001
        result['ended_utc']=utc_now()
        atomic_json(out/'report.json',result)
        atomic_json(ROOT/'artifacts/stage14/lifecycle_check.json',result)
        print(json.dumps({'status':result.get('status'),'checks':result['checks'],'report':str(out/'report.json')},indent=2))


if __name__=='__main__': main()
