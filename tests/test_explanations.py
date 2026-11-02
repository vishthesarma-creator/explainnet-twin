"""Stage 8 software fixtures only; no measured performance or production models."""
import json
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_models import fitted_unit_bundle, window, write_loader_fixture

from explainnet.agent import AgentClient
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.contracts import ServiceObjective
from explainnet.diagnosis_service import DiagnosisService
from explainnet.explanation_engine import RFExplainer, build_background, normalize_multiclass, plain_language
from explainnet.explanation_service import ExplanationService
from explainnet.incident_service import IncidentService
from explainnet.link_localization import localize
from explainnet.localization_evaluation import evaluate_saved_predictions
from explainnet.model_contracts import CLASS_ORDER, FEATURE_ORDER
from explainnet.model_dataset import Partition, load_measured_dataset
from explainnet.storage import Store
from explainnet.telemetry_contracts import TelemetrySettings

DEFINITION = {'pairs': [{'pair_id': 'critical', 'source_host': 'h1', 'target_host': 'h3',
    'paths': {'primary': ['s1', 's2', 's3', 's5']}}]}


def observed_window(i=0, age=0):
    w = window() | {'window_id': f'w{i}', 'start_monotonic_s': 10 * i, 'end_monotonic_s': 10 * (i + 1),
        'at_utc': (datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
        'context': {'selected_paths': {'critical': 'primary'}, 'forwarding_version': 1}}
    return w


def save_window(store, w):
    with store.connection() as db:
        db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?)', (w['run_id'], w['at_utc'], 'unit', '{}'))
        db.execute('INSERT OR REPLACE INTO telemetry_windows VALUES(?,?,?,?,?,?,?)',
            (w['window_id'], w['run_id'], w['instance_id'], w['end_monotonic_s'], w['complete'], w['inference_ready'], json.dumps(w)))


def result(cause='loss', **overrides):
    return {'model_id': 'munit', 'mode': 'live', 'status': 'supported', 'freshness': 'fresh',
        'predicted_class': cause, 'incident': cause != 'healthy', 'service_violations': [],
        'calibrated_probabilities': {c: .2 for c in CLASS_ORDER}, 'probability_status': 'calibrated',
        'confidence': .2, 'reasons': []} | overrides


def unit_background(bundle, X):
    train = Partition(X[::2], np.asarray([c for c in CLASS_ORDER for _ in range(2)]),
        np.asarray(['fit'] * 10), np.asarray(['episode'] * 10), [{'window_id': f'train{i}'} for i in range(10)])
    return build_background(bundle, train, bundle['dataset'], ['fit'])


@pytest.mark.parametrize('cause', CLASS_ORDER)
def test_actual_rf_multiclass_additivity_class_mapping_signs_and_calibration(cause):
    bundle, X = fitted_unit_bundle()
    engine = RFExplainer(bundle, unit_background(bundle, X))
    w = observed_window()
    w['features']['rtt_mean_ms'] = 9
    d = result(cause, status='uncertain', reasons=['unit qualification retained'])
    output = engine.explain(w, d)
    assert output['explained_class'] == cause
    assert engine.native_classes[output['class_index']] == cause
    assert output['additivity_absolute_error'] <= 1e-6
    transformed = bundle['classifier'][0].transform(np.asarray([[w['features'][n] for n in FEATURE_ORDER]]))
    assert output['underlying_model_output'] == bundle['classifier'][-1].predict_proba(transformed)[0, output['class_index']]
    assert output['calibrated_probabilities'] == d['calibrated_probabilities']
    assert output['diagnosis_status'] == 'uncertain'
    assert len(output['contributions']) == len(bundle['classifier'][0].transformed_names_)
    assert len(output['top_features']) <= 3
    for c in output['contributions']:
        assert c['direction'] == ('supporting' if c['contribution'] > 0 else 'opposing' if c['contribution'] < 0 else 'neutral')
    text = plain_language(output, d, localize(w, DEFINITION))
    assert 'diagnosis uncertain' in text and 'Separate calibrated probability' in text
    assert 'physical cause' in text and 'unit qualification retained' in text


def test_supported_multiclass_shapes_and_reject_ambiguity():
    values = np.arange(30).reshape(1, 6, 5)
    expected = np.zeros(5)
    assert np.array_equal(normalize_multiclass(values, expected, 6, 5)[0], values[0])
    assert np.array_equal(normalize_multiclass([values[:, :, i] for i in range(5)], expected, 6, 5)[0], values[0])
    with pytest.raises(ValueError, match='shape'):
        normalize_multiclass(values.transpose(0, 2, 1), expected, 6, 5)
    with pytest.raises(ValueError, match='nonfinite'):
        normalize_multiclass(values.astype(float) * np.nan, expected, 6, 5)


def test_background_train_fit_only_determinism_frozen_preprocessing_and_mapping(tmp_path):
    write_loader_fixture(tmp_path)  # Test rows are nonnumeric SEALED; never converted.
    train, validation, hashes = load_measured_dataset(tmp_path)
    bundle, _ = fitted_unit_bundle()
    bundle['dataset'] = hashes
    groups = sorted(set(train.groups))[::2]
    before = bundle['classifier'][0].statistics_.copy()
    bg = build_background(bundle, train, hashes, groups, limit=8)
    assert bg == build_background(bundle, train, hashes, groups, limit=8)
    assert set(bg['groups']) <= set(groups)
    assert not set(bg['window_ids']) & {w['window_id'] for w in validation.windows}
    assert bg['partition'] == 'train' and len(bg['window_ids']) == 8
    assert np.array_equal(before, bundle['classifier'][0].statistics_)
    with pytest.raises(ValueError, match='differs'):
        build_background(bundle, train, hashes | {'bad': True}, groups)
    altered = deepcopy(bg)
    altered['matrix'][0][0] += 1
    with pytest.raises(ValueError, match='changed'):
        RFExplainer(bundle, altered)


def test_missing_indicator_is_not_measurement_and_units_retained():
    bundle, X = fitted_unit_bundle()
    w = observed_window()
    w['features']['rtt_mean_ms'] = None
    out = RFExplainer(bundle, unit_background(bundle, X)).explain(w, result('loss'))
    measured = next(c for c in out['contributions'] if c['transformed_feature'] == 'rtt_mean_ms')
    indicator = next(c for c in out['contributions'] if c['transformed_feature'] == 'rtt_mean_ms__missing')
    assert measured['original_measured_value'] is None and measured['unit'] == 'milliseconds'
    assert measured['preprocessing'] == 'training median imputation'
    assert indicator['is_missing_indicator'] and indicator['transformed_value'] == 1
    assert 'not a network measurement' in indicator['preprocessing']
    out['top_features'] = [indicator]
    assert 'not a network measurement' in plain_language(out, result('loss'), localize(w, DEFINITION))


def test_incident_dedup_cause_history_fresh_resolution_and_observation_times(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    service = IncidentService(store, DEFINITION)
    for i in range(6):
        save_window(store, observed_window(i))
    w0 = observed_window(0)
    iid = service.observe(w0, result(), 'd0')
    assert service.observe(w0, result(), 'd0') == iid
    w1 = observed_window(1)
    assert service.observe(w1, result('latency'), 'd1') == iid
    assert [e['result']['predicted_class'] for e in service.get(iid)['history']] == ['loss', 'latency']
    w2 = observed_window(2, age=90)
    service.observe(w2, result('healthy', freshness='stale', status='stale'), 'd2')
    assert service.get(iid)['state'] == 'open'
    w3 = observed_window(3)
    w3['inference_ready'] = False
    service.observe(w3, result('healthy'), 'd3')
    assert service.get(iid)['healthy_streak'] == 0
    w4, w5 = observed_window(4), observed_window(5)
    service.observe(w4, result('healthy'), 'd4')
    assert service.get(iid)['state'] == 'open'
    service.observe(w4, result('healthy'), 'monitor:w4')
    assert service.get(iid)['healthy_streak'] == 1  # Same window cannot count twice.
    service.observe(w5, result('healthy'), 'd5')
    incident = service.get(iid)
    assert incident['state'] == 'resolved' and incident['resolution_evidence'] == ['w4', 'w5']
    assert incident['observed_start_utc'] == w0['at_utc'] and incident['resolved_utc'] == w5['at_utc']
    assert service.observe(w0, result('qos'), 'late-model-cause') == iid
    assert service.get(iid)['state'] == 'resolved'
    late = next(e for e in service.get(iid)['history'] if e['source_id'] == 'late-model-cause')
    assert not late['applied_to_lifecycle']
    assert len(service.list()) == 1


def test_historical_healthy_gap_and_changed_path_cannot_resolve(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    service = IncidentService(store, DEFINITION)
    for i in (0, 1, 5, 6):
        save_window(store, observed_window(i))
    iid = service.observe(observed_window(0), result(mode='recorded', freshness='historical'), 'r0')
    service.observe(observed_window(1), result('healthy', mode='recorded', freshness='historical'), 'r1')
    assert service.get(iid)['state'] == 'open' and service.get(iid)['healthy_streak'] == 0
    live = service.observe(observed_window(0), result(), 'l0')
    service.observe(observed_window(1), result('healthy'), 'l1')
    service.observe(observed_window(5), result('healthy'), 'l5')
    assert service.get(live)['state'] == 'open' and service.get(live)['healthy_streak'] == 1
    w = observed_window(6)
    w['context']['selected_paths']['critical'] = 'alternative'
    assert service.observe(w, result('healthy'), 'l6') is None
    assert service.get(live)['state'] == 'open'


def test_ambiguous_localization_counter_ranking_no_shap_or_hidden_inputs():
    w = observed_window()
    out = localize(w, DEFINITION)
    assert out['status'] == 'ambiguous' and len(out['candidate_set']) == 6
    assert out['localization_probability'] is None and not out['shap_used']
    w['directional'] = {'s1->s2': {'duration_s': 8, 'weighted_utilization': 7.6, 'invalid_intervals': []}}
    out = localize(w, DEFINITION)
    assert out['candidate_set'] == ['s1->s2']  # Not the experiment's usual injected link.
    assert out['ranking'][0]['score'] == 2
    w['directional']['s1->s2']['invalid_intervals'] = ['reset']
    assert localize(w, DEFINITION)['status'] == 'ambiguous'
    for key in ('laboratory_journal', 'scenario', 'intended_location', 'injected_parameters'):
        with pytest.raises(ValueError, match='ground truth'):
            localize(w | {key: 'hidden'}, DEFINITION)


def test_observed_queue_deltas_identity_reset_and_bounded_window():
    w = observed_window()
    def sample(t, drops, identity='i'):
        return {'source': 'network_agent', 'sample_id': str(t), 'run_id': w['run_id'], 'monotonic_s': t,
            'links': {'s5->s3': {'identity': identity, 'classes': {}, 'queues': {'x': {'drops': drops, 'backlog': 10}}}}}
    a, b = sample(2, 0), sample(4, 8)
    out = localize(w, DEFINITION, [a, b])
    assert out['candidate_set'] == ['s5->s3'] and out['ranking'][0]['score'] == 4
    assert localize(w, DEFINITION, [a, sample(4, 8, 'changed')])['status'] == 'ambiguous'
    assert localize(w, DEFINITION, [sample(-2, 0), b])['status'] == 'ambiguous'
    with pytest.raises(ValueError, match='ground truth'):
        localize(w, DEFINITION, [a | {'intended_location': 's2->s3'}])


def setup_service(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    telemetry = SimpleNamespace(settings=TelemetrySettings(), objective=ServiceObjective(), status=lambda _: {'live': True})
    diagnosis = DiagnosisService(store, telemetry)
    bundle, X = fitted_unit_bundle()
    diagnosis.bundles.publish(bundle, {'unit_fixture': True}, X)
    diagnosis.active = bundle
    w = observed_window()
    save_window(store, w)
    diagnosis._persist(w, result(mode='recorded', freshness='historical'))
    service = ExplanationService(store, diagnosis, DEFINITION)
    return store, diagnosis, service, w, bundle, X


def test_cache_invalidation_worker_failure_isolation_unsupported_and_seal(tmp_path, monkeypatch):
    store, diagnosis, service, w, bundle, X = setup_service(tmp_path)
    requested = service.request('munit', w['window_id'])
    assert requested['status'] == 'pending'
    assert service.request('munit', w['window_id'])['explanation_id'] == requested['explanation_id']
    runtime = RFExplainer(bundle, unit_background(bundle, X))
    calls = []
    monkeypatch.setattr(service, '_runtime', lambda p: calls.append(p) or runtime)
    ready = service.process(requested)
    assert ready['status'] == 'ready' and calls
    assert service.get(requested['explanation_id'])['status'] == 'ready'
    changed_background = ExplanationService(store, diagnosis, DEFINITION, background_limit=8)
    assert changed_background.request('munit', w['window_id'])['explanation_id'] != requested['explanation_id']
    w['features']['rtt_mean_ms'] += 1
    save_window(store, w)
    changed = service.request('munit', w['window_id'])
    assert changed['status'] == 'unsupported' and changed['explanation_id'] != requested['explanation_id']
    assert service.process(requested)['status'] == 'failed'
    assert service.get(requested['explanation_id'])['status'] == 'ready'  # Immutable terminal evidence.
    assert len(diagnosis.history(w['window_id'])) == 1
    monkeypatch.setattr(diagnosis, '_sealed', lambda _: True)
    with pytest.raises(ValueError, match='sealed'):
        service.request('munit', w['window_id'])
    assert service.process(changed_background.history(w['window_id'])[1])['status'] == 'failed'


def test_callback_failure_never_replaces_diagnosis_and_worker_persists_failure(tmp_path, monkeypatch):
    _store, diagnosis, service, w, _bundle, _X = setup_service(tmp_path)
    def fail(*_):
        raise RuntimeError('isolated explainer failure')
    diagnosis.on_diagnosis = fail
    saved = diagnosis._persist(w, result(mode='recorded'))
    assert saved['predicted_class'] == 'loss' and 'isolated' in diagnosis.explanation_error
    requested = service.request('munit', w['window_id'])
    monkeypatch.setattr(service, '_runtime', fail)
    service.start()
    try:
        deadline = time.monotonic() + 5
        while service.get(requested['explanation_id'])['status'] == 'pending' and time.monotonic() < deadline:
            time.sleep(.02)
        assert service.get(requested['explanation_id'])['status'] == 'failed'
        assert service.thread.is_alive()
    finally:
        service.close()


def test_api_jobs_pending_retrieval_incident_routes_and_validation(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run', agent_socket=tmp_path / 'agent.sock')
    Store(settings.database_path).initialize()
    monkeypatch.setattr(AgentClient, 'inventory', lambda _: {'instances': []})
    app = create_app(settings)
    monkeypatch.setattr(app.state.worker.explanations, 'request', lambda *_: {'explanation_id': 'xunit', 'status': 'pending'})
    with TestClient(app) as client:
        response = client.post('/v1/explanations/request', json={'model_id': 'munit', 'window_id': 'wunit'})
        assert response.status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/v1/jobs/' + response.json()['job_id']).json()
            if job['state'] == 'succeeded':
                break
            time.sleep(.01)
        assert job['result']['status'] == 'pending'
        assert client.get('/v1/explanations').json()['worker_live']
        assert client.get('/v1/explanations/missing').status_code == 404
        assert client.get('/v1/explanations/window/wunit').json()['records'] == []
        assert client.get('/v1/incidents').json()['records'] == []
        assert client.get('/v1/incidents/missing').status_code == 404
        assert client.post('/v1/explanations/request', json={'model_id': 'munit', 'window_id': '../unsafe'}).status_code == 422
        assert client.post('/v1/jobs/repair').status_code == 501


def test_loaded_explainer_reused_and_new_model_version_invalidates(tmp_path):
    store, diagnosis, service, w, bundle, X = setup_service(tmp_path)
    request = service.request('munit', w['window_id'])
    bg = unit_background(bundle, X)
    with store.connection() as db:
        db.execute('INSERT INTO explanation_backgrounds VALUES(?,?,?,?)',
            (request['background_recipe'], 'munit', bg['content_hash'], json.dumps(bg)))
    first = service._runtime(request)
    assert service._runtime(request) is first and len(service.cache) == 1
    assert service.process(request)['status'] == 'ready'
    second_bundle, X = fitted_unit_bundle('msecond')
    diagnosis.bundles.publish(second_bundle, {'unit_fixture': True}, X)
    diagnosis._persist(w, result(model_id='msecond', mode='recorded', freshness='historical'))
    second = service.request('msecond', w['window_id'])
    assert second['cache_key'] != request['cache_key']
    assert second['background_recipe'] != request['background_recipe']
    assert second['explanation_id'] != request['explanation_id']
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM incident_state').fetchone()[0] == 1


def test_additivity_and_persisted_raw_output_mismatch_are_rejected(monkeypatch):
    bundle, X = fitted_unit_bundle()
    engine = RFExplainer(bundle, unit_background(bundle, X))
    w = observed_window()
    with pytest.raises(ValueError, match='persisted diagnosis'):
        engine.explain(w, result('healthy', raw_probabilities={'healthy': -1}))
    monkeypatch.setattr(engine.explainer, 'shap_values', lambda *a, **kw: np.zeros((1, len(engine.pre.transformed_names_), 5)))
    with pytest.raises(ValueError, match='additivity failed'):
        engine.explain(w, result('healthy'))


def test_no_diagnosis_or_selected_class_is_explicitly_unsupported(tmp_path):
    store, diagnosis, service, _w, _bundle, _X = setup_service(tmp_path)
    w = observed_window(1)
    save_window(store, w)
    assert service.request('munit', w['window_id'])['status'] == 'unsupported'
    diagnosis._persist(w, result(predicted_class=None, status='insufficient-data', mode='live'))
    out = service.request('munit', w['window_id'], 'live')
    assert out['status'] == 'unsupported' and out['background_version'] is None


def test_baseline_incidents_without_model_and_classifier_recovery_gate(tmp_path):
    store, diagnosis, service, w, _bundle, _X = setup_service(tmp_path)
    diagnosis.active = None
    with store.connection() as db:
        db.execute('INSERT INTO telemetry_collectors VALUES(?,?,?,?,?,?)', (w['run_id'], w['instance_id'], 'running', 1, 'unit', '{}'))
        db.execute('INSERT INTO baseline_alerts VALUES(?,?,?)',
            (w['window_id'], w['instance_id'], json.dumps({'status': 'alert', 'alert_latched': True, 'violations': [{'rule': 'loss'}]})))
    service._monitor()
    incidents = [i for i in service.incidents.list() if i['mode'] == 'live']
    assert len(incidents) == 1 and incidents[0]['service_status'] == 'degraded'
    diagnosis.active = {'model_id': 'munit'}
    for i in (1, 2):
        current = observed_window(i)
        save_window(store, current)
        with store.connection() as db:
            db.execute('INSERT INTO baseline_alerts VALUES(?,?,?)',
                (current['window_id'], current['instance_id'], json.dumps({'status': 'healthy', 'alert_latched': False, 'violations': []})))
        service._monitor()
        assert service.incidents.get(incidents[0]['incident_id'])['state'] == 'open'
        service.incidents.observe(current, result('healthy'), f'live{i}')
    assert service.incidents.get(incidents[0]['incident_id'])['state'] == 'resolved'


def test_saved_prediction_evaluation_cannot_change_localization(tmp_path):
    store, _diagnosis, _service, w, _bundle, _X = setup_service(tmp_path)
    # Existing table FK relationships require a compact unit-only membership.
    with store.connection() as db:
        db.execute('INSERT INTO dataset_batches VALUES(?,?,?,?,?)', ('db', 'completed', 'unit', 1, '{}'))
        db.execute('INSERT INTO dataset_attempts VALUES(?,?,?,?,?)', ('da', 'db', 'eunit', 'completed', '{}'))
        db.execute('INSERT INTO dataset_members VALUES(?,?,?,?,?,?,?)', (w['window_id'], 'db', 'eunit', 'family', 'train', 'da', 'hash'))
    # This fixture tests evaluation lookup order, not model or localization quality.
    w['context']['traffic_run_ids'] = ['trafficunit']
    save_window(store, w)
    store.insert_record('runs', 'trafficunit', {}, config_hash='unit')
    store.insert_record('ground_truth', 'trafficunit', {'fault_label': 'loss', 'intended_location': 's2->s3', 'affected_directions': []})
    prediction = localize(w, DEFINITION)
    saved = tmp_path / 'saved.json'
    saved.write_text(json.dumps({'cases': [{'window_id': w['window_id'], 'localization': prediction}]}))
    before = saved.read_bytes()
    evaluation = evaluate_saved_predictions(store, saved)
    assert evaluation['cases'][0]['outcome'] == 'ambiguous_contains_truth'
    with store.connection() as db:
        db.execute("UPDATE ground_truth SET payload_json=? WHERE run_id='trafficunit'", (json.dumps({'fault_label': 'loss', 'intended_location': 'outside', 'affected_directions': []}),))
    assert evaluate_saved_predictions(store, saved)['cases'][0]['outcome'] == 'ambiguous_misses_truth'
    assert saved.read_bytes() == before and localize(w, DEFINITION) == prediction
    with store.connection() as db:
        db.execute("UPDATE dataset_members SET partition='test' WHERE window_id=?", (w['window_id'],))
    with pytest.raises(ValueError, match='test remains sealed'):
        evaluate_saved_predictions(store, saved)
