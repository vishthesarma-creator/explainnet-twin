"""One-time verified transition from prior review services to the ownership-aware launcher."""
import json
import os
import signal
import time
from pathlib import Path

from explainnet.app_launcher import identity, occupied, request
from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now

ROOT=Path(__file__).resolve().parents[1]


def main():
    if os.geteuid()==0: raise ValueError('Run as the ordinary application user')
    config=ROOT/'artifacts/stage6/runtime/config.json'
    settings=load_settings(config)
    with Store(settings.database_path).connection() as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM lab_action_state WHERE state IN ('applying','verifying','rolling_back')").fetchone()[0]==0
    candidates=[]
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit(): continue
        item=identity(int(directory.name))
        if not item or item['uid']!=os.geteuid() or item['cwd']!=str(ROOT): continue
        argv=item['argv']
        backend='explainnet.cli' in argv and str(config) in argv and argv[-1:] == ['serve']
        dashboard='streamlit' in argv and str(ROOT/'src/explainnet/dashboard/app.py') in argv and '--server.port=8501' in argv
        if backend or dashboard: candidates.append({'component':'backend' if backend else 'dashboard','identity':item})
    if sum(r['component']=='backend' for r in candidates)>1 or sum(r['component']=='dashboard' for r in candidates)>1:
        raise ValueError('Ambiguous prior service identities; nothing stopped')
    control=request(f'http://127.0.0.1:{settings.port}/v1/lab/control')
    assert not control['auto_enabled'] and not control['allow_observed_only']
    report={'at_utc':utc_now(),'prior_services':candidates,'active_jobs':0,'active_actions':0,'control':control}
    atomic_json(ROOT/'artifacts/stage14/review_service_transition.json',report)
    for record in candidates:
        item=record['identity']; pid=item['pid']
        if identity(pid)!=item: raise ValueError('Prior process identity changed; no signal sent')
        if record['component']=='backend':
            request(f'http://127.0.0.1:{settings.port}/v1/control/stop',{})
        else: os.kill(pid,signal.SIGTERM)
        end=time.monotonic()+110
        while identity(pid)==item and time.monotonic()<end: time.sleep(.25)
        if identity(pid)==item: raise RuntimeError('Owned prior service is still shutting down; no forced kill')
    assert not occupied(settings.port) and not occupied(8501)
    report['owned_prior_services_stopped']=True
    atomic_json(ROOT/'artifacts/stage14/review_service_transition.json',report)
    print(json.dumps({'status':'prior_owned_review_services_stopped','count':len(candidates)}))


if __name__=='__main__': main()
