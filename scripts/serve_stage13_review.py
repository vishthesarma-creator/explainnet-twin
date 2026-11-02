"""Start ordinary-user loopback API/UI for review; never starts a root agent."""
import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'


def reachable(url):
    try:
        with urllib.request.urlopen(url,timeout=5) as response:
            return response.status==200
    except (OSError,urllib.error.URLError):
        return False


def main():
    if os.geteuid()==0:
        raise ValueError('Run API/dashboard as the ordinary application user')
    settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
    parser=argparse.ArgumentParser()
    parser.add_argument('--restart-api',action='store_true',help='Restart only the exact owned API recorded by this launcher')
    args=parser.parse_args()
    if args.restart_api:
        previous=json.loads((OUT/'review_services.json').read_text())
        pid=previous['processes']['api']['pid']
        argv=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if b'explainnet.cli' not in argv or str(ROOT/'artifacts/stage6/runtime/config.json').encode() not in argv:
            raise ValueError('Recorded API process identity changed; no signal sent')
        os.kill(pid,signal.SIGTERM)
        deadline=time.monotonic()+20
        while Path(f'/proc/{pid}/cmdline').exists() and Path(f'/proc/{pid}/cmdline').read_bytes() and time.monotonic()<deadline:
            time.sleep(.5)
        if Path(f'/proc/{pid}/cmdline').exists() and Path(f'/proc/{pid}/cmdline').read_bytes():
            with sqlite3.connect('file:'+str(settings.database_path)+'?mode=ro',uri=True) as db:
                active=db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if active:
                raise RuntimeError('Owned API still has active jobs; no forced stop or duplicate started')
            if Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')!=argv:
                raise ValueError('API identity changed during shutdown; no further signal sent')
            os.kill(pid,signal.SIGKILL)
            atomic_json(OUT/'review_api_bounded_stop.json',{'at_utc':utc_now(),'pid':pid,
                'active_jobs':active,'grace_s':20,'reason':'Owned review API stuck draining a read-only query; exact identity verified'})
            time.sleep(.5)
    processes={}
    commands={'api':([sys.executable,'-m','explainnet.cli','--config',str(ROOT/'artifacts/stage6/runtime/config.json'),'serve'],
        f'http://127.0.0.1:{settings.port}/v1/health'),
        'dashboard':([sys.executable,str(ROOT/'scripts/launch_dashboard.py'),'--config',str(ROOT/'artifacts/stage6/runtime/config.json')],
            'http://127.0.0.1:8501/_stcore/health')}
    for name,(argv,url) in commands.items():
        if reachable(url):
            processes[name]={'already_reachable':True,'url':url}
            continue
        with (OUT/('review_'+name+'.log')).open('a') as output:
            child=subprocess.Popen(argv,cwd=ROOT,env=os.environ|{'PYTHONPATH':str(ROOT/'src')},
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+60
        while not reachable(url) and time.monotonic()<deadline and child.poll() is None:
            time.sleep(.5)
        if not reachable(url):
            raise RuntimeError(name+' did not become ready; inspect its owned log')
        processes[name]={'pid':child.pid,'url':url,'ready':True}
    receipt={'at_utc':utc_now(),'app_uid':os.geteuid(),'processes':processes,'root_agent_started':False}
    atomic_json(OUT/'review_services.json',receipt)
    print(json.dumps(receipt,indent=2))


if __name__=='__main__': main()
