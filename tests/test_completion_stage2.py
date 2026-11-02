"""Software fixtures only; native trained/fidelity evidence is reported separately."""
import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from pydantic import ValidationError
from test_twin import sign, snapshot, window
from test_workflow import fake_engine

from explainnet.contracts import ServiceObjective
from explainnet.dashboard.client import ApiClient, ApiError
from explainnet.incident_service import IncidentService
from explainnet.model_contracts import CLASS_ORDER, FEATURE_HASH
from explainnet.model_policy import DEFAULT_POLICY, infer
from explainnet.network_runtime import NetworkManager
from explainnet.recovery_ranking import health
from explainnet.recovery_spec import generate
from explainnet.rejection_details import experiment_rejections
from explainnet.scenario_runtime import ScenarioEngine
from explainnet.service_requirements import VERSION, evaluate, resolve
from explainnet.storage import Store
from explainnet.telemetry_contracts import CollectorStartRequest, TelemetrySettings
from explainnet.telemetry_monitor import rules
from explainnet.twin_spec import validate_snapshot
from explainnet.workflow_contracts import WorkflowRequest


def measured(rtt=66):
    w = window()
    w.update(at_utc=datetime.now(UTC).isoformat(), complete=True, inference_ready=True, start_monotonic_s=0, end_monotonic_s=15,
        feature_schema_version=1, feature_schema_hash=FEATURE_HASH)
    w['features'].update(rtt_mean_ms=rtt, rtt_p95_ms=rtt, critical_offered_bps=6_000_000)
    return w


def test_shared_declared_service_tightens_generic_objective_consistently():
    w = measured(); settings = TelemetrySettings(); objective = ServiceObjective(max_rtt_ms=100)
    evidence = evaluate(w, objective)
    assert evidence['contract']['max_rtt_ms'] == 20 and evidence['contract']['version'] == VERSION
    assert evidence['service_violation'] and any(v['rule'] == 'rtt_p95_ms' for v in rules(w, settings, objective))
    assert health(w, snapshot()['workload'], objective)['service_evidence']['contract']['max_rtt_ms'] == 20
    assert resolve(w['features'], ServiceObjective(max_rtt_ms=10))['max_rtt_ms'] == 10


def test_missing_service_is_unavailable_and_low_demand_is_not_delivery_fault():
    w = measured(6)
    w['features'].update(rtt_p95_ms=None, critical_offered_bps=1000, critical_goodput_bps=10)
    result = evaluate(w)
    assert 'rtt_p95_ms' in result['missing'] and not result['service_acceptable']
    assert not any(v['rule'] == 'delivered_demand' for v in result['violations'])
    workload = deepcopy(snapshot()['workload'])
    next(p for p in workload if p['source_host']=='h1' and p['target_host']=='h3')['offered_bps'] = 1000
    w['features']['rtt_p95_ms'] = 6
    assert health(w, workload)['components']['demand'] == 0


def fake_bundle(probabilities):
    estimator = SimpleNamespace(classes_=np.array(CLASS_ORDER), predict_proba=lambda _: np.array([probabilities]),
        named_steps={'preprocessing':SimpleNamespace(kept_indices_=[], dropped_names_=[])})
    return {'model_id':'fixture_model', 'calibrator':estimator, 'classifier':estimator, 'policy':DEFAULT_POLICY,
        'anomaly_threshold':.62244014, 'anomaly_preprocessing':SimpleNamespace(transform=lambda x:x),
        'isolation_forest':SimpleNamespace(score_samples=lambda _:np.array([-.568211939]))}


def test_high_confidence_fault_uses_actual_service_not_lowered_anomaly_gate():
    w = measured()
    result = infer(fake_bundle([.01,.01,.01,.94,.03]), w, TelemetrySettings(), ServiceObjective(max_rtt_ms=100), mode='live', live=True)
    assert result['status'] == 'supported' and result['predicted_class'] == 'latency'
    assert not result['anomalous'] and result['anomaly_threshold'] == .62244014
    assert result['service_violation'] and result['service_contract_version'] == VERSION
    assert result['confidence'] == .94


def test_healthy_abstention_is_preserved():
    result = infer(fake_bundle([.58,.1,.1,.11,.11]), measured(6), TelemetrySettings(), ServiceObjective(max_rtt_ms=100))
    assert result['status'] == 'uncertain' and 'classifier confidence below policy threshold' in result['reasons']


def test_snapshot_v2_is_immutable_and_rejects_hidden_or_altered_service():
    s = snapshot(); s.update(schema_version=2, measurement_protocol='paired_capture_v2_fixed_probe_warmup',
        service_requirements=resolve(s['window']['features'], s['policy']['objective']))
    sign(s); validate_snapshot(s)
    bad = deepcopy(s); bad['service_requirements']['max_rtt_ms'] = 66; sign(bad)
    with pytest.raises(ValueError, match='service'): validate_snapshot(bad)
    bad = deepcopy(s); bad['service_requirements']['injected_parameters'] = {'configured_delay':60}; sign(bad)
    with pytest.raises(ValueError, match='experimental'): validate_snapshot(bad)


def test_candidate_budget_is_distinct_feasible_changes_plus_control():
    plan = generate(snapshot(), 2)
    assert len(plan['candidates']) == 3 and plan['candidates'][0]['action']['family'] == 'no_change'
    assert len({c['candidate_id'] for c in plan['candidates']}) == 3
    assert all(c['logical_diff'] and not c['feasibility']['physical_capacity_increased'] for c in plan['candidates'][1:])
    assert WorkflowRequest.model_fields['max_repairs'].default == 2


@pytest.mark.parametrize('condition', ['latency','loss','saturation','qos'])
def test_two_feasible_changes_for_declared_observable_testbed_conditions(condition):
    s = snapshot()
    if condition == 'saturation':
        s['workload'].append({'profile_id':'background','source_host':'h5','target_host':'h6',
            'protocol':'udp','offered_bps':97_000_000,'packet_size':1200})
    elif condition == 'qos':
        s['workload'][0]['offered_bps'] = 2_000_000
        s['workload'][1]['offered_bps'] = 30_000_000
        s['queue_configuration']['s3->s5'].update(
            child_classes=[{'handle':'5:10','rate_bps':300_000,'ceil_bps':300_000},
                {'handle':'5:20','rate_bps':16_000_000,'ceil_bps':20_000_000}],
            flow_mapping=[{'source_host':'h1','target_host':'h3','classid':'5:10','default':False},
                {'source_host':None,'target_host':None,'classid':'5:20','default':True}])
    sign(s)
    plan = generate(s,2)
    assert plan['feasible_repair_count'] == 2 and len(plan['candidates']) == 3
    assert all(c['logical_diff'] and not c['feasibility']['physical_capacity_increased'] for c in plan['candidates'][1:])
    assert len({c['candidate_id'] for c in plan['candidates']}) == 3
    if condition == 'qos': assert plan['candidates'][2]['action']['family'] == 'restore_qos'


def test_nested_fidelity_rejection_retains_required_and_observed_values():
    metric = {'metric':'rtt_variability_ms','original':.148,'twin':7.638,'absolute_error':7.49,'tolerance':3.074,'status':'fail'}
    result = experiment_rejections({'trials':[{'trial_id':'trial','fidelity':{'metrics':[metric]}}]})
    assert result[0]['absolute_error'] > result[0]['tolerance'] and result[0]['original'] == .148


def test_explicit_collector_lifetime_remains_bounded():
    assert CollectorStartRequest(instance_id='original',duration_s=900).duration_s == 900
    with pytest.raises(ValidationError): CollectorStartRequest(instance_id='original',duration_s=1201)


def test_sampler_and_workflow_capture_share_one_live_incident(tmp_path):
    store = Store(tmp_path/'db'); store.initialize(); service = IncidentService(store)
    w = measured(); w.update(instance_id='original',run_id='collector',window_id='one')
    w['context'] = {'traffic_run_ids':['traffic'], 'agent_epoch':'owner', 'forwarding_version':1,'selected_paths':{'critical':'primary'}}
    store.insert_record('runs','collector',{},config_hash='fixture'); store.insert_record('runs','capture',{},config_hash='fixture')
    other = w | {'run_id':'capture','window_id':'two'}
    with store.connection() as db:
        for row in [w, other]:
            db.execute('INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?)',
                (row['window_id'], row['run_id'], 'original', 15, 1, 1, json.dumps(row)))
    result = {'mode':'live','status':'supported','freshness':'fresh','incident':True,'service_violations':['rtt']}
    first = service.observe(w,result,'first',context_token='root')
    assert service.observe(other,result,'second') == first
    assert len(service.list('original')) == 1


def test_expiry_countdown_is_not_an_installed_configuration_change(tmp_path, monkeypatch):
    engine,s,view,_ = fake_engine(tmp_path,monkeypatch)
    action = generate(s)['candidates'][1]['action']
    prepared = engine.prepare('original','a',s,action,'key')
    view['workload_remaining_s'] = 900
    before = engine._readback(engine.records['a'])
    view['workload_remaining_s'] = 800
    assert engine._readback(engine.records['a']) == before and prepared['state'] == 'prepared'


def test_ownership_batch_checks_every_bridge_without_cached_authorization(monkeypatch):
    calls = []
    rows = [['b1',['map',[['explainnet_instance','original'],['explainnet_token','owner']]]],
        ['b2',['map',[['explainnet_instance','original'],['explainnet_token','owner']]]]]
    def native(*args):
        calls.append(args)
        return json.dumps({'headings':['name','external_ids'],'data':rows})
    monkeypatch.setattr('explainnet.network_runtime.command', native)
    manager = object.__new__(NetworkManager)
    record = {'instance_id':'original','token':'owner','bridges':['b1','b2']}
    assert manager._verified_bridges(record) and len(calls) == 1
    rows[1][1][1][1][1] = 'foreign'
    assert not manager._verified_bridges(record) and len(calls) == 2
    rows.pop()
    assert not manager._verified_bridges(record)
    assert not manager._verified_bridges(record | {'token':None}) and len(calls) == 3


def test_restore_ignores_only_native_packet_counter():
    original = 'qdisc htb 5: root direct_packets_stat 0 direct_qlen 1000\nnetem delay 1ms seed 12'
    assert ScenarioEngine.configuration_text(original) == ScenarioEngine.configuration_text(original.replace('stat 0','stat 1'))
    for change in ['delay 2ms','seed 13','direct_qlen 999']:
        altered = original.replace('delay 1ms',change) if change.startswith('delay') else original.replace('seed 12',change) if change.startswith('seed') else original.replace('direct_qlen 1000',change)
        assert ScenarioEngine.configuration_text(original) != ScenarioEngine.configuration_text(altered)


@pytest.mark.parametrize('bad', [None, 'hash', 'shape'])
def test_dashboard_hydrates_bounded_integrity_checked_details(bad):
    native = json.dumps({'trials':[{'raw':'x'*4_100_000}]} if bad != 'shape' else []).encode()
    digest = hashlib.sha256(native).hexdigest()
    def response(request):
        if request.url.path == '/v1/test':
            return httpx.Response(200,json={'response_schema_version':2,'evidence':{'bytes':len(native),'sha256':digest},
                'evidence_retrieval':'/v1/evidence/'+digest})
        offset = int(request.url.params['offset']); block = native[offset:offset+49152]
        return httpx.Response(200,json={'sha256':digest if bad != 'hash' else 'wrong','offset':offset,
            'next_offset':offset+len(block),'total_bytes':len(native),'base64':base64.b64encode(block).decode()})
    client = ApiClient(transport=httpx.MockTransport(response))
    if bad:
        with pytest.raises(ApiError, match='mismatch|shape'): client.get('/v1/test')
    else:
        assert len(client.get('/v1/test')['trials'][0]['raw']) == 4_100_000
