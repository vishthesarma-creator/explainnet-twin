"""Focused guards and experiment orchestration; native measurements remain separate."""
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_twin import sign, snapshot, window

from explainnet.agent_protocol import validate_parameters
from explainnet.recovery_contracts import RecoveryRequest
from explainnet.recovery_ranking import health, rank, score
from explainnet.recovery_runtime import apply
from explainnet.recovery_service import RecoveryService
from explainnet.recovery_spec import POLICY_HASH, feasibility, generate, validate_action
from explainnet.storage import Store
from explainnet.twin_runtime import TwinEngine
from explainnet.twin_service import TwinCanceled
from explainnet.twin_spec import digest, obsolete


def measured(rtt=10):
    w = window()
    w['features']['rtt_mean_ms'] = rtt
    w['features']['rtt_p95_ms'] = rtt  # Uniform RTT fixture: both policies evaluate the same tail metric.
    w['per_flow']['h1->h3:udp'] = deepcopy(w['per_flow']['h2->h4:udp']) | {'delivered_bps': 6_000_000}
    return w


def test_feasible_unique_logical_candidates_and_rejections():
    s = snapshot()
    plan = generate(s)
    assert len(plan['candidates']) == 4
    assert len({c['candidate_id'] for c in plan['candidates']}) == 4
    assert plan['candidates'][0]['action']['family'] == 'no_change'
    assert {len(c['logical_diff']) for c in plan['candidates']} == {0, 1, 2}
    assert any('no-op' in r['reason'] or 'eligible' in r['reason'] for r in plan['rejected'])
    a = deepcopy(plan['candidates'][1]['action'])
    a['changes'][0]['to_path'] = 'primary'
    with pytest.raises(ValueError, match='no-op'):
        feasibility(s, a)
    a['changes'][0]['pair_id'] = 'h5'
    with pytest.raises(ValueError, match='forbidden'):
        validate_action(a)
    a['changes'][0]['pair_id'] = 'critical'
    a['changes'] *= 2
    with pytest.raises(ValueError, match='duplicate'):
        validate_action(a)


def test_physical_capacity_loops_missing_and_hidden():
    s = snapshot()
    action = generate(s)['candidates'][2]['action']
    s['workload'][0]['offered_bps'] = 28_000_000
    sign(s)
    with pytest.raises(ValueError, match='capacity'):
        feasibility(s, action)
    s = snapshot()
    s['definition']['pairs'][0]['paths']['alternative'] = ['s1', 's4', 's1', 's4', 's5']
    sign(s)
    with pytest.raises(ValueError, match='simple'):
        generate(s)
    s = snapshot()
    s['window']['data_quality']['laboratory_journal'] = {'configured_loss': .1}
    sign(s)
    with pytest.raises(ValueError, match='experimental'):
        generate(s)


def test_dimensionless_demand_units_nochange_and_service_constraints():
    s, w = snapshot(), measured()
    h = health(w, s['workload'])
    assert h['penalty'] == 0
    assert h['normalization']['required_delivered_bps'] == 5_400_000
    w['features']['critical_goodput_bps'] = 2_700_000
    assert health(w, s['workload'])['components']['demand'] == .5
    w['features']['rtt_mean_ms'] = 40
    w['features']['rtt_p95_ms'] = 40
    assert health(w, s['workload'])['components']['rtt'] == 1
    control = generate(s)['candidates'][0]
    scored = score(w, w, control, s['workload'])
    assert scored['score'] == 0 and scored['improvement'] == 0
    repair = generate(s)['candidates'][1]
    assert not score(w, w, repair, s['workload'])['eligible']
    outcome = measured()
    outcome['per_flow']['h2->h4:udp']['delivered_bps'] = 1_000_000
    assert not score(w, outcome, repair, s['workload'])['eligible']


def trials_for(candidates):
    return [{'candidate_id': c['candidate_id'], 'family': c['action']['family'], 'hypothesis_id': 'h0',
        'repetition': r, 'state': 'measured', 'window': measured(40 if c['action']['family'] == 'no_change' else 10)}
        for r in range(2) for c in candidates]


def test_ties_repeat_uncertainty_failures_and_quality():
    s = snapshot()
    cs = generate(s)['candidates'][:3]
    trials = trials_for(cs)
    result = rank(cs, trials, s['workload'], ['h0'], 2)
    assert result['status'] == 'eligible'
    assert result['selected_candidate_id'] == cs[1]['candidate_id']
    assert rank(cs, trials, s['workload'], ['h0'], 2, True)['status'] == 'uncertain'
    assert rank(cs, trials[:1], s['workload'], ['h0'], 2)['status'] == 'no-safe-repair'
    for t in trials:
        if t['family'] != 'no_change':
            t['window']['features']['cpu_busy_fraction'] = .99
    assert rank(cs, trials, s['workload'], ['h0'], 2)['status'] == 'no-safe-repair'


def test_original_target_and_action_wire_contract(tmp_path):
    engine = TwinEngine(SimpleNamespace(state_dir=tmp_path, lock=threading.RLock()))
    with pytest.raises(ValueError, match='twin-owned'):
        apply(engine, 'original', 'a' * 64, {'family': 'no_change', 'changes': [], 'policy_hash': POLICY_HASH})
    with pytest.raises(ValueError):
        validate_parameters('twin_apply_candidate', {'schema_version': 1, 'twin_id': 't', 'snapshot_hash': 'a' * 64,
            'action': {'family': 'scenario_reset', 'changes': [], 'policy_hash': POLICY_HASH}})


@pytest.mark.parametrize('alter_fault', [False, True])
def test_root_fault_preservation_cumulative_and_live_role_guards(tmp_path, monkeypatch, alter_fault):
    s = snapshot()
    action = generate(s)['candidates'][1]['action']
    runtime = {'role': 'twin', 'token': 'owned', 'twin_snapshot_hash': s['snapshot_hash']}
    live = {'record': runtime}
    fault = {'delay_ms': 35, 'loss_fraction': .08, 'physical_bps': 100_000_000}
    def select_path(*_):
        if alter_fault:
            fault['delay_ms'] = 0
    manager = SimpleNamespace(state_dir=tmp_path, lock=threading.RLock(), records={'twUnit': runtime},
        _running=lambda _: live, select_path=select_path)
    engine = TwinEngine(manager)
    engine.records['twUnit'] = {'twin_id': 'twUnit', 'snapshot': s, 'state': 'running'}
    engine.cancel_events['twUnit'] = threading.Event()
    engine.view = lambda instance: {'fingerprint': s['source_fingerprint'], 'ownership': s['ownership'], 'workload': s['workload']}
    monkeypatch.setattr('explainnet.recovery_runtime.impairment_proof', lambda *args: deepcopy(fault))
    if alter_fault:
        with pytest.raises(ValueError, match='impairment'):
            apply(engine, 'twUnit', s['snapshot_hash'], action)
        assert engine.records['twUnit']['recovery_application']['state'] == 'failed'
    else:
        assert apply(engine, 'twUnit', s['snapshot_hash'], action)['fault_preserved']
        assert fault['delay_ms'] == 35
        with pytest.raises(ValueError, match='cumulative'):
            apply(engine, 'twUnit', s['snapshot_hash'], action)
    engine.records['twUnit'].pop('recovery_application')
    runtime['role'] = 'original'
    with pytest.raises(ValueError, match='original execution forbidden'):
        apply(engine, 'twUnit', s['snapshot_hash'], action)


class FakeTwins:
    def __init__(self, store, s):
        self.store, self.s = store, s
        self.agent = self
        self.resets, self.applications, self.destroyed = [], [], []
        self.current = None
        self.cancel_after_apply = False
        self.fail_candidate = False

    def get_snapshot(self, _):
        return self.s

    def twin_view(self, _):
        return {'fingerprint': self.s['source_fingerprint'], 'ownership': self.s['ownership'],
            **{k: self.s['provenance'].get(k) for k in ('agent_epoch', 'forwarding_version', 'workload_config_versions')}}

    def construct(self, _):
        return {'state': 'running'}

    def reset(self, request):
        self.current = None
        self.resets.append(request.hypothesis_id)
        return {'ownership': {'token': str(len(self.resets))}, 'snapshot_hash': self.s['snapshot_hash'],
            'hypothesis_id': request.hypothesis_id, 'state': 'running'}

    def twin_apply_candidate(self, request):
        assert self.current is None, 'cumulative action'
        self.current = request.action
        self.applications.append(request.action)
        if self.fail_candidate and request.action['family'] != 'no_change':
            raise RuntimeError('bounded root application failure')
        if self.cancel_after_apply:
            raise TwinCanceled('test cancellation')
        return {'fault_preserved': True, 'workload_preserved': True}

    def twin_capture(self, request):
        return {'source_after': self.twin_view(None), 'source_before': self.twin_view(None),
            'series': {'original': [{'observed_config_hash': 'x'}]}, 'capture_id': 'capture'}

    def materialize(self, _, instance_id):
        return measured(40 if instance_id == 'original' or self.current['family'] == 'no_change' else 10), {}

    def destroy(self, request):
        self.destroyed.append(request.twin_id)
        return {'state': 'destroyed', 'original_modified': False}


def setup_service(tmp_path):
    store = Store(tmp_path / 'app.sqlite3')
    store.initialize()
    s = snapshot()
    s['expires_utc'] = (datetime.fromisoformat(s['at_utc']) + timedelta(seconds=900)).isoformat()
    s['window']['features']['rtt_mean_ms'] = 40
    s['background_probe']['rtt_mean_ms'] = 40
    sign(s)
    store.insert_record('runs', 'r', {}, config_hash='hash')
    store.insert_record('snapshots', s['snapshot_id'], s, run_id='r', config_hash='hash', snapshot_hash=s['snapshot_hash'])
    with store.connection() as db:
        import json
        db.execute('INSERT INTO twin_snapshots VALUES(?,?,?,?)', (s['snapshot_id'], 'key', s['snapshot_hash'], json.dumps(s)))
    twins = FakeTwins(store, s)
    return RecoveryService(twins), twins, RecoveryRequest(operation_id='op', twin_id='tw', snapshot_id=s['snapshot_id'], max_repairs=2)


def test_reset_each_trial_durable_idempotency_and_finite_budget(tmp_path, monkeypatch):
    service, twins, request = setup_service(tmp_path)
    monkeypatch.setattr('threading.Event.wait', lambda self, _: self.is_set())
    result = service.test(request)
    assert result['state'] == 'eligible'
    assert len(twins.resets) == len(twins.applications) == 12
    assert len({t['reset']['runtime_token'] for t in result['trials']}) == 12
    assert all(t['elapsed_ms'] >= t['candidate_application_ms'] >= 0 for t in result['trials'])
    assert all(t['paired_capture_rpc_ms'] >= 0 and t['materialization_ms'] >= 0 for t in result['trials'])
    assert twins.destroyed == ['tw']
    assert service.test(request)['idempotent']
    with pytest.raises(ValueError, match='different'):
        service.test(request.model_copy(update={'seed': 1}))
    twins.s['source_fingerprint'] = 'drift'
    assert obsolete(twins.s, {'fingerprint': 'old', 'ownership': twins.s['ownership']})


@pytest.mark.parametrize('mode', ['cancel', 'failure', 'expiry', 'budget', 'original'])
def test_canceled_failed_stale_refused_trials(tmp_path, monkeypatch, mode):
    service, twins, request = setup_service(tmp_path)
    monkeypatch.setattr('threading.Event.wait', lambda self, _: self.is_set())
    if mode == 'cancel':
        twins.cancel_after_apply = True
        with pytest.raises(TwinCanceled):
            service.test(request)
        assert service.get('op', current=False)['state'] == 'canceled'
        assert twins.destroyed == ['tw']
    elif mode == 'failure':
        twins.fail_candidate = True
        result = service.test(request)
        assert result['state'] == 'no-safe-repair' and result['failures']
        assert all(t['failure_restoration'] == 'running' for t in result['trials'] if t['state'] == 'failed')
    elif mode == 'expiry':
        twins.s['at_utc'] = (datetime.now(UTC) - timedelta(seconds=181)).isoformat()
        twins.s['expires_utc'] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        sign(twins.s)
        assert service.test(request)['state'] == 'stale'
        assert not twins.resets
    elif mode == 'budget':
        assert service.test(request.model_copy(update={'timeout_s': 30}))['state'] == 'insufficient-evidence'
        assert not twins.resets
    else:
        with pytest.raises(ValueError, match='original'):
            service.test(request.model_copy(update={'twin_id': 'original'}))


def test_current_recommendation_invalidated_by_drift_and_expiry(tmp_path, monkeypatch):
    service, twins, request = setup_service(tmp_path)
    monkeypatch.setattr('threading.Event.wait', lambda self, _: self.is_set())
    assert service.test(request)['state'] == 'eligible'
    previous = twins.twin_view
    twins.twin_view = lambda _: previous(None) | {'fingerprint': 'changed'}
    assert service.get('op')['state'] == 'stale'
    assert service.get('op')['recommendation']['selected_candidate_id'] is None
    assert service.get('op', current=False)['state'] == 'eligible'


def test_missing_original_is_stale_before_any_twin_trial(tmp_path):
    service, twins, request = setup_service(tmp_path)
    def unavailable(_):
        raise RuntimeError('original namespace no longer owned')
    twins.twin_view = unavailable
    assert service.test(request)['state'] == 'stale'
    assert not twins.resets


def test_policy_file_and_typed_actions_are_identical():
    import json
    from pathlib import Path

    from pydantic import ValidationError

    from explainnet.recovery_contracts import AgentRecoveryAction
    from explainnet.recovery_spec import POLICY

    assert json.loads((Path(__file__).resolve().parents[1] / 'config/recovery_policy_v2.json').read_text()) == POLICY
    with pytest.raises(ValidationError):
        AgentRecoveryAction(twin_id='twUnit', snapshot_hash='a' * 64,
            action={'family': 'reroute', 'policy_hash': POLICY_HASH, 'changes': [{'pair_id': 'critical',
                'from_path': 'primary', 'to_path': ['s1', 's4', 's5']}]})


def test_approved_qos_and_background_capability_capacity():
    from explainnet.recovery_spec import POLICY

    s = snapshot()
    q = s['queue_configuration']['s3->s5']
    q['child_classes'] = [{'handle': '5:10', 'rate_bps': 500_000, 'ceil_bps': 500_000},
        {'handle': '5:20', 'rate_bps': 16_000_000, 'ceil_bps': 20_000_000}]
    q['flow_mapping'] = [{'source_host': 'h1', 'target_host': 'h3', 'classid': '5:10', 'default': False},
        {'source_host': None, 'target_host': None, 'classid': '5:20', 'default': True}]
    sign(s)
    action = {'family': 'restore_qos', 'changes': [POLICY['approved_qos']], 'policy_hash': POLICY_HASH}
    assert feasibility(s, action)['physical_capacity_increased'] is False
    s['definition']['links'][2]['forward_bps'] = 10_000_000
    s['baseline']['definition_hash'] = digest(s['definition'])
    sign(s)
    with pytest.raises(ValueError, match='physical capacity'):
        feasibility(s, action)
    s = snapshot()
    s['workload'].append({'profile_id': 'background', 'source_host': 'h5', 'target_host': 'h6',
        'protocol': 'udp', 'offered_bps': 97_000_000, 'packet_size': 1200})
    sign(s)
    action = {'family': 'shape_background', 'changes': [{'source_host': 'h5', 'target_host': 'h6', 'limit_bps': 80_000_000}], 'policy_hash': POLICY_HASH}
    assert feasibility(s, action)['offered_load_bps']['s2->s3'] == 91_000_000
    s['definition']['hosts'][4]['access_bps'] = 70_000_000
    s['baseline']['definition_hash'] = digest(s['definition'])
    sign(s)
    with pytest.raises(ValueError, match='physical access'):
        feasibility(s, action)


def test_pair_alias_cannot_change_permitted_endpoints_and_shape_is_selective():
    s = snapshot()
    action = generate(s)['candidates'][1]['action']
    s['definition']['pairs'][0]['source_host'] = 'h2'
    s['baseline']['definition_hash'] = digest(s['definition'])
    sign(s)
    with pytest.raises(ValueError, match='forbidden logical pair endpoints'):
        feasibility(s, action)
    s = snapshot()
    s['workload'][1] = {'profile_id': 'other', 'source_host': 'h5', 'target_host': 'h4', 'protocol': 'udp',
        'offered_bps': 1_000_000, 'packet_size': 1200}
    s['workload'].append({'profile_id': 'background', 'source_host': 'h5', 'target_host': 'h6', 'protocol': 'udp',
        'offered_bps': 97_000_000, 'packet_size': 1200})
    sign(s)
    action = {'family': 'shape_background', 'changes': [{'source_host': 'h5', 'target_host': 'h6', 'limit_bps': 80_000_000}],
        'policy_hash': POLICY_HASH}
    with pytest.raises(ValueError, match='another endpoint'):
        feasibility(s, action)
