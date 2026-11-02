"""Actual API/Streamlit evidence rendering after model/evaluation work; no lab mutations."""
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
settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
url=f'http://127.0.0.1:{settings.port}'
os.environ['EXPLAINNET_API_URL']=url
client=ApiClient(ClientSettings(api_url=url,timeout_s=30))
before=client.get('/v1/dashboard/status',DashboardStatus)
store=Store(settings.database_path)
with store.connection() as db: before_jobs=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
evidence=client.get('/v1/dashboard/evidence/evaluation')
assert evidence['evidence']['stage']==13
app=AppTest.from_file(ROOT/'src/explainnet/dashboard/app.py')
pages=[]
for name in ('overview','network','incidents','twin','recovery','evidence'):
    start=time.monotonic()
    if name!='overview': app.switch_page('pages/'+name+'.py')
    app.run(timeout=90)
    assert not app.exception,[e.message for e in app.exception]
    assert not app.error,[e.value for e in app.error]
    pages.append({'page':name,'rendered':True,'elapsed_ms':(time.monotonic()-start)*1000})
with store.connection() as db: after_jobs=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
after=client.get('/v1/dashboard/status',DashboardStatus)
assert before_jobs==after_jobs
assert not after['control']['auto_enabled'] and not after['control']['allow_observed_only']
report={'status':'passed','at_utc':utc_now(),'pages':pages,'api_version':after['api_version'],
    'real_model_count':after['models']['registered_count'],'real_ready_shap':after['explanations']['ready_count'],
    'stage13_evidence_available':True,'render_did_not_submit_jobs':True,
    'visual_limitation':'Supported Streamlit AppTest and real HTTP; no pixel-level browser verification'}
atomic_json(ROOT/'artifacts/stage13/dashboard_check.json',report)
print(json.dumps(report,indent=2))
