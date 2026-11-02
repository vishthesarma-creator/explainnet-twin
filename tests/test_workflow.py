"""Software guards/failure fixtures, distinct from native Stage 11 evidence."""
import json
import sqlite3
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_twin import snapshot

from explainnet.agent_protocol import validate_parameters
from explainnet.api import create_app
from explainnet.config import Settings, load_network
from explainnet.jobs import Worker
from explainnet.lab_runtime import LabActionEngine
from explainnet.receiver_stream import native_receiver, recent_receiver
from explainnet.recovery_spec import generate
from explainnet.storage import Store
from explainnet.workflow_contracts import ApplyRequest, ModeRequest
from explainnet.workflow_service import RecoveryCoordinator

ROOT = Path(__file__).resolve().parents[1]


def test_recent_native_stream_retains_actual_omission_and_full_file(tmp_path):
    records = [{'event': 'start', 'data': {'timestamp': {'timemillisecs': 1000}}}]
    records += [{'event': 'interval', 'data': {'sum': {'start': i - 1, 'end': i, 'seconds': 1, 'omitted': True}}} for i in range(1, 4)]
    records += [{'event': 'interval', 'data': {'sum': {'start': i - 1, 'end': i, 'seconds': 1, 'omitted': False}, 'padding': 'x' * 300}}
        for i in range(1, 1000)]
    p = tmp_path / 'server.json'
    p.write_text(''.join(json.dumps(r) + '\n' for r in records))
    before = p.read_bytes()
    short = recent_receiver(p)
    assert len(short['intervals']) == 33
    assert max(i['sum']['end'] for i in short['intervals'] if i['sum']['omitted']) == 3
    assert short['intervals'][-1] == native_receiver(p.read_text())['intervals'][-1]
    assert p.read_bytes() == before


def fake_engine(tmp_path, monkeypatch):
    s = snapshot()
    record = {'token': s['ownership']['token'], 'instance_id': 'original', 'selected_paths': dict(s['selected_paths']),
        'hosts': s['ownership']['hosts'], 'switches': {k: {'name': k} for k in s['definition']['switches']},
        'definition': s['definition'], 'bridges': s['definition']['switches'], 'host_processes': [{'pid': 123, 'start_ticks': '42', 'namespace': 'owned'}]}
    m = SimpleNamespace(state_dir=tmp_path, lock=threading.RLock(), allow_lab_test_hooks=False,
        _running=lambda _: {'record': record}, _owned_bridge=lambda *args: True)
    view = {'fingerprint': s['source_fingerprint'], 'ownership': s['ownership'], 'forwarding_version': 1,
        'selected_paths': record['selected_paths'], 'workload': s['workload'], 'at_utc': datetime.now(UTC).isoformat()}
    m.twins = SimpleNamespace(view=lambda _: deepcopy(view))
    monkeypatch.setattr('explainnet.network_runtime.process_identity', lambda _: record['host_processes'][0])
    monkeypatch.setattr('explainnet.lab_runtime.impairment_proof', lambda *args: {'owned_active_impairment': 'unchanged'})
    engine = LabActionEngine(m)
    engine._flows = lambda _: {'s1': [view['selected_paths']['critical']]}
    def select(instance, pair, path, **kwargs):
        assert (tmp_path / 'lab_action_a.json').exists(), 'mutation without durable root journal'
        view['selected_paths'][pair] = path
        view['forwarding_version'] += 1
    m.select_path = select
    m.probe = lambda *args: {'passed': True}
    return engine, s, view, record


def test_root_prepare_before_mutation_rollback_and_unsafe_undo(tmp_path, monkeypatch):
    engine, s, view, _ = fake_engine(tmp_path, monkeypatch)
    action = generate(s)['candidates'][1]['action']
    prepared = engine.prepare('original', 'a', s, action, 'key')
    assert prepared['state'] == 'prepared' and view['selected_paths']['critical'] == 'primary'
    assert engine.prepare('original', 'a', s, action, 'key')['state'] == 'prepared'
    with pytest.raises(ValueError, match='lease'):
        engine.guard('original')
    r = engine.records['a']
    # Model the acknowledged application boundary; rollback uses real journal.
    view['selected_paths']['critical'] = 'alternative'
    view['forwarding_version'] = 2
    r.update(state='kept', after=engine._readback(r))
    view['forwarding_version'] = 3
    with pytest.raises(ValueError, match='intervening'):
        engine.rollback('a')
    view['forwarding_version'] = 2
    assert engine.rollback('a')['state'] == 'rolled_back'
    assert view['selected_paths']['critical'] == 'primary'
    assert engine.rollback('a')['state'] == 'rolled_back'


def test_owner_target_and_normal_hook_rejection(tmp_path, monkeypatch):
    engine, s, _, record = fake_engine(tmp_path, monkeypatch)
    action = generate(s)['candidates'][1]['action']
    with pytest.raises(ValueError, match='disabled'):
        engine.prepare('original', 'a', s, action, 'key', 'partial_failure')
    record['role'] = 'twin'
    with pytest.raises(ValueError, match='twin target'):
        engine.prepare('original', 'a', s, action, 'key')
    with pytest.raises(ValueError):
        validate_parameters('lab_apply', {'schema_version': 1, 'action_id': 'a', 'command': 'tc anything'})


def coordinator(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    worker = SimpleNamespace(store=store, agent=SimpleNamespace(), twins=SimpleNamespace(), recovery=SimpleNamespace(),
        explanations=SimpleNamespace(definition=load_network(ROOT / 'config/topology.yaml')))
    return RecoveryCoordinator(worker)


def test_modes_audited_restart_disabled_and_no_nested_job(tmp_path):
    c = coordinator(tmp_path)
    assert c.control()['mode'] == 'recommend' and not c.control()['auto_enabled']
    c.mode(ModeRequest(mode='lab-auto-repair', allow_observed_only=True))
    assert c.control()['auto_enabled']
    c.reconcile()
    assert c.control()['mode'] == 'recommend' and not c.control()['auto_enabled']
    assert len(c.store.list_audit()) >= 2
    c.mode(ModeRequest(mode='observe'))
    c.reconcile()
    assert c.control()['mode'] == 'observe'


def test_typed_api_modes_stop_prompt_and_hook_scope(tmp_path):
    cfg = Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run',
        agent_socket=tmp_path / 'absent', topology_file=ROOT / 'config/topology.yaml')
    Store(cfg.database_path).initialize()
    with TestClient(create_app(cfg)) as client:
        assert client.get('/v1/lab/control').json()['mode'] == 'recommend'
        assert client.post('/v1/lab/mode', json={'mode': 'external-auto'}).status_code == 422
        assert client.post('/v1/lab/apply', json={'workflow_id': 'w', 'action_id': 'a', 'request_key': 'k',
            'test_hook': 'shell_command'}).status_code == 422
        assert client.post('/v1/lab/automation/stop').json()['new_actuation_prevented']


def test_native_interval_anchor_survives_later_wall_clock_step():
    from explainnet.telemetry_math import receiver_records

    native = {'start': {'timestamp': {'timemillisecs': 1_000_010}}, 'intervals': [{'sum': {'start': 0, 'end': 1,
        'seconds': 1, 'sender': False, 'bytes': 1200, 'packets': 1, 'lost_packets': 0, 'jitter_ms': 0}}]}
    point = {'completed_runs': [], 'active_receiver_runs': [{'run_id': 'r', 'state': 'running', 'profiles': [{
        'parameters': {'stream_receiver': True, 'profile_id': 'critical', 'protocol': 'udp', 'source_host': 'h1', 'target_host': 'h3'},
        'server_json': native, 'receiver_clock_anchor': {'utc_epoch_s': 1000, 'monotonic_s': 10}}]}],
        'monotonic_s': 20, 'at_utc': datetime.fromtimestamp(2000, UTC).isoformat(), 'instance_id': 'original', 'config_version': 'v1'}
    before = receiver_records(point, 'collector')[0]
    point.update(monotonic_s=21, at_utc=datetime.fromtimestamp(2100, UTC).isoformat())
    after = receiver_records(point, 'collector')[0]
    assert before['start_monotonic_s'] == pytest.approx(10.01)
    assert before['start_monotonic_s'] == after['start_monotonic_s']
    assert before['sample_id'] == after['sample_id']


def test_model_exception_is_explicit_and_uncertain_result_cannot_actuate(tmp_path):
    c = coordinator(tmp_path)
    c.worker.diagnosis = SimpleNamespace(status=lambda: {'active_model_id': None})
    w = {'state': 'recommended', 'diagnosis': {'status': 'observed-only', 'model_id': None}, 'experiment_id': 'e'}
    c.mode(ModeRequest(mode='assisted-repair'))
    with pytest.raises(ValueError, match='explicit observed-only'):
        c._eligible(w, False)
    c.mode(ModeRequest(mode='assisted-repair', allow_observed_only=True))
    c.recovery.get = lambda _: {'state': 'uncertain', 'recommendation': {'status': 'uncertain'}}
    with pytest.raises(ValueError, match='uncertain/stale/poor-fidelity'):
        c._eligible(w, False)
    c.mode(ModeRequest(mode='observe'))
    for automated in (False, True):
        with pytest.raises(ValueError, match='operating mode'):
            c._mode_gate(automated)
    c.mode(ModeRequest(mode='assisted-repair'))
    with pytest.raises(ValueError, match='exception revoked'):
        c._mode_gate(False, observed_only=True)


def test_storage_poll_io_error_is_visible_and_does_not_kill_worker(tmp_path, monkeypatch):
    store = Store(tmp_path / 'io.sqlite3')
    store.initialize()
    worker = Worker(store, SimpleNamespace(), poll_s=.01)
    failed = threading.Event()
    healthy = threading.Event()
    def poll():
        if not healthy.is_set():
            failed.set()
            raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(store, 'next_queued', poll)
    thread = threading.Thread(target=worker._loop)
    thread.start()
    try:
        assert failed.wait(2)
        until = time.monotonic() + 2
        while worker.storage_error is None and time.monotonic() < until:
            time.sleep(.01)
        assert thread.is_alive() and worker.storage_error == 'disk I/O error'
        healthy.set()
        until = time.monotonic() + 2
        while worker.storage_error and time.monotonic() < until:
            time.sleep(.01)
        assert worker.storage_error is None and thread.is_alive()
    finally:
        worker._stop.set()
        thread.join(2)


def test_transient_uses_whole_overlapping_native_intervals(tmp_path, monkeypatch):
    c = coordinator(tmp_path)
    c.agent.telemetry_observe = lambda _: {'native': 'preserved'}
    records = [{'valid': True, 'start_monotonic_s': start, 'end_monotonic_s': start + 1,
        'source_host': 'h1', 'target_host': 'h3', 'bytes': 1200, 'duration_s': 1, 'packets': 10, 'lost_packets': 2}
        for start in (9, 10, 11, 12)]
    monkeypatch.setattr('explainnet.workflow_service.receiver_records', lambda *args: records)
    measured = c._transient({'action_id': 'a', 'instance_id': 'original', 'created_utc': datetime.now(UTC).isoformat(),
        'application': {'application_started_monotonic_s': 10.5, 'application_ended_monotonic_s': 11.2}})
    assert measured['status'] == 'measured' and len(measured['native_intervals']) == 2
    assert measured['metrics']['h1->h3']['duration_s'] == 2
    assert measured['metrics']['h1->h3']['loss_fraction'] == .2
    assert measured['metrics']['h1->h3']['goodput_bps'] == 9600


def test_already_queued_mutation_is_refused_during_recovery(tmp_path):
    store = Store(tmp_path / 'queued.sqlite3')
    store.initialize()
    worker = Worker(store, SimpleNamespace(), poll_s=.01)
    called = []
    worker.handlers['model_load'] = lambda _: called.append(True)
    job_id = worker._enqueue('model_load', 'test', {'schema_version': 1, 'model_id': 'model'}, 'external')
    worker.coordinator.busy = lambda *args: True
    thread = threading.Thread(target=worker._loop)
    thread.start()
    try:
        until = time.monotonic() + 3
        while store.get_job(job_id)['state'] == 'queued' and time.monotonic() < until:
            time.sleep(.01)
        until = time.monotonic() + 3
        while store.get_job(job_id)['state'] == 'running' and time.monotonic() < until:
            time.sleep(.01)
        result = store.get_job(job_id)
        assert result['state'] == 'failed' and 'queued mutation rejected' in result['error']
        assert not called
    finally:
        worker._stop.set()
        thread.join(2)


def test_database_failure_after_apply_cannot_skip_root_rollback(tmp_path, monkeypatch):
    c = coordinator(tmp_path)
    source = snapshot()
    candidate = generate(source)['candidates'][1]
    w = {'workflow_id': 'w', 'instance_id': 'original', 'incident_id': 'incident', 'snapshot_id': 'snapshot',
        'diagnosis': {'status': 'observed-only'}}
    c._eligible = lambda *args: ({'lineage': {}}, candidate)
    c.twins.get_snapshot = lambda _: source
    c._sample = lambda _: ({'window_id': 'pre'}, {})
    c.recovery.freshness = lambda _: []
    c._guard = lambda *args: None
    c._mode_gate = lambda *args: {}
    c._state = lambda workflow, state, **extra: workflow.update(state=state, **extra)
    c.store.insert_record = lambda *args, **kwargs: None
    c.agent.lab_prepare = lambda _: {'state': 'prepared'}
    applied, restored = [], []
    c.agent.lab_apply = lambda _: applied.append(True) or {'state': 'applied'}
    c.agent.lab_rollback = lambda _: restored.append(True) or {'state': 'rolled_back', 'restoration_probe': {'passed': True}}
    c._transient = lambda _: {'status': 'unavailable', 'metrics': None}
    saves = []
    def save_action(action):
        saves.append(action['state'])
        if len(saves) >= 3:
            raise sqlite3.OperationalError('disk I/O error')
    c._save_action = save_action
    monkeypatch.setattr('explainnet.workflow_service.quality', lambda *args: [])
    monkeypatch.setattr('explainnet.workflow_service.health', lambda *args: {'penalty': 1})
    c._apply(w, ApplyRequest(workflow_id='w', action_id='a', request_key='k'))
    assert applied == [True] and restored == [True]
    assert w['state'] == 'rolled_back' and c.degraded and c.watch_stop.is_set()
    assert not c.control()['auto_enabled']
    with pytest.raises(ValueError, match='degraded'):
        c.mode(ModeRequest(mode='lab-auto-repair'))
