"""Synthetic fixtures verify contracts/arithmetic only; real evidence lives in Stage 9 artifacts."""
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from explainnet.agent_protocol import validate_parameters
from explainnet.config import load_network
from explainnet.receiver_stream import native_receiver
from explainnet.storage import MIGRATIONS, Store
from explainnet.telemetry_contracts import FEATURES
from explainnet.twin_fidelity import compare, freeze_policy
from explainnet.twin_runtime import TwinEngine
from explainnet.twin_spec import digest, obsolete, reconstruct, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]


def window():
    features = dict.fromkeys(FEATURES, 0)
    features.update(rtt_mean_ms=10, rtt_p95_ms=11, rtt_variability_ms=1, critical_goodput_bps=6000000,
        shared_utilization_fraction=.11, qos_utilization_fraction=.55, cpu_busy_fraction=.1, memory_used_fraction=.2)
    return {'window_id': 'wFixture', 'duration_s': 15, 'complete': True, 'inference_ready': True,
        'features': features, 'per_flow': {'h2->h4:udp': {'bytes': 10000, 'duration_s': 12, 'packets': 100,
            'lost_packets': 0, 'delivered_bps': 5000000, 'loss_fraction': 0}},
        'at_utc': datetime.now(UTC).isoformat(), 'sample_ids': ['sampleFixture'],
        'data_quality': {'reasons': [], 'warnings': [], 'coverage_fraction': .9, 'sample_count': 12,
            'transmitted_probes': 30, 'successful_probe_count': 30, 'probe_timeouts': 0, 'failed_probe_batches': 0,
            'receiver_duration_s': 12, 'missing_metrics': [], 'missing_metric_reasons': {}, 'counter_resets': 0, 'stale_age_s': 1}}


def sign(s):
    s['source_fingerprint'] = digest({k: s[k] for k in ('definition', 'selected_paths', 'queue_configuration', 'workload')})
    s['snapshot_hash'] = digest({k: v for k, v in s.items() if k != 'snapshot_hash'})
    return s


def snapshot():
    d, w, now = load_network(ROOT / 'config/topology.yaml').model_dump(), window(), datetime.now(UTC)
    policy = freeze_policy([w, w | {'window_id': 'wOther'}], {'schema_version': 1, 'max_rtt_ms': 100,
        'max_loss_fraction': .02, 'min_goodput_bps': 1000000, 'max_jitter_ms': None})
    return sign({'schema_version': 1, 'snapshot_id': 'snFixture', 'at_utc': now.isoformat(),
        'expires_utc': (now + timedelta(seconds=180)).isoformat(), 'original_instance_id': 'original', 'definition': d,
        'selected_paths': {p['pair_id']: p['default_path'] for p in d['pairs']},
        'queue_configuration': {f'{l[a]}->{l[b]}': {'child_classes': [], 'flow_mapping': [],
            'queues': [{'kind': 'htb', 'handle': '5:', 'limit_packets': None}, {'kind': 'netem', 'handle': '10:', 'limit_packets': 1000}]}
            for l in d['links'] for a, b in [('source', 'target'), ('target', 'source')]},
        'workload': [{'profile_id': 'critical', 'source_host': 'h1', 'target_host': 'h3', 'protocol': 'udp',
            'offered_bps': 6000000, 'packet_size': 1200}, {'profile_id': 'bulk', 'source_host': 'h2',
            'target_host': 'h4', 'protocol': 'udp', 'offered_bps': 5000000, 'packet_size': 1200}],
        'ownership': {'instance_id': 'original', 'token': 'fixture', 'subnet': '10.77.1.0/24',
            'hosts': {h['host_id']: {'name': h['host_id'], 'ip': '10.77.1.' + str(h['address_offset']), 'namespace': h['host_id']} for h in d['hosts']},
            'switches': {s: {'name': s, 'dpid': s} for s in d['switches']}, 'bridges': d['switches'], 'interfaces': []},
        'source_fingerprint': '', 'window': w, 'background_probe': {'transmitted': 30, 'received': 30, 'rtt_mean_ms': 5, 'sample_count': 30},
        'diagnosis': {'status': 'unavailable', 'model_id': None, 'probabilities': None, 'uncertainty': 'fixture', 'reason': 'fixture'},
        'localization': {'status': 'ambiguous', 'candidate_set': ['s2->s3', 's3->s2'], 'uncertainty': 'fixture'},
        'baseline': {'window_ids': ['wFixture', 'wOther'], 'definition_hash': digest(d), 'rtt_mean_ms': 10,
            'background_rtt_mean_ms': 5, 'source': 'fixture'}, 'policy': policy,
        'provenance': {'capture_id': 'vFixture', 'source_window_id': 'wFixture', 'agent_epoch': 'fixture',
            'forwarding_version': 1, 'nominal_settings_source': 'fixture', 'observation_age_s': 1, 'policy_hash': policy['policy_hash']}})


def test_snapshot_immutable_allowlists_and_runtime_ids():
    s = snapshot()
    validate_snapshot(s)
    s['window']['features']['rtt_mean_ms'] = 12
    with pytest.raises(ValueError, match='hash'):
        validate_snapshot(s)
    s = snapshot()
    s['queue_configuration']['s2->s3']['configured_loss'] = .08
    with pytest.raises(ValueError):
        validate_snapshot(sign(s))
    s = snapshot()
    s['window']['features']['answer'] = 1
    with pytest.raises(ValueError):
        validate_snapshot(sign(s))
    s = snapshot()
    s['ownership']['instance_id'] = 'twin'
    with pytest.raises(ValueError, match='ownership'):
        validate_snapshot(sign(s))


def test_delay_ambiguity_no_symmetry_assumed_and_background_constrains_shared():
    s = snapshot()
    s['window']['features']['rtt_mean_ms'] = 50
    s['background_probe']['rtt_mean_ms'] = 45
    s['localization']['candidate_set'] = ['s1->s2', 's2->s3', 's3->s2']
    plan = reconstruct(sign(s))
    assert plan['ambiguity'] == ['s2->s3', 's3->s2']
    assert len(plan['hypotheses']) == 2
    assert all(h['impairments'][0]['added_delay_ms'] == 40 for h in plan['hypotheses'])
    assert all(h['impairments'][0]['loss_fraction'] == 0 for h in plan['hypotheses'])
    s['window']['features']['rtt_mean_ms'] = 200
    assert reconstruct(sign(s))['status'] == 'insufficient-evidence'


def test_saturation_uses_fixed_capacities_and_offered_demand():
    s = snapshot()
    s['workload'].append({'profile_id': 'background', 'source_host': 'h5', 'target_host': 'h6',
        'protocol': 'udp', 'offered_bps': 100000000, 'packet_size': 1200})
    before = deepcopy(s['definition'])
    assert reconstruct(sign(s))['hypotheses'][0]['impairments'] == []
    assert s['definition'] == before


def test_missing_reconstruction_evidence_refuses():
    s = snapshot()
    s['window']['inference_ready'] = False
    assert reconstruct(sign(s))['status'] == 'insufficient-evidence'


def test_frozen_tolerances_loss_floor_required_metrics_pressure_durations():
    s, w = snapshot(), window()
    policy = s['policy']
    other = deepcopy(w)
    other['features']['udp_loss_fraction'] = .025
    assert compare(w, other, policy, s['workload'], s['queue_configuration'])['status'] == 'pass'
    other['features']['udp_loss_fraction'] = .04
    assert compare(w, other, policy, s['workload'], s['queue_configuration'])['status'] == 'fail'
    other['features']['udp_loss_fraction'] = None
    assert compare(w, other, policy, s['workload'], s['queue_configuration'])['status'] == 'insufficient-evidence'
    other = deepcopy(w)
    other['features']['cpu_busy_fraction'] = .9
    assert compare(w, other, policy, s['workload'], s['queue_configuration'])['contamination']
    other['duration_s'] = 10
    assert compare(w, other, policy, s['workload'], s['queue_configuration'])['status'] == 'insufficient-evidence'
    policy['tolerances']['udp_loss_fraction']['absolute'] = 1
    with pytest.raises(ValueError, match='changed'):
        compare(w, w, policy, s['workload'], s['queue_configuration'])


def test_freshness_and_observable_drift():
    s = snapshot()
    view = {'fingerprint': s['source_fingerprint'], 'ownership': s['ownership']}
    assert not obsolete(s, view)
    assert obsolete(s, view, datetime.fromisoformat(s['expires_utc'])) == ['snapshot expired']
    assert 'drift' in obsolete(s, view | {'fingerprint': 'different'})[0]


def test_stream_native_events_partial_tail_and_no_false_finalization():
    start = json.dumps({'event': 'start', 'data': {'timestamp': {'timemillisecs': 123}}}) + '\n'
    assert native_receiver(start) == {'intervals': [], 'start': {'timestamp': {'timemillisecs': 123}}}
    text = start + json.dumps({'event': 'interval', 'data': {'sum': {'sender': False}}}) + '\n' + '{"event":'
    result = native_receiver(text)
    assert len(result['intervals']) == 1 and 'end' not in result
    assert native_receiver('{"intervals": [], "end": {}}')['end'] == {}


def test_agent_schema_rejects_shell_and_wrong_identity():
    validate_parameters('twin_capture', {'schema_version': 1, 'instance_id': 'original', 'duration_s': 15, 'twin_id': None})
    with pytest.raises(ValueError):
        validate_parameters('twin_destroy', {'schema_version': 1, 'twin_id': '../original'})
    with pytest.raises(ValueError):
        validate_parameters('twin_capture', {'schema_version': 1, 'instance_id': 'original', 'duration_s': 21, 'twin_id': None})


def test_scoped_destroy_never_targets_original_and_is_idempotent(tmp_path):
    calls = []
    manager = SimpleNamespace(state_dir=tmp_path, cleanup=lambda target: calls.append(target), lock=__import__('threading').RLock())
    engine = TwinEngine(manager)
    engine._save({'twin_id': 'twFixture', 'state': 'running', 'snapshot': snapshot()})
    engine.destroy('twFixture')
    engine.destroy('twFixture')
    assert calls == ['twFixture']
    with pytest.raises(ValueError):
        engine.destroy('original')


def test_partial_construction_failure_cleans_only_twin(tmp_path):
    s, calls = snapshot(), []
    manager = SimpleNamespace(state_dir=tmp_path, lock=__import__('threading').RLock(), records={},
        cleanup=lambda target: calls.append(target))
    def fail_start(_instance, _definition):
        raise RuntimeError('deliberate unit failure, no packets')
    manager.start = fail_start
    engine = TwinEngine(manager)
    engine.view = lambda _id: {'fingerprint': s['source_fingerprint'], 'ownership': s['ownership']}
    engine.budget = lambda: {'cpus': 8}
    with pytest.raises(RuntimeError, match='unit failure'):
        engine.construct('twFixture', s, 'h0')
    assert calls == ['twFixture']
    assert engine.records['twFixture']['scoped_cleanup']
    with pytest.raises(ValueError, match='separate'):
        engine.construct('original', s, 'h0')


def test_snapshot_request_idempotency_is_immutable_without_agent(tmp_path):
    from explainnet.twin_contracts import SnapshotRequest
    from explainnet.twin_service import TwinService
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    s = snapshot()
    request = SnapshotRequest(instance_id='original', request_key='fixtureKey', baseline={}, policy={})
    store.insert_record('runs', 'rFixture', {}, config_hash='fixture')
    store.insert_record('snapshots', s['snapshot_id'], s, run_id='rFixture', config_hash='fixture', snapshot_hash=s['snapshot_hash'])
    with store.connection() as db:
        db.execute('INSERT INTO twin_snapshots VALUES(?,?,?,?)', (s['snapshot_id'], request.request_key, s['snapshot_hash'], json.dumps(s)))
    store.audit('unit', 'twin_snapshot_request', {'request_hash': digest(request.model_dump())}, subject_id=request.request_key)
    service = TwinService(store, None)
    assert service.snapshot(request)['snapshot'] == s
    with pytest.raises(ValueError, match='different inputs'):
        service.snapshot(request.model_copy(update={'expiry_s': 30}))


def test_calibration_idempotency_and_parameter_collision(tmp_path):
    from explainnet.twin_contracts import CalibrationRequest
    from explainnet.twin_service import TwinService
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    s = snapshot()
    store.insert_record('runs', 'rFixture', {}, config_hash='fixture')
    store.insert_record('snapshots', s['snapshot_id'], s, run_id='rFixture', config_hash='fixture', snapshot_hash=s['snapshot_hash'])
    with store.connection() as db:
        db.execute('INSERT INTO twin_snapshots VALUES(?,?,?,?)', (s['snapshot_id'], 'key', s['snapshot_hash'], json.dumps(s)))
    service = TwinService(store, None)
    service._save_instance({'twin_id': 'twFixture', 'snapshot_id': s['snapshot_id'], 'state': 'running'}, s['snapshot_id'])
    request = CalibrationRequest(twin_id='twFixture', operation_id='calFixture')
    result = {'trial_id': 'calFixture', 'twin_id': 'twFixture', 'created_utc': s['at_utc'], 'state': 'completed', 'request_hash': digest(request.model_dump())}
    service._save_trial(result)
    assert service.calibrate(request) == result
    with pytest.raises(ValueError, match='different inputs'):
        service.calibrate(request.model_copy(update={'max_trials': 3}))


def test_migration_eight_preserves_stage_eight_records(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_utc TEXT NOT NULL)')
        for version, migration in enumerate(MIGRATIONS[:7], start=1):
            db.executescript(migration)
            db.execute('INSERT INTO schema_migrations VALUES(?,?)', (version, 'fixture'))
        db.execute("INSERT INTO runs VALUES('rFixture','fixture','unchanged','{}')")
    store = Store(path)
    store.initialize()
    assert store.healthy()
    assert store.get_record('runs', 'rFixture')['config_hash'] == 'unchanged'


def test_running_cancellation_can_finish_job_without_killing_worker(tmp_path):
    from explainnet.contracts import JobState
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    store.create_job('jFixture', 'twin_measure', 'request')
    assert store.next_queued()['id'] == 'jFixture'
    assert store.finish_job('jFixture', JobState.canceled, 1, error='twin operation canceled')
    assert store.get_job('jFixture')['state'] == 'canceled'


def test_live_capture_indexes_current_intervals_without_changing_measured_metrics(tmp_path):
    from test_telemetry import BASE
    from test_telemetry import snapshot as raw_snapshot

    from explainnet.telemetry_contracts import TelemetrySettings
    from explainnet.telemetry_math import aggregate_windows, receiver_records
    from explainnet.twin_service import TwinService
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    points = [raw_snapshot(t) for t in range(50, 65)]
    points[-1]['active_receiver_runs'] = [{'run_id': 'runningNative', 'state': 'running', 'profiles': [{
        'parameters': {'profile_id': 'critical', 'source_host': 'h1', 'target_host': 'h3', 'protocol': 'udp', 'stream_receiver': True},
        'server_json': {'start': {'timestamp': {'timemillisecs': BASE.timestamp() * 1000}},
            'intervals': [{'sum': {'start': i, 'end': i + 1, 'seconds': 1, 'bytes': 750000, 'packets': 625,
                'lost_packets': 0, 'jitter_ms': .1, 'omitted': False, 'sender': False}} for i in range(65)]}}]}]
    capture = {'started_utc': (BASE + timedelta(seconds=50)).isoformat(), 'started_monotonic_s': 50,
        'duration_s': 15, 'source_before': {'definition': snapshot()['definition'], 'fingerprint': 'fixture'},
        'series': {'lab1': points}}
    expected = aggregate_windows(points + receiver_records(points[-1], 'expected'),
        {'run_id': 'expected', 'instance_id': 'lab1', 'started_monotonic_s': 50, 'started_utc': capture['started_utc']},
        TelemetrySettings(window_s=15, sample_interval_s=2.5), 65)[0]
    actual, _ = TwinService(store, None).materialize(capture, 'lab1')
    assert actual['features'] == expected['features']
    assert actual['per_flow'] == expected['per_flow']
    assert actual['features']['critical_goodput_bps'] == 6000000
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM telemetry_samples WHERE source='iperf_receiver_interval'").fetchone()[0] == 15
    assert len(points[-1]['active_receiver_runs'][0]['profiles'][0]['server_json']['intervals']) == 65


def test_keyed_reset_retry_returns_history_without_rebuilding(tmp_path):
    from explainnet.twin_contracts import TwinResetRequest
    from explainnet.twin_service import TwinService
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    request = TwinResetRequest(twin_id='twFixture', request_key='resetFixture')
    result = {'twin_id': 'twFixture', 'state': 'running', 'ownership': {'token': 'freshFixture'}}
    store.audit('unit', 'twin_reset_request', {'request_hash': digest(request.model_dump()), 'result': result},
        subject_id=request.request_key)
    assert TwinService(store, None).reset(request) == result
    with pytest.raises(ValueError, match='different inputs'):
        TwinService(store, None).reset(request.model_copy(update={'hypothesis_id': 'h1'}))
