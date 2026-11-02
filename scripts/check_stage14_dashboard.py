"""Read-only six-page integration test against a selected actual backend."""
import argparse
import json
import os
import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

from explainnet.config import load_settings
from explainnet.dashboard.client import ApiClient, ClientSettings
from explainnet.dashboard_api import DashboardStatus
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store, utc_now

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cfg=load_settings(args.config)
    os.environ['EXPLAINNET_API_URL']=f'http://127.0.0.1:{cfg.port}'
    client=ApiClient(ClientSettings(api_url=os.environ['EXPLAINNET_API_URL'],timeout_s=30))
    before=client.get('/v1/dashboard/status',DashboardStatus)
    store=Store(cfg.database_path)
    with store.connection() as db:
        jobs_before=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        events_before=db.execute('SELECT count(*) FROM audit_events').fetchone()[0]
    catalog=client.get('/v1/dashboard/evidence')['records']
    downloaded=[]
    for row in catalog:
        if row['available']:
            assert client.get('/v1/dashboard/evidence/'+row['artifact_id'])['artifact_id']==row['artifact_id']
            downloaded.append(row['artifact_id'])
    app=AppTest.from_file(ROOT/'src/explainnet/dashboard/app.py')
    pages=[]
    for name in ('overview','network','incidents','twin','recovery','evidence'):
        start=time.monotonic()
        if name!='overview': app.switch_page('pages/'+name+'.py')
        app.run(timeout=90)
        assert not app.exception,[e.message for e in app.exception]
        assert not app.error,[e.value for e in app.error]
        pages.append({'page':name,'rendered':True,'elapsed_ms':(time.monotonic()-start)*1000})
    with store.connection() as db:
        jobs_after=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        events_after=db.execute('SELECT count(*) FROM audit_events').fetchone()[0]
    after=client.get('/v1/dashboard/status',DashboardStatus)
    assert jobs_before==jobs_after and events_before==events_after
    assert before['control']==after['control']
    assert not after['control']['auto_enabled'] and not after['control']['allow_observed_only']
    value={'stage':14,'status':'passed','at_utc':utc_now(),'pages':pages,'app_uid':os.geteuid(),
        'api_version':after['api_version'],'real_model_count':after['models']['registered_count'],
        'ready_shap_count':after['explanations']['ready_count'],'agent_available':after['agent']['available'],
        'live_originals':[n['instance_id'] for n in after['agent']['instances'] if n.get('state')=='running' and n.get('role')=='original'],
        'approved_downloads':downloaded,'no_jobs_or_audits_from_navigation':True,'control_unchanged':True,
        'visual_limitation':'Actual HTTP and supported Streamlit AppTest; no supported browser automation/pixel verification available'}
    atomic_json(args.output,value)
    print(json.dumps(value,indent=2))


if __name__=='__main__': main()
