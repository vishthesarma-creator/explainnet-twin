"""Completion stage 1 software fixtures; these are not native packet evidence."""
import base64
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from test_dashboard import settings, ui_fixture
from test_workflow import coordinator

from explainnet.agent import RPC_CONTEXT, AgentClient, AgentUnavailable
from explainnet.agent_server import Handler, Server, dispatch_v2
from explainnet.api import create_app
from explainnet.app_launcher import configuration, validate_binding
from explainnet.application_profiles import PROFILES, identity
from explainnet.config import load_settings
from explainnet.dashboard.client import ApiClient
from explainnet.dashboard.presentation import measurement_window, telemetry_freshness
from explainnet.jobs import Worker
from explainnet.network_contracts import InstanceRequest
from explainnet.network_runtime import NetworkManager
from explainnet.response_evidence import FRAME_LIMIT, EvidenceFiles, encoded
from explainnet.storage import Store
from explainnet.telemetry_service import TelemetryService
from explainnet.workflow_contracts import ApplyRequest, WorkflowRequest

ROOT = Path(__file__).resolve().parents[1]


def workflow_request(name='w'):
    return WorkflowRequest(workflow_id=name, request_key=name + 'key', instance_id='original',
        baseline={'window_ids': ['one', 'two'], 'definition_hash': 'a' * 64},
        policy={'version': 'fixture'}, max_repairs=1)


@pytest.mark.parametrize('state', ['refused', 'failed', 'recommended', 'succeeded', 'rolled_back', 'interrupted'])
def test_execution_releases_after_finalization_only(tmp_path, state):
    c = coordinator(tmp_path)
    c._save = lambda w: None
    c.get = lambda _: {'instance_id': 'original'}
    entered, release = threading.Event(), threading.Event()
    def run(w):
        w['state'] = state
        entered.set()
        assert release.wait(3)
        assert c.busy(), 'terminal result must not release unfinished cleanup'
    w = {'workflow_id': 'w'}
    c.active = c.latest = 'w'
    c.thread = threading.Thread(target=c._execute, args=(w, run))
    c.thread.start()
    assert entered.wait(2) and c.busy('original')
    release.set()
    c.thread.join(3)
    assert c.active is None and c.latest == 'w' and not c.busy()


def test_old_finalizer_cannot_release_new_worker(tmp_path):
    c = coordinator(tmp_path)
    c.active = 'new'
    c.thread = threading.current_thread()
    c._execute({'workflow_id': 'old'}, lambda _: None)
    assert c.active == 'new'


def test_cleanup_failure_keeps_mutation_ownership_blocked(tmp_path):
    c = coordinator(tmp_path)
    c._save = lambda _: None
    c.active = 'w'
    c.thread = threading.current_thread()
    w = {'workflow_id': 'w', 'candidate_result': {'cleanup_error': 'owned twin still present'}}
    c._execute(w, lambda _: None)
    assert c.active is None and c.busy()
    assert c.lifecycle()['cleanup_pending_workflow_ids'] == ['w']


def test_launch_duplicate_and_id_conflict(tmp_path):
    c = coordinator(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def run(_):
        entered.set()
        release.wait(3)
    c._run = run
    req = workflow_request()
    c.launch(req)
    assert entered.wait(2)
    assert c.launch(req)['idempotent']
    with pytest.raises(ValueError, match='reused'):
        c.launch(req.model_copy(update={'request_key': 'otherkey'}))
    release.set()
    c.thread.join(3)
    assert c.active is None


def test_restart_retains_interrupted_action_without_replay(tmp_path):
    c = coordinator(tmp_path)
    w = workflow_request().model_dump() | {'state': 'verifying', 'created_utc': datetime.now(UTC).isoformat()}
    c._save(w)
    a = {'action_id': 'a', 'request_key': 'akey', 'instance_id': 'original', 'workflow_id': 'w',
        'created_utc': w['created_utc'], 'state': 'verifying'}
    with c.store.connection() as db:
        db.execute("INSERT INTO runs VALUES('r',?,'fixture','{}')", (w['created_utc'],))
        db.execute("INSERT INTO incidents VALUES('i','r',?,'{}')", (w['created_utc'],))
        db.execute("INSERT INTO actions VALUES('a','i',NULL,?,'{}')", (w['created_utc'],))
    c._save_action(a)
    calls = []
    c.agent.lab_status = lambda _: calls.append('read') or {'state': 'applied'}
    c.agent.lab_rollback = lambda _: calls.append('rollback') or {'state': 'rolled_back'}
    c.reconcile()
    assert calls == ['read'] and c.busy() and c.active is None
    assert c.action('a')['state'] == 'interrupted' and c.lifecycle()['unsettled_action_ids'] == ['a']
    assert not c.control()['auto_enabled'] and not c.control()['allow_observed_only']
    c.reconcile_action('a')
    assert calls == ['read', 'rollback'] and not c.busy()


def test_application_duplicate_and_stop_remain_responsive(tmp_path):
    c = coordinator(tmp_path)
    entered, release = threading.Event(), threading.Event()
    c.get = lambda _: {'workflow_id': 'w', 'instance_id': 'original', 'state': 'verifying'}
    calls = []
    def apply(w, request):
        calls.append(request.action_id)
        entered.set()
        release.wait(3)
    c._apply = apply
    request = ApplyRequest(workflow_id='w', action_id='a', request_key='key')
    c.apply(request)
    assert entered.wait(2)
    assert c.apply(request)['idempotent']
    assert c.stop()['new_actuation_prevented'] and c.busy()
    c.cancel('w')
    assert c.events['w'].is_set() and c.busy()
    release.set()
    c.thread.join(3)
    assert calls == ['a'] and not c.busy()


@contextmanager
def v2_agent(tmp_path, monkeypatch, value):
    from explainnet import agent_server
    original = agent_server.dispatch
    calls = []
    def fake(request, manager):
        if request['operation'] == 'evidence_read':
            return original(request, manager)
        calls.append(request['operation'])
        return deepcopy(value)
    monkeypatch.setattr(agent_server, 'dispatch', fake)
    server = Server(str(tmp_path / 'v2.sock'), Handler)
    server.allowed_uids = {os.geteuid()}
    server.network_manager = SimpleNamespace(state_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    try:
        yield AgentClient(tmp_path / 'v2.sock', timeout_s=5, protocol_version=2), calls, server.network_manager
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_large_scenario_ack_complete_evidence_and_duplicate_rpc(tmp_path, monkeypatch):
    value = {'instance_id': 'original', 'laboratory_journal': {'state': 'stopped'},
        'traffic_runs': [{'run_id': 'run', 'native': 'x' * 2_648_473}]}
    with v2_agent(tmp_path, monkeypatch, value) as (client, calls, _):
        context = RPC_CONTEXT.set('one-job')
        try:
            parameters = InstanceRequest(instance_id='original').model_dump()
            ack = client.call('scenario_reset', parameters, hydrate=False)
            assert len(encoded(ack)) < FRAME_LIMIT and ack['outcome'] == 'completed'
            assert client.read_evidence(ack['evidence']) == value
            assert client.call('scenario_reset', parameters) == value
            assert calls == ['scenario_reset'], 'duplicate RPC physically replayed'
        finally:
            RPC_CONTEXT.reset(context)
    preserved = EvidenceFiles(tmp_path / 'response_evidence').page(ack['evidence']['sha256'])
    assert preserved['total_bytes'] > 2 * 1024 * 1024


def test_unknown_rpc_cannot_be_repeated(tmp_path, monkeypatch):
    from explainnet import agent_server
    calls = []
    def mutate_then_fail(*_):
        calls.append('physical_success')
        raise OSError('ack lost after physical mutation')
    monkeypatch.setattr(agent_server, 'dispatch', mutate_then_fail)
    request = {'protocol_version': 2, 'request_id': 'f' * 32, 'operation': 'scenario_reset',
        'parameters': InstanceRequest(instance_id='original').model_dump()}
    manager = SimpleNamespace(state_dir=tmp_path)
    with pytest.raises(OSError):
        dispatch_v2(request, manager)
    with pytest.raises(RuntimeError, match='outcome unknown'):
        dispatch_v2(request, manager)
    assert calls == ['physical_success']


def test_read_evidence_does_not_write_journals(tmp_path, monkeypatch):
    value = {'instance_id': 'original', 'state': 'running', 'native': 'x' * 2_648_473}
    with v2_agent(tmp_path, monkeypatch, value) as (client, _, _):
        assert client.network_inspect(InstanceRequest(instance_id='original')) == value
        assert sorted(p.name for p in tmp_path.iterdir()) == ['v2.sock']


def test_corrupted_page_digest_refused(tmp_path):
    client = AgentClient(tmp_path / 'unused', protocol_version=2)
    client.call = lambda *a, **k: {'sha256': 'f' * 64, 'offset': 0, 'total_bytes': 2,
        'next_offset': 2, 'complete': True, 'base64': base64.b64encode(b'{}').decode()}
    with pytest.raises(AgentUnavailable, match='integrity'):
        client.read_evidence({'sha256': 'f' * 64, 'bytes': 2})


def test_gets_do_not_update_database_and_jobs_are_paged(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    store = Store(cfg.database_path)
    store.initialize()
    network = {'instance_id': 'original', 'state': 'running', 'live_verified': True}
    traffic = {'instance_id': 'original', 'run_id': 'run', 'state': 'succeeded', 'native': 'x' * 2_700_000}
    monkeypatch.setattr(AgentClient, 'network_inspect', lambda *a: network)
    monkeypatch.setattr(AgentClient, 'traffic_status', lambda *a: traffic)
    monkeypatch.setattr(AgentClient, 'scenario_inspect', lambda *a: {'laboratory_journal': None, 'traffic_runs': [traffic]})
    job = store.create_job('job', 'traffic_stop', 'request', {})
    store.next_queued()
    store.finish_job(job, 'succeeded', 1, result=traffic)
    app = create_app(cfg)
    client = TestClient(app)  # No startup reconciliation/background fixture workers.
    def dump():
        with store.connection() as db:
            return list(db.iterdump())
    before = dump()
    for _ in range(2):
        for path in ['/v1/networks/original', '/v1/traffic/original/run', '/v1/laboratory/scenarios/original',
                '/v1/lab/control', '/v1/jobs/job', '/v1/dashboard/telemetry/original']:
            response = client.get(path)
            assert response.status_code == 200 and len(response.content) < FRAME_LIMIT
    offset, raw = 0, bytearray()
    while True:
        p = client.get('/v1/jobs/job/evidence', params={'offset': offset}).json()
        raw.extend(base64.b64decode(p['base64']))
        offset = p['next_offset']
        if p['complete']:
            break
    assert hashlib.sha256(raw).hexdigest() == p['sha256']
    assert json.loads(raw)['result'] == traffic and dump() == before


def test_ack_failure_readback_reconciles_physical_success(tmp_path):
    store = Store(tmp_path / 'db')
    store.initialize()
    class Agent:
        def network_stop(self, _):
            raise AgentUnavailable('lost acknowledgement')
        def network_inspect(self, _):
            return {'instance_id': 'original', 'state': 'stopped', 'live_verified': True}
    worker = Worker(store, Agent())
    with pytest.raises(AgentUnavailable):
        worker._operation('network_stop', InstanceRequest(instance_id='original').model_dump())
    assert store.list_instances()[0]['state'] == 'stopped'


def test_old_run_never_looks_fresh_after_restart():
    collector = {'live': True, 'session': {'run_id': 'new'}}
    old = {'run_id': 'old', 'at_utc': datetime.now(UTC).isoformat(), 'complete': True, 'inference_ready': True}
    assert measurement_window(collector, [old]) is None
    assert telemetry_freshness(collector, old) == 'Historical / stale'
    new = old | {'run_id': 'new', 'complete': False}
    assert measurement_window(collector, [new, old]) == new


def test_expired_collector_is_not_live_during_finalization(tmp_path):
    store = Store(tmp_path / 'db')
    store.initialize()
    telemetry = TelemetryService(store, SimpleNamespace())
    telemetry.collectors['original'] = {'session': {'run_id': 'new', 'state': 'running',
        'started_utc': datetime.now(UTC).isoformat(), 'started_monotonic_s': time.monotonic() - 10,
        'duration_s': 1, 'last_observation_utc': datetime.now(UTC).isoformat()},
        'thread': SimpleNamespace(is_alive=lambda: True)}
    actual = telemetry.status('original')
    assert actual['expired'] and not actual['live'] and actual['remaining_s'] == 0


def test_runtime_refuses_lost_ownership_without_mutating_journal():
    manager = NetworkManager.__new__(NetworkManager)
    manager.instances = {'original': {'owned': 'fixture'}}
    manager.records = {'original': {'state': 'running', 'bridges': ['bridge']}}
    manager._owned_bridge = lambda *args: False
    before = deepcopy(manager.records)
    with pytest.raises(ValueError, match='ownership'):
        manager._running('original')
    assert manager.records == before


def test_restart_cancels_queued_external_mutation(tmp_path):
    store = Store(tmp_path / 'db')
    store.initialize()
    store.create_job('orphan', 'network_stop', 'old', {'instance_id': 'original'})
    calls = []
    worker = Worker(store, SimpleNamespace(inventory=lambda: {'instances': []}), poll_s=.01)
    worker.handlers['network_stop'] = lambda _: calls.append('unsafe replay')
    worker.start()
    try:
        assert store.get_job('orphan')['state'] == 'canceled' and calls == []
    finally:
        worker.stop()


def test_profiles_and_launcher_refuse_redirection():
    for profile, (config, port) in PROFILES.items():
        cfg = load_settings(config)
        assert identity(cfg)['profile'] == profile
        assert configuration(SimpleNamespace(config=config, dashboard_port=port, api_url=None))[1].endswith(str(cfg.port))
        with pytest.raises(ValueError, match='redirection'):
            configuration(SimpleNamespace(config=config, dashboard_port=port, api_url='http://127.0.0.1:1234'))


def test_running_api_identity_is_checked(monkeypatch):
    cfg = load_settings(PROFILES['trained'][0])
    url = f'http://127.0.0.1:{cfg.port}'
    actual = {'config_hash': cfg.config_hash, 'identity': {'database_path': str(cfg.database_path), 'api_url': url}}
    monkeypatch.setattr('explainnet.app_launcher.request', lambda _: actual)
    assert validate_binding(cfg, url) == actual['identity']
    actual['identity']['database_path'] = '/wrong/store'
    with pytest.raises(ValueError, match='store/URL'):
        validate_binding(cfg, url)


def test_shared_bootstrap_and_refresh_fixture(monkeypatch):
    mapping = ui_fixture(True)
    mapping['/v1/config'] = {'identity': {'profile': 'fixture'}}
    requests = []
    def fake(self, path, method='GET', body=None, key=None, model=None):
        requests.append(method)
        assert method == 'GET'
        result = deepcopy(mapping.get(path.split('?')[0], {'records': []}))
        return model.model_validate(result).model_dump() if model else result
    monkeypatch.setattr(ApiClient, 'request', fake)
    monkeypatch.delenv('EXPLAINNET_CONFIG_HASH', raising=False)
    app = AppTest.from_file(str(ROOT / 'src/explainnet/dashboard/app.py')).run(timeout=60)
    assert not app.exception, [x.message for x in app.exception]
    assert any(b.label == 'Refresh now' for b in app.button)
    assert len(app.toggle) == 1
    next(b for b in app.button if b.label=='Refresh now').click().run(timeout=60)
    assert not app.exception and set(requests) == {'GET'}
    assert not (ROOT / 'src/explainnet/dashboard/pages').exists()
