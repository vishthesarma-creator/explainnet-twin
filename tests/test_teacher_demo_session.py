"""Operational safety checks, never evidence of network repair qualification."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('teacher_session',
    Path(__file__).resolve().parents[1] / 'scripts/teacher_demo_session.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('control,actions', [
    ({'active_workflow_id': 'w'}, []),
    ({'monitor_active': True}, []),
    ({}, [{'state': 'succeeded'}]),
    ({}, [{'state': 'verifying'}]),
    ({}, [{'state': 'failed', 'degraded': True}]),
])
def test_cleanup_refuses_unsettled_or_kept_changes(control, actions):
    with pytest.raises(ValueError):
        module.teardown_allowed(control, actions)


def test_cleanup_allows_completed_undo():
    module.teardown_allowed({}, [{'state': 'rolled_back'}])


@pytest.mark.parametrize('opt_in,model', [(False, None), (True, 'activeModel')])
def test_observed_only_never_silently_replaces_a_trained_model(opt_in, model):
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture'}
    session.http = lambda route: {'active_model_id': model} if route == '/v1/models' else {'auto_enabled': False}
    session.job = lambda *args: pytest.fail('No mutation is allowed before explicit consent/model checks')
    with pytest.raises(ValueError, match='opt-in'):
        session.recommend(opt_in)


def test_fault_uses_separate_validated_setup_and_never_cleans_or_applies():
    from explainnet.scenario_contracts import ScenarioStartRequest
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture', 'policy': {'policy_hash': 'frozen'},
        'healthy_traffic': {'run_id': 'trafficFixture'}}
    session.http = lambda route: {'auto_enabled': False}
    session.save = lambda: None
    calls = []
    def job(route, body):
        calls.append((route, body))
        if route.endswith('scenarios/start'):
            ScenarioStartRequest.model_validate(body)
        return {'session': {'started_utc': '2026-10-21T00:00:00+00:00'}}
    session.job = job
    session.fault()
    assert [route for route, _ in calls] == ['/v1/telemetry/stop', '/v1/traffic/stop',
        '/v1/laboratory/scenarios/start', '/v1/telemetry/start']
    assert session.data['ground_truth']['recipe']['measurement_s'] == 900


def test_recommendation_payload_excludes_injector_and_never_applies(tmp_path):
    from explainnet.workflow_contracts import WorkflowRequest
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture', 'ground_truth': {'secret': 'label'},
        'policy': {'policy_hash': 'frozen'}, 'baseline': {'window_ids': ['w1', 'w2']},
        'receipt': str(tmp_path / 'session.json')}
    session.save = lambda: None
    def http(route):
        if route == '/v1/models':
            return {'active_model_id': None}
        if route.startswith('/v1/lab/workflows/'):
            return {'state': 'refused', 'reasons': ['real gate refused']}
        return {'auto_enabled': False}
    session.http = http
    calls = []
    def job(route, body):
        calls.append((route, body))
        if route == '/v1/lab/workflow':
            WorkflowRequest.model_validate(body)
            assert 'ground_truth' not in body and 'secret' not in str(body)
    session.job = job
    session.recommend(True)
    assert [route for route, _ in calls] == ['/v1/lab/mode', '/v1/lab/workflow']
    assert session.data['workflow']['state'] == 'refused'


def test_status_never_substitutes_a_previous_collectors_window():
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    session.binding = {}
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture'}
    session.save = lambda: None
    def http(route):
        if route.startswith('/v1/dashboard/telemetry/'):
            return {'collector': {'live': True, 'session': {'run_id': 'newCollector'}},
                'windows': [{'run_id': 'oldCollector', 'complete': True}]}
        if route.startswith('/v1/networks/'):
            return {'state': 'running'}
        return {'auto_enabled': False}
    session.http = http
    session.status()
    assert session.data['last_status']['window'] is None
    assert not session.data['last_status']['same_store_window_verified']


@pytest.mark.parametrize('state', ['succeeded', 'canceled', 'failed', 'interrupted', 'running'])
def test_renew_reconciles_actual_traffic_before_retrying_stop(state, tmp_path):
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    from explainnet.storage import Store
    session.store = Store(tmp_path / 'renew.sqlite3')
    session.store.initialize()
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture',
        'healthy_traffic': {'run_id': 'oldRun', 'state': 'running'}}
    session.save = lambda: None
    calls = []
    def http(route):
        if route.startswith('/v1/traffic/'):
            calls.append('read_actual_state')
            return {'run_id': 'oldRun', 'instance_id': 'teachlive_fixture', 'state': state}
        return {'auto_enabled': False}
    session.http = http
    def job(route, body):
        calls.append(route)
        if route == '/v1/traffic/start':
            return {'run_id': 'newRun', 'created_utc': '2026-10-22T00:00:00+00:00'}
        return {'session': {'started_utc': '2026-10-22T00:00:00+00:00'}}
    session.job = job
    session.healthy_traffic()
    assert ('/v1/traffic/stop' in calls) == (state == 'running')
    assert calls.index('read_actual_state') < calls.index('/v1/traffic/start')
    assert session.data['renewal_reconciliations'][0]['actual_state'] == state


def test_renew_refuses_untracked_run_after_lost_ack(tmp_path):
    from explainnet.storage import Store
    session = module.Session.__new__(module.Session)
    session.cfg = SimpleNamespace(config_hash='cfg')
    session.store = Store(tmp_path / 'db')
    session.store.initialize()
    session.data = {'config_hash': 'cfg', 'instance_id': 'teachlive_fixture', 'healthy_traffic': {'run_id': 'old'}}
    session.http = lambda route: {'auto_enabled': False}
    calls = []
    def job(route, body):
        calls.append(route)
        assert route == '/v1/laboratory/reconcile'
        return {'runs': [{'run_id': 'lost_ack_new_run', 'state': 'running'}]}
    session.job = job
    with pytest.raises(ValueError, match='Untracked'):
        session.healthy_traffic()
    assert calls == ['/v1/laboratory/reconcile']
