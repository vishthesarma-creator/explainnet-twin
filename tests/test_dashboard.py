"""Stage 12 software fixtures. These are never live experimental evidence."""
import json
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from test_twin import snapshot, window

from explainnet.agent import AgentClient, AgentUnavailable
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.dashboard.client import ApiClient, ApiError, ClientSettings, JobAccepted
from explainnet.dashboard.presentation import (
    measurement_window,
    readiness,
    retry_intent,
    send_intent,
    telemetry_freshness,
)
from explainnet.dashboard.views import PAGES
from explainnet.dashboard_api import evidence_bytes, public_value
from explainnet.recovery_spec import generate
from explainnet.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def test_client_success_and_contract_validation():
    transport = httpx.MockTransport(lambda r: httpx.Response(202, json={'job_id': 'job', 'state': 'queued'}))
    client = ApiClient(transport=transport)
    assert client.submit('/v1/lab/mode', {'mode': 'observe'}, 'key')['job_id'] == 'job'
    for content in (b'not json', b'[]', b'{}'):
        client = ApiClient(transport=httpx.MockTransport(lambda r, body=content: httpx.Response(200, content=body)))
        with pytest.raises(ApiError, match='JSON|shape|contract'):
            client.get('/v1/test', JobAccepted)


@pytest.mark.parametrize('error,kind', [(httpx.ConnectError('offline'), 'unavailable'), (httpx.ReadTimeout('slow'), 'timeout')])
def test_client_failure_has_no_mutation_retry(error, kind):
    calls = []
    def fail(request):
        calls.append(request)
        raise error
    client = ApiClient(transport=httpx.MockTransport(fail))
    with pytest.raises(ApiError) as caught:
        client.submit('/v1/traffic/start', {}, 'key')
    assert caught.value.kind == kind and len(calls) == 1


def test_local_urls_error_mapping_and_redaction():
    for url in ('https://example.com', 'http://user:password@127.0.0.1:8765', 'http://127.0.0.1:8765/other'):
        with pytest.raises(ValueError):
            ClientSettings(api_url=url)
    client = ApiClient(transport=httpx.MockTransport(lambda r: httpx.Response(409, json={'error': {'message': 'stale snapshot'}})))
    with pytest.raises(ApiError, match='stale snapshot'):
        client.submit('/v1/lab/apply', {}, 'key')
    result = public_value({'secret': 'hidden', 'path': '/home/user/private.json', 'logical_diff': [{'from_path': 'primary', 'to_path': 'alternative'}]})
    assert 'hidden' not in str(result) and '/home/' not in str(result)
    assert result['logical_diff'][0]['from_path'] == 'primary'


def test_confirmation_latch_and_ambiguous_response():
    calls = []
    class Client:
        def submit(self, *args):
            calls.append(args)
            raise ApiError('timeout', 'timeout')
    state = {}
    with pytest.raises(ValueError, match='confirmation'):
        send_intent(Client(), state, 'apply', '/v1/lab/apply', {}, [False])
    assert not state and not calls
    first = send_intent(Client(), state, 'apply', '/v1/lab/apply', {}, [True])
    second = send_intent(Client(), state, 'apply', '/v1/lab/apply', {}, [True])
    assert first == second and first['state'] == 'unknown' and len(calls) == 1
    with pytest.raises(ValueError, match='already has a request'):
        send_intent(Client(), state, 'apply', '/v1/lab/apply', {'other': True}, [True])
    class ReadyClient:
        def submit(self, *args):
            calls.append(args)
            return {'job_id': 'same_job', 'state': 'queued'}
    original_key = first['key']
    retry_intent(ReadyClient(), first)
    assert first['state'] == 'acknowledged' and calls[-1][-1] == original_key
    assert len(calls) == 2


@pytest.mark.parametrize('response', [httpx.Response(503, json={'detail': 'storage failed'}), httpx.Response(200, json={})])
def test_ambiguous_server_or_protocol_failure_retains_intent(response):
    client = ApiClient(transport=httpx.MockTransport(lambda r: response))
    state = {}
    receipt = send_intent(client, state, 'apply', '/v1/lab/apply', {}, [True])
    assert receipt['state'] == 'unknown' and receipt['key'] == state['apply']['key']


def test_empty_readiness_and_stopped_collector_are_truthful():
    assert ('Dataset', 'Unknown') in readiness(None)
    w = window()
    w['at_utc'] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    assert telemetry_freshness({'live': False}, w) == 'Historical / stale'
    assert telemetry_freshness({'live': True}, w) == 'Fresh'
    assert telemetry_freshness({}, None) == 'No measurements'


def settings(tmp_path):
    return Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run', agent_socket=tmp_path / 'absent',
        topology_file=ROOT / 'config/topology.yaml', traffic_profiles_file=ROOT / 'config/traffic.yaml')


def test_active_window_selection_preserves_quality_failures_and_collection_boundaries():
    pending = window() | {'run_id': 'current', 'complete': False, 'inference_ready': False}
    failed = window() | {'run_id': 'current', 'complete': True, 'inference_ready': False}
    good = window() | {'run_id': 'current'}
    old = window() | {'run_id': 'previous'}
    assert measurement_window({'live': True}, [pending, failed, good]) is failed
    assert measurement_window({'live': True}, [pending, old]) is pending
    assert measurement_window({'live': True}, [pending, good]) is good
    assert measurement_window({'live': False}, [pending, good]) is pending
    assert measurement_window({'live': True}, []) is None


def test_backend_empty_status_safe_evidence_and_paths(tmp_path):
    cfg = settings(tmp_path)
    store = Store(cfg.database_path)
    store.initialize()
    with TestClient(create_app(cfg)) as client:
        status = client.get('/v1/dashboard/status').json()
        assert status['dataset']['ready'] is False and status['dataset']['counts_by_split'] == {}
        assert not status['agent']['available'] and status['agent']['instances'] == []
        assert status['models']['registered_count'] == 0 and status['explanations']['ready_count'] == 0
        assert not status['control']['auto_enabled'] and not status['control']['allow_observed_only']
        assert client.get('/v1/dashboard/records/workflows').json() == {'records': []}
        assert client.get('/v1/dashboard/reversible/original').json()['available'] is False
        assert client.get('/v1/dashboard/records/arbitrary_table').status_code == 422
        assert client.get('/v1/dashboard/evidence/secrets').status_code == 422
        assert client.get('/v1/dashboard/evidence/../../config/example.yaml').status_code != 200
        downloaded = client.get('/v1/dashboard/evidence/recovery')
        assert downloaded.status_code == 200 and 'attachment' in downloaded.headers['content-disposition']
        assert '/mnt/c/' not in downloaded.text and 'native_intervals' not in downloaded.text
        for artifact in client.get('/v1/dashboard/evidence').json()['records']:
            if artifact['available']:
                assert client.get('/v1/dashboard/evidence/'+artifact['artifact_id']).status_code == 200
        assert client.get('/v1/dashboard/status').json()['control'] == status['control']


def test_durable_job_idempotency_and_conflicting_key(tmp_path):
    cfg = settings(tmp_path)
    Store(cfg.database_path).initialize()
    app = create_app(cfg)
    with TestClient(app) as client:
        h = {'Idempotency-Key': 'same_intent'}
        a = client.post('/v1/lab/mode', json={'mode': 'observe'}, headers=h)
        b = client.post('/v1/lab/mode', json={'mode': 'observe'}, headers=h)
        assert a.status_code == b.status_code == 202 and a.json()['job_id'] == b.json()['job_id']
        assert client.post('/v1/lab/mode', json={'mode': 'recommend'}, headers=h).status_code == 409
        assert client.get('/v1/dashboard/submissions/same_intent').json()['job_id'] == a.json()['job_id']
    # Durable across a fresh API/Store instance; startup doesn't replay it.
    with TestClient(create_app(cfg)) as client:
        c = client.post('/v1/lab/mode', json={'mode': 'observe'}, headers=h)
        assert c.json()['job_id'] == a.json()['job_id']


def test_traffic_double_click_executes_one_job(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    Store(cfg.database_path).initialize()
    calls = []
    def launch(self, request):
        calls.append(request.instance_id)
        return {'run_id': 'trafficFixture', 'config_hash': 'fixture'}
    monkeypatch.setattr(AgentClient, 'traffic_start', launch)
    with TestClient(create_app(cfg)) as client:
        body = {'instance_id': 'original', 'profile_ids': ['critical'], 'duration_s': 4}
        headers = {'Idempotency-Key': 'one_traffic_intent'}
        one = client.post('/v1/traffic/start', json=body, headers=headers).json()
        two = client.post('/v1/traffic/start', json=body, headers=headers).json()
        assert one['job_id'] == two['job_id']
        end = time.monotonic() + 3
        while time.monotonic() < end:
            job = client.get('/v1/jobs/' + one['job_id']).json()
            if job['state'] in {'succeeded', 'failed'}:
                break
            time.sleep(.01)
        assert job['state'] == 'succeeded' and calls == ['original']


def test_undo_requires_actual_current_readback(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    store = Store(cfg.database_path)
    store.initialize()
    when = datetime.now(UTC).isoformat()
    with store.connection() as db:
        db.execute("INSERT INTO runs VALUES('r',?,'fixture','{}')", (when,))
        db.execute("INSERT INTO incidents VALUES('i','r',?,'{}')", (when,))
        db.execute("INSERT INTO actions VALUES('a','i',NULL,?,'{}')", (when,))
        db.execute("INSERT INTO lab_action_state VALUES('a','k','original','succeeded',?,'{}')", (when,))
    native = {'state': 'kept', 'current': {'version': 2}, 'after': {'version': 2}}
    monkeypatch.setattr(AgentClient, 'lab_status', lambda *args: native)
    with TestClient(create_app(cfg)) as client:
        assert client.get('/v1/dashboard/reversible/original').json()['available']
        native['current']['version'] = 3
        assert not client.get('/v1/dashboard/reversible/original').json()['available']
        def unavailable(*args):
            raise AgentUnavailable('owner lost')
        monkeypatch.setattr(AgentClient, 'lab_status', unavailable)
        assert not client.get('/v1/dashboard/reversible/original').json()['available']


def test_sealed_windows_never_returned(tmp_path):
    cfg = settings(tmp_path)
    store = Store(cfg.database_path)
    store.initialize()
    with store.connection() as db:
        db.execute("INSERT INTO runs VALUES('run',?, 'fixture','{}')", (datetime.now(UTC).isoformat(),))
        db.execute("INSERT INTO dataset_batches VALUES('batch','planned','hash',1,'{}')")
        db.execute("INSERT INTO dataset_attempts VALUES('attempt','batch','episode','planned','{}')")
        for name, partition in [('visible', 'train'), ('sealed', 'test')]:
            payload = window() | {'window_id': name, 'instance_id': 'original'}
            db.execute('INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?)', (name, 'run', 'original', 10, 1, 1, json.dumps(payload)))
            db.execute('INSERT INTO dataset_members VALUES(?,?,?,?,?,?,?)', (name, 'batch', 'episode', 'family', partition, 'attempt', 'hash'))
    # Mount without starting services: the fixture batch is intentionally minimal.
    client = TestClient(create_app(cfg))
    response = client.get('/v1/dashboard/telemetry/original').json()
    assert [w['window_id'] for w in response['windows']] == ['visible']
    assert client.get('/v1/dashboard/windows/sealed').status_code == 404


def test_evidence_rejects_symlink(tmp_path):
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    real = tmp_path / 'private.json'
    real.write_text('{"status":"not public"}')
    (artifacts / 'recovery_validation_report.json').symlink_to(real)
    with pytest.raises(ValueError, match='symlink'):
        evidence_bytes('recovery', 1, tmp_path)


def ui_fixture(populated):
    source = snapshot()
    current = window() | {'instance_id': 'original', 'context': {'selected_paths': source['selected_paths']}}
    control = {'mode': 'recommend', 'auto_enabled': False, 'allow_observed_only': False}
    status = {'schema_version': 1, 'at_utc': datetime.now(UTC).isoformat(), 'api_version': '0.12.0', 'database': 'available',
        'agent': {'available': populated, 'instances': [{'instance_id': 'original', 'role': 'original', 'state': 'running', 'live_verified': True}] if populated else []},
        'dataset': {'ready': False, 'counts_by_split': {'train': 2} if populated else {}, 'batches': []},
        'models': {'registered_count': 0, 'active_model_id': None}, 'explanations': {'ready_count': 0, 'worker_live': True},
        'twin': {'snapshot_count': 1 if populated else 0, 'live_ready': None}, 'control': control, 'traffic_profiles': ['critical', 'bulk']}
    generated = generate(source, max_repairs=1)
    experiment = {'operation_id': 'experiment', 'snapshot_id': source['snapshot_id'], 'twin_id': 'twin', 'state': 'eligible',
        'candidates': generated['candidates'], 'trials': [{'trial_id': 'trial', 'candidate_id': generated['candidates'][0]['candidate_id'],
            'state': 'measured', 'window': current, 'hypothesis_id': 'hypothesis', 'fidelity': {'passed': True}}],
        'recommendation': {'status': 'eligible', 'logical_diff': [], 'selected_candidate_id': generated['candidates'][-1]['candidate_id'], 'rows': []}}
    workflow = {'workflow_id': 'workflow', 'instance_id': 'original', 'state': 'recommended', 'experiment_id': 'experiment',
        'diagnosis': {'status': 'observed-only'}}
    incident = {'incident_id': 'incident', 'instance_id': 'original', 'state': 'open', 'severity': 'service_violation',
        'service_status': 'degraded', 'last_window_id': current['window_id'], 'path': {'flow': 'critical'}, 'observed_update_utc': current['at_utc']}
    mapping = {'/v1/dashboard/status': status, '/v1/lab/control': control,
        '/v1/networks/original': {'definition': source['definition'], 'selected_paths': source['selected_paths'], 'live_verified': True},
        '/v1/dashboard/telemetry/original': {'collector': {'live': True}, 'windows': [current]},
        '/v1/dashboard/windows/' + current['window_id']: {'window': current, 'rule_findings': {'status': 'alert'}},
        '/v1/dashboard/reversible/original': {'available': False, 'reason': 'No applicable action'},
        '/v1/recovery/experiment': experiment, '/v1/twins/snapshots/' + source['snapshot_id']: source,
        '/v1/lab/workflows/workflow': workflow, '/v1/incidents/incident': incident,
        '/v1/dashboard/records/incidents': {'records': [incident] if populated else []},
        '/v1/dashboard/records/experiments': {'records': [experiment] if populated else []},
        '/v1/dashboard/records/workflows': {'records': [workflow] if populated else []},
        '/v1/dashboard/evidence': {'records': []}}
    return mapping


@pytest.mark.parametrize('populated', [False, True])
@pytest.mark.parametrize('page', range(6))
def test_all_pages_render_with_explicit_software_fixtures(monkeypatch, populated, page):
    mapping = ui_fixture(populated)
    mutations = []
    def fake(self, path, method='GET', body=None, key=None, model=None):
        assert method == 'GET', 'Rendering/navigation must not mutate'
        result = deepcopy(mapping.get(path.split('?')[0], {'records': []}))
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient, 'request', fake)
    code = f"import streamlit as st\nst.set_page_config(layout='wide')\nfrom explainnet.dashboard.views import render\nfrom explainnet.dashboard.client import ApiClient\nrender({page},ApiClient())"
    app = AppTest.from_string(code).run(timeout=60)
    assert not app.exception, [x.message for x in app.exception]
    expected = 'ExplainNet Twin' if page == 0 else PAGES[page]
    assert app.title[0].value == expected
    assert not mutations


@pytest.mark.parametrize('state', ['fresh', 'stopped', 'stale', 'incomplete', 'missing', 'unavailable'])
def test_overview_checklist_requires_usable_live_measurements(monkeypatch, state):
    mapping = ui_fixture(True)
    telemetry = mapping['/v1/dashboard/telemetry/original']
    current = telemetry['windows'][0]
    current.update(at_utc=datetime.now(UTC).isoformat(), complete=True, inference_ready=True)
    if state == 'stopped':
        telemetry['collector']['live'] = False
    elif state == 'stale':
        current['at_utc'] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    elif state == 'incomplete':
        current['complete'] = False
    elif state == 'missing':
        telemetry['windows'] = []

    def fake(self, path, method='GET', body=None, key=None, model=None):
        assert method == 'GET'
        if state == 'unavailable' and path.startswith('/v1/dashboard/telemetry/'):
            raise ApiError('Collector unavailable', 'unavailable')
        result = deepcopy(mapping.get(path.split('?')[0], {'records': []}))
        return model.model_validate(result).model_dump() if model else result

    monkeypatch.setattr(ApiClient, 'request', fake)
    app = AppTest.from_string('from explainnet.dashboard.views import render\n'
        'from explainnet.dashboard.client import ApiClient\nrender(0, ApiClient())').run(timeout=60)
    assert not app.exception
    checklist = [m.value for m in app.markdown if ' Verified original network and fresh telemetry' in m.value]
    assert checklist == [('✓' if state == 'fresh' else '○') + ' Verified original network and fresh telemetry']


def test_main_navigation_and_unavailable_backend(monkeypatch):
    def offline(*args, **kwargs):
        raise ApiError('Backend unavailable', 'unavailable')
    monkeypatch.setattr(ApiClient, 'request', offline)
    app = AppTest.from_file(ROOT / 'src/explainnet/dashboard/app.py').run(timeout=60)
    assert not app.exception and app.title[0].value == 'Live Network'
    assert app.warning
    for name, title in [('network','Live Network'),('incidents','Diagnosis'),('twin','Twin & Recovery'),('recovery','Twin & Recovery'),('evidence','Results')]:
        app.switch_page('page_routes/' + name + '.py').run(timeout=60)
        assert not app.exception and app.title[0].value == title


def test_mode_confirmation_and_repeat_click(monkeypatch):
    mapping = ui_fixture(False)
    calls = []
    def fake(self, path, method='GET', body=None, key=None, model=None):
        if method == 'POST':
            calls.append((path, body, key))
            return {'job_id': 'accepted', 'state': 'queued'}
        result = deepcopy(mapping.get(path.split('?')[0], {'records': []}))
        if path == '/v1/jobs/accepted':
            result = {'state': 'succeeded'}
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient, 'request', fake)
    code = "from explainnet.dashboard.views import render\nfrom explainnet.dashboard.client import ApiClient\nrender(4,ApiClient())"
    app = AppTest.from_string(code).run(timeout=60)
    app.selectbox[0].set_value('lab-auto-repair').run()
    next(b for b in app.button if b.label == 'Apply mode selection').click().run()
    assert not calls and app.error
    app.checkbox[1].check()
    next(b for b in app.button if b.label == 'Apply mode selection').click().run()
    assert len(calls) == 1 and calls[0][1]['mode'] == 'lab-auto-repair'
    app.run()
    assert len(calls) == 1 and next(b for b in app.button if b.label == 'Apply mode selection').disabled
    next(b for b in app.button if b.label == 'Prepare another request').click().run()
    assert not app.exception and not app.checkbox(key='confirm_auto').value
    next(b for b in app.button if b.label == 'Apply mode selection').click().run()
    assert len(calls) == 1, 'A new automatic-mode intent needs a fresh confirmation'


@pytest.mark.parametrize('calibrated', [True, False])
def test_recorded_prediction_and_shap_match_actual_model_window(monkeypatch, calibrated):
    mapping = ui_fixture(True)
    mapping['/v1/dashboard/status']['models'] = {'active_model_id': 'modelFixture', 'registered_count': 1}
    mapping['/v1/dashboard/status']['explanations']['ready_count'] = 1
    wid = mapping['/v1/incidents/incident']['last_window_id']
    mapping['/v1/diagnoses/' + wid] = {'records': [{'model_id': 'modelFixture', 'predicted_class': 'latency',
        'probability_status': 'calibrated' if calibrated else 'raw_uncalibrated', 'confidence': .76}]}
    good = {'status': 'ready', 'model_id': 'modelFixture', 'window_id': wid,
        'contributions': [{'transformed_feature': 'rtt_mean_ms', 'contribution': .2}]}
    mapping['/v1/explanations/window/' + wid] = {'records': [good, good | {'model_id': 'wrongModel', 'contributions': []}]}
    def fake(self, path, method='GET', body=None, key=None, model=None):
        assert method == 'GET'
        result = deepcopy(mapping.get(path, {'records': []}))
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient, 'request', fake)
    code = "from explainnet.dashboard.views import render\nfrom explainnet.dashboard.client import ApiClient\nrender(2,ApiClient())"
    app = AppTest.from_string(code).run(timeout=60)
    assert not app.exception
    assert any(h.value == 'Recorded SHAP explanation' for h in app.subheader)
    assert 'wrongModel' not in str([element.value for element in app.json])
    confidence_metrics = [m for m in app.metric if m.label == 'Calibrated confidence']
    assert bool(confidence_metrics) == calibrated
