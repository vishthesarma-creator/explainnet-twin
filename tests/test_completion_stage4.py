"""UI/API software fixtures, never measured packet or research acceptance."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from test_dashboard import settings, ui_fixture

from explainnet.api import create_app
from explainnet.dashboard.client import ApiClient
from explainnet.dashboard.four_pages import refusal_rows
from explainnet.storage import Store

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('size',[5,10,15])
def test_network_launch_accepts_validated_scale_templates(tmp_path,size):
    import yaml
    cfg=settings(tmp_path)
    topology=tmp_path/'topology.yaml'
    topology.write_text(yaml.safe_dump(yaml.safe_load((ROOT/'config/topology.yaml').read_text())))
    cfg=cfg.model_copy(update={'topology_file':topology})
    store=Store(cfg.database_path);store.initialize()
    client=TestClient(create_app(cfg))
    response=client.post('/v1/networks/start',json={'instance_id':'fixture_scale','switches':size})
    assert response.status_code==202
    job=store.get_job(response.json()['job_id'])
    assert len(job['payload']['definition']['switches'])==size
    assert job['type']=='network_start'
    assert client.post('/v1/networks/start',json={'instance_id':'fixture','switches':99}).status_code==422


@pytest.mark.parametrize('populated',[False,True])
@pytest.mark.parametrize('route',['live','diagnosis','twin_recovery','results'])
def test_four_routes_share_shell_and_never_submit(monkeypatch,populated,route):
    mapping=ui_fixture(populated)
    mapping['/v1/demo/host-status']={'active':False,'state':'fixture'}
    calls=[]
    def fake(self,path,method='GET',body=None,key=None,model=None):
        calls.append(method)
        assert method=='GET','Navigation must not mutate'
        value=deepcopy(mapping.get(path.split('?')[0],{'records':[]}))
        return model.model_validate(value).model_dump() if model else value
    monkeypatch.setattr(ApiClient,'request',fake)
    app=AppTest.from_file(str(ROOT/'src/explainnet/dashboard/app.py')).run(timeout=60)
    if route!='live':app.switch_page('page_routes/'+route+'.py').run(timeout=60)
    assert not app.exception,[x.message for x in app.exception]
    assert any(b.label=='Refresh now' for b in app.button)
    assert any(t.label=='Auto-refresh every 10 seconds' for t in app.toggle)
    app.button[[b.label for b in app.button].index('Refresh now')].click().run(timeout=60)
    assert not app.exception and set(calls)=={'GET'}


@pytest.mark.parametrize('legacy,target',[('network','Live Network'),('incidents','Diagnosis'),('twin','Twin & Recovery'),('recovery','Twin & Recovery'),('evidence','Results'),('overview','Live Network')])
def test_legacy_routes_redirect_with_persistent_controls(monkeypatch,legacy,target):
    mapping=ui_fixture(False)
    def fake(self,path,method='GET',body=None,key=None,model=None):
        assert method=='GET'
        result=deepcopy(mapping.get(path.split('?')[0],{'records':[]}))
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient,'request',fake)
    app=AppTest.from_file(str(ROOT/'src/explainnet/dashboard/app.py')).run(timeout=60)
    app.switch_page('page_routes/'+legacy+'.py').run(timeout=60)
    assert not app.exception and target in [x.value for x in app.title]
    assert any(x.label=='Refresh now' for x in app.button)


def test_exact_nested_fidelity_reasons_are_readable():
    rows=refusal_rows({'state':'insufficient-evidence','trials':[{'family':'no_change','fidelity':{
        'status':'fail','metrics':[{'metric':'rtt_p95_ms','status':'fail','original':66.8,'twin':97.0,'absolute_error':30.2,'tolerance':30.04}]}}]})
    text=json.dumps(rows)
    assert 'rtt_p95_ms' in text and '30.04' in text and 'trials[0].fidelity.metrics[0]' in text


def test_nominal_reference_refuses_active_fault_before_capture(tmp_path,monkeypatch):
    from explainnet import demo_reference
    from explainnet.network_contracts import InstanceRequest
    monkeypatch.setattr(demo_reference,'Path',lambda _:tmp_path/'lock')
    worker=SimpleNamespace(coordinator=SimpleNamespace(control=dict,lifecycle=dict),
        agent=SimpleNamespace(network_inspect=lambda _:{'state':'running','live_verified':True},
            scenario_inspect=lambda _:{'laboratory_journal':{'state':'running','configuration':{'kind':'latency'}}}),
        twins=SimpleNamespace(capture=lambda *a:pytest.fail('Impaired source must not become nominal')))
    with pytest.raises(ValueError,match='active fault'):demo_reference.capture_reference(worker,InstanceRequest(instance_id='original'))


def test_nominal_capture_ordinals_have_distinct_durable_rpc_identity(tmp_path,monkeypatch):
    from explainnet import demo_reference
    from explainnet.agent import RPC_CONTEXT
    from explainnet.network_contracts import InstanceRequest
    store=Store(tmp_path/'e.sqlite3');store.initialize()
    monkeypatch.setattr(demo_reference,'Path',lambda _:tmp_path/'lock')
    seen=[]
    def capture(instance,duration):
        context=RPC_CONTEXT.get();seen.append(context)
        return {'window':{'window_id':'w_'+context,'instance_id':instance}}
    worker=SimpleNamespace(store=store,coordinator=SimpleNamespace(control=dict,lifecycle=dict),
        agent=SimpleNamespace(network_inspect=lambda _:{'state':'running','live_verified':True,'definition':{'fixture':True},'selected_paths':{'critical':'primary'}},
            scenario_inspect=lambda _:{}),twins=SimpleNamespace(capture=capture,pilot_reference=lambda **kw:({'fixture':True},{'policy_hash':'fixture'})))
    token=RPC_CONTEXT.set('fixture_job')
    try:
        result=demo_reference.capture_reference(worker,InstanceRequest(instance_id='original'))
        assert RPC_CONTEXT.get()=='fixture_job'
    finally:RPC_CONTEXT.reset(token)
    assert seen==['fixture_job_capture_0','fixture_job_capture_1']
    assert len(set(result['baseline']['window_ids']))==2


def test_new_read_endpoints_and_allowlisted_downloads_have_no_db_mutation(tmp_path,monkeypatch):
    from explainnet import dashboard_api
    monkeypatch.setattr(dashboard_api,'ROOT',tmp_path)
    cfg=settings(tmp_path);store=Store(cfg.database_path);store.initialize()
    client=TestClient(create_app(cfg))
    with store.connection() as db:before=db.total_changes
    assert client.get('/v1/demo/reference/original').json()=={'reference':None}
    assert client.get('/v1/dashboard/deliverables').json()=={'records':[]}
    assert client.get('/v1/dashboard/deliverables/secret').status_code==422
    assert client.get('/v1/dashboard/deliverables/report-pdf').status_code==404
    folder=tmp_path/'deliverables/completion4';folder.mkdir(parents=True)
    secret=tmp_path/'private.pdf';secret.write_bytes(b'private')
    (folder/'ExplainNet_Twin_Report_Reviewed.pdf').symlink_to(secret)
    assert client.get('/v1/dashboard/deliverables/report-pdf').status_code==404
    with store.connection() as db:
        assert db.total_changes==before
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
