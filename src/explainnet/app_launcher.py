"""Ordinary-user lifecycle orchestration with exact process ownership checks."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dashboard.client import ClientSettings
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now

ROOT=Path(__file__).resolve().parents[2]


def identity(pid):
    """PID reuse, executable arguments, user and cwd must all match before signaling."""
    try:
        base=Path('/proc')/str(pid)
        stat=base.joinpath('stat').read_text().rsplit(')',1)[1].split()
        if stat[0]=='Z':
            return None
        return {'pid':pid,'start_ticks':stat[19],'uid':base.stat().st_uid,
            'argv':[v.decode() for v in base.joinpath('cmdline').read_bytes().split(b'\0') if v],
            'cwd':str(base.joinpath('cwd').resolve())}
    except (OSError,IndexError,UnicodeError):
        return None


def owned(record):
    if not record or not record.get('identity'):
        return False
    saved=record['identity']; argv=saved.get('argv',[])
    backend=len(argv)==6 and argv[1:4]==['-m','explainnet.cli','--config'] and argv[-1]=='serve'
    dashboard=(len(argv)>=5 and argv[1:4]==['-m','streamlit','run']
        and argv[4]==str(ROOT/'src/explainnet/dashboard/app.py') and '--server.address=127.0.0.1' in argv)
    return bool((backend or dashboard) and argv[0]==sys.executable and record.get('argv')==argv
        and saved.get('cwd')==str(ROOT) and saved.get('uid')==os.geteuid()
        and identity(saved['pid'])==saved)


def occupied(port):
    with socket.socket() as probe:
        probe.settimeout(.3)
        return probe.connect_ex(('127.0.0.1',port))==0


def request(url,body=None,timeout=5):
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError('Readiness response exceeds limit')
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode()


def ready(name,url):
    try:
        value=request(url)
        return bool(value.get('worker_live')) if name=='backend' and isinstance(value,dict) else value=='ok'
    except (OSError,ValueError,urllib.error.URLError):
        return False


def configuration(args):
    settings=load_settings(args.config)
    if not 1<=args.dashboard_port<=65535 or args.dashboard_port==settings.port:
        raise ValueError('Dashboard and API need distinct ports in 1..65535')
    api=ClientSettings(api_url=args.api_url or f'http://127.0.0.1:{settings.port}').api_url
    if api != f'http://127.0.0.1:{settings.port}':
        raise ValueError('API override differs from selected configuration; no silent backend redirection')
    return settings,api


def validate_binding(settings, api):
    actual = request(api + '/v1/config')
    if actual.get('config_hash') != settings.config_hash:
        raise ValueError('Running API configuration hash differs from the launcher; no laboratory operation allowed')
    bound = actual.get('identity') or {}
    if bound.get('database_path') != str(settings.database_path) or bound.get('api_url') != api:
        raise ValueError('Running API store/URL identity differs from the selected profile')
    return bound


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--dashboard-port',type=int,default=8501)
    parser.add_argument('--api-url',help='Explicit loopback dashboard API address; normally derived from config')
    parser.add_argument('--record',type=Path,help='Lifecycle receipt; default CONFIG runtime_dir/app_launcher.json')
    parser.add_argument('action',choices=['check','start','status','stop'])
    args=parser.parse_args()
    if os.geteuid()==0:
        parser.error('Run the API/dashboard launcher as the ordinary application user; start the root agent separately')
    settings,api=configuration(args)
    receipt=args.record or settings.runtime_dir/'app_launcher.json'
    if receipt.is_symlink():
        raise ValueError('Lifecycle receipt must not be a symlink')
    state=json.loads(receipt.read_text()) if receipt.exists() else {'schema_version':1,'components':{}}
    components=state['components']
    specs={
        'backend':{'port':settings.port,'url':f'http://127.0.0.1:{settings.port}/v1/health',
            'argv':[sys.executable,'-m','explainnet.cli','--config',str(args.config.resolve()),'serve']},
        'dashboard':{'port':args.dashboard_port,'url':f'http://127.0.0.1:{args.dashboard_port}/_stcore/health',
            'argv':[sys.executable,'-m','streamlit','run',str(ROOT/'src/explainnet/dashboard/app.py'),
                '--server.address=127.0.0.1',f'--server.port={args.dashboard_port}','--server.headless=true','--browser.gatherUsageStats=false']}}
    def save():
        state.update(at_utc=utc_now(),config=str(args.config.resolve()),config_hash=settings.config_hash,
            app_uid=os.geteuid(),dashboard_api_url=api)
        atomic_json(receipt,state)
    if args.action=='check':
        result={'at_utc':utc_now(),'app_uid':os.geteuid(),'python':sys.version.split()[0],
            'database_initialized':Store(settings.database_path).healthy(),
            'agent_socket_exists':settings.agent_socket.exists(),'api_port_occupied':occupied(settings.port),
            'dashboard_port_occupied':occupied(args.dashboard_port),'api_url':api,
            'root_agent_command':'/usr/bin/python3 -m explainnet.agent_server (launch separately as root)',
            'creates_network':False,'changes_recovery_mode':False}
    elif args.action=='start':
        if not Store(settings.database_path).healthy():
            raise ValueError('Database missing/migrations pending. Run explainnet --config CONFIG init; existing databases are preserved')
        if any(owned(r) for r in components.values()) and state.get('config_hash')!=settings.config_hash:
            raise ValueError('Configuration changed while owned services run; stop using the receipt before starting changed settings')
        if owned(components.get('dashboard')) and state.get('dashboard_api_url')!=api:
            raise ValueError('Dashboard API address changed; stop the owned dashboard before starting the new address')
        # Validate both ports before starting either service.
        for name,spec in specs.items():
            record=components.get(name)
            if owned(record) and record.get('argv')!=spec['argv']:
                raise ValueError(name+' is owned but uses different configuration/port; stop it using its original configuration first')
            if occupied(spec['port']) and not owned(record):
                raise ValueError(f"{name} port {spec['port']} is occupied by an unowned service. Nothing was stopped or started")
        environment=os.environ|{'PYTHONPATH':str(ROOT/'src'),'EXPLAINNET_API_URL':api,
            'EXPLAINNET_CONFIG_HASH':settings.config_hash, 'EXPLAINNET_CONFIG_PATH':str(args.config.resolve())}
        receipt.parent.mkdir(parents=True,exist_ok=True)
        for name,spec in specs.items():
            if not owned(components.get(name)):
                log=receipt.parent/(name+'.log')
                with log.open('a') as output:
                    child=subprocess.Popen(spec['argv'],cwd=ROOT,env=environment,stdin=subprocess.DEVNULL,
                        stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                components[name]={'identity':identity(child.pid),'argv':spec['argv'],'url':spec['url'],
                    'log':str(log),'state':'starting'}
                save()
            deadline=time.monotonic()+120
            while not ready(name,spec['url']) and time.monotonic()<deadline and owned(components[name]):
                time.sleep(.5)
            components[name]['state']='ready' if ready(name,spec['url']) else 'failed_readiness'
            save()
            if components[name]['state']!='ready':
                raise RuntimeError(name+' failed readiness; owned process and log retained in '+str(receipt))
            if name == 'backend':
                state['configuration_identity'] = validate_binding(settings, api)
                save()
        result=state
    elif args.action=='stop':
        for name in ('dashboard','backend'):
            record=components.get(name)
            if not owned(record):
                if record:
                    record['state']='not_owned_or_exited_no_signal_sent'
                continue
            # Uvicorn's existing graceful shutdown calls worker.stop(), which
            # finishes verification/rollback. No receipt-supplied URL is posted.
            os.kill(record['identity']['pid'],signal.SIGTERM)
            end=time.monotonic()+110
            while owned(record) and time.monotonic()<end:
                time.sleep(.25)
            record['state']='stopped' if not owned(record) else 'shutdown_pending_no_forced_kill'
            save()
            if owned(record):
                raise RuntimeError(name+' is still completing shutdown; inspect its log, leave the agent available for rollback')
        save(); result=state
    else:
        result={'at_utc':utc_now(),'components':{name:{'owned':owned(components.get(name)),
            'port_occupied':occupied(spec['port']),'ready':ready(name,spec['url']),
            'url':spec['url']} for name,spec in specs.items()}}
        try:
            result['configuration_identity'] = validate_binding(settings, api)
            value=request(f'http://127.0.0.1:{settings.port}/v1/dashboard/status')
            result['readiness']={k:value[k] for k in ('agent','dataset','models','explanations','control')}
        except (OSError,ValueError,KeyError):
            result['readiness']={'status':'backend unavailable/restarting; no mutation submitted'}
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
