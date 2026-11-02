"""Stage 14 integration/lifecycle safety fixtures; not packet experiment results."""
import json
import sys
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_dashboard import settings, ui_fixture
from test_workflow import coordinator

from explainnet import app_launcher
from explainnet.api import create_app
from explainnet.storage import Store


def test_eligibility_refreshes_matching_shap_without_persisting_or_actuating(tmp_path):
    c=coordinator(tmp_path)
    w={'state':'recommended','workflow_id':'w','diagnosis':{'status':'supported','model_id':'m'},
        'explanation':{'status':'pending','explanation_id':'x','window_id':'o'},'experiment_id':'e'}
    c.get=lambda _: deepcopy(w)
    c._mode_gate=lambda _: {'allow_observed_only':False}
    c.worker.explanations.get=lambda _: {'status':'ready','model_id':'m','window_id':'o'}
    c._save=Mock(side_effect=AssertionError('Read preview wrote a workflow'))
    def expired(_):
        raise ValueError('expired source recommendation')
    c.recovery.get=expired
    result=c.eligibility('w')
    assert not result['available'] and 'expired' in result['reason']
    assert w['explanation']['status']=='pending'
    c._save.assert_not_called()
    c.worker.explanations.get=lambda _: {'status':'ready','model_id':'different','window_id':'o'}
    assert 'lineage' in c.eligibility('w')['reason']


def test_preview_refuses_uncertain_diagnosis_even_in_assisted_mode(tmp_path):
    c=coordinator(tmp_path)
    c.get=lambda _: {'state':'recommended','diagnosis':{'status':'uncertain'},'explanation':{'status':'ready'}}
    c._mode_gate=lambda _: {'allow_observed_only':True}
    assert 'uncertainty' in c.eligibility('w')['reason']


def test_download_catalog_and_eligibility_get_do_not_submit_jobs(tmp_path):
    cfg=settings(tmp_path)
    store=Store(cfg.database_path); store.initialize()
    app=create_app(cfg)
    with TestClient(app) as client:
        with store.connection() as db:
            before=(db.execute('SELECT count(*) FROM jobs').fetchone()[0],db.execute('SELECT count(*) FROM audit_events').fetchone()[0])
        assert not client.get('/v1/dashboard/applicable/missing').json()['available']
        catalog=client.get('/v1/dashboard/evidence').json()['records']
        assert any(r['artifact_id']=='integration' for r in catalog)
        for row in catalog:
            if row['available']:
                assert client.get('/v1/dashboard/evidence/'+row['artifact_id']).status_code==200
        with store.connection() as db:
            after=(db.execute('SELECT count(*) FROM jobs').fetchone()[0],db.execute('SELECT count(*) FROM audit_events').fetchone()[0])
        assert after==before


def test_reused_pid_or_changed_command_is_never_owned(monkeypatch):
    original={'pid':12,'start_ticks':'40','uid':1000,
        'argv':[sys.executable,'-m','explainnet.cli','--config',str(app_launcher.ROOT/'config/example.yaml'),'serve'],
        'cwd':str(app_launcher.ROOT)}
    record={'identity':original,'argv':original['argv']}
    monkeypatch.setattr(app_launcher.os,'geteuid',lambda:1000)
    monkeypatch.setattr(app_launcher,'identity',lambda _: original)
    assert app_launcher.owned(record)
    monkeypatch.setattr(app_launcher,'identity',lambda _: original|{'start_ticks':'41'})
    assert not app_launcher.owned(record)
    monkeypatch.setattr(app_launcher,'identity',lambda _: original|{'argv':['python','unrelated']})
    assert not app_launcher.owned(record)


def test_forged_receipt_cannot_adopt_an_unrelated_process(monkeypatch):
    unrelated={'pid':12,'start_ticks':'40','uid':1000,'argv':['/bin/sleep','100'],
        'cwd':str(app_launcher.ROOT)}
    monkeypatch.setattr(app_launcher.os,'geteuid',lambda:1000)
    monkeypatch.setattr(app_launcher,'identity',lambda _:unrelated)
    assert not app_launcher.owned({'identity':unrelated,'argv':unrelated['argv']})
    assert not app_launcher.owned({'identity':unrelated,'argv':['python','-m','explainnet.cli']})


def test_occupied_unowned_port_starts_nothing_and_signals_nothing(tmp_path,monkeypatch):
    cfg=settings(tmp_path)
    Store(cfg.database_path).initialize()
    config=tmp_path/'config.json'; config.write_text(cfg.model_dump_json())
    monkeypatch.setattr('sys.argv',['manage_app','--config',str(config),'start'])
    monkeypatch.setattr(app_launcher,'occupied',lambda _:True)
    spawn=Mock(); kill=Mock()
    monkeypatch.setattr(app_launcher.subprocess,'Popen',spawn)
    monkeypatch.setattr(app_launcher.os,'kill',kill)
    with pytest.raises(ValueError,match='unowned service'):
        app_launcher.main()
    spawn.assert_not_called(); kill.assert_not_called()


def test_changed_config_refused_while_owned_services_run(tmp_path,monkeypatch):
    cfg=settings(tmp_path)
    Store(cfg.database_path).initialize()
    config=tmp_path/'config.json'; config.write_text(cfg.model_dump_json())
    receipt=tmp_path/'launcher.json'
    receipt.write_text(json.dumps({'components':{'backend':{'identity':{'pid':12}}},'config_hash':'different'}))
    monkeypatch.setattr('sys.argv',['manage_app','--config',str(config),'--record',str(receipt),'start'])
    monkeypatch.setattr(app_launcher,'owned',lambda record:bool(record))
    with pytest.raises(ValueError,match='Configuration changed'):
        app_launcher.main()


def test_apply_button_uses_backend_preview_rejection(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from explainnet.dashboard.client import ApiClient
    mapping=ui_fixture(True)
    mapping['/v1/dashboard/status']['control']['mode']='assisted-repair'
    mapping['/v1/dashboard/applicable/workflow']={'available':False,'reason':'diagnosis/explanation uncertainty prevents application'}
    def get(_self,path,model=None):
        result=deepcopy(mapping.get(path,{'records':[]}))
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient,'get',get)
    app=AppTest.from_string('from explainnet.dashboard.views import recovery\nfrom explainnet.dashboard.client import ApiClient\nc=ApiClient()\nrecovery(c,c.get("/v1/dashboard/status"))')
    app.run(timeout=60)
    assert not app.exception
    assert next(b for b in app.button if b.label=='Apply eligible repair').disabled
    assert any('uncertainty prevents' in c.value for c in app.caption)


def test_workflow_read_refreshes_shap_with_lineage_without_rewriting_history(tmp_path):
    c=coordinator(tmp_path)
    w={'workflow_id':'w','request_key':'k','instance_id':'original','created_utc':datetime.now(UTC).isoformat(),
        'state':'refused','diagnosis':{'model_id':'m'},
        'explanation':{'status':'pending','explanation_id':'x','model_id':'m','window_id':'o'}}
    c._save(w)
    c.worker.explanations.get=lambda _: {'status':'ready','model_id':'m','window_id':'o'}
    assert c.get('w')['explanation']['status']=='ready'
    with c.store.connection() as db:
        saved=json.loads(db.execute('SELECT payload_json FROM recovery_workflows').fetchone()[0])
    assert saved['explanation']['status']=='pending'
    c.worker.explanations.get=lambda _: {'status':'ready','model_id':'different','window_id':'o'}
    assert c.get('w')['explanation']['status']=='unsupported'


def test_collection_progresses_while_actual_explanation_worker_is_blocked(tmp_path,monkeypatch):
    from test_explanations import RFExplainer, setup_service, unit_background
    from test_telemetry import snapshot

    from explainnet.telemetry_service import TelemetryService

    store,_diagnosis,explainer,w,bundle,X=setup_service(tmp_path)
    entered=threading.Event(); release=threading.Event(); sampled=threading.Event()
    count=0
    class Agent:
        def network_inspect(self,_): return {'state':'running','live_verified':True}
        def telemetry_observe(self,_):
            nonlocal count
            count+=1
            result=snapshot(count)
            result.update(monotonic_s=time.monotonic(),at_utc=datetime.now(UTC).isoformat(),capabilities={})
            if count>=3: sampled.set()
            return result
    collector=TelemetryService(store,Agent())
    runtime=RFExplainer(bundle,unit_background(bundle,X))
    monkeypatch.setattr(explainer,'_runtime',lambda _:runtime)
    original=explainer.process
    def block(payload):
        entered.set()
        assert release.wait(8),'Bounded fixture release timeout'
        return original(payload)
    monkeypatch.setattr(explainer,'process',block)
    explainer.request('munit',w['window_id'])
    try:
        explainer.start(); assert entered.wait(4)
        collector.start('lab1',25)
        assert sampled.wait(5) and not release.is_set()
        assert collector.status('lab1')['session']['sample_count']>=2
        assert explainer.thread.is_alive()
    finally:
        release.set()
        explainer.close()
        collector.stop('lab1')
