"""Isolated synthetic unit fixtures; never used for measured model-quality claims."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.pipeline import Pipeline

from explainnet.contracts import ServiceObjective
from explainnet.dataset_contracts import Schedule, digest, make_schedule
from explainnet.dataset_export import valid_window_duration
from explainnet.dataset_recovery import recovery_limits, recovery_telemetry
from explainnet.dataset_repository import DatasetRepository
from explainnet.dataset_service import DatasetService
from explainnet.diagnosis_service import DiagnosisService
from explainnet.model_bundle import BundleRepository
from explainnet.model_contracts import CLASS_ORDER, DATASET_UNITS, FEATURE_HASH, FEATURE_ORDER, UNITS
from explainnet.model_dataset import Partition, load_measured_dataset
from explainnet.model_features import MeasurementPreprocessor, feature_array
from explainnet.model_policy import DEFAULT_POLICY, infer, ordered_probabilities
from explainnet.model_training import assign_groups, dependency_versions, reliability
from explainnet.storage import Store
from explainnet.telemetry_contracts import TelemetrySettings


def measurements():
    f = {n: 0.0 for n in FEATURE_ORDER}
    f.update(rtt_mean_ms=5, rtt_p95_ms=6, rtt_variability_ms=1, critical_goodput_bps=2000000,
        critical_offered_bps=2000000, offered_demand_bps=3000000, active_flow_count=2,
        shared_utilization_fraction=.03, qos_utilization_fraction=.15, cpu_busy_fraction=.1,
        memory_used_fraction=.1, primary_path_fraction=1)
    return f


def window():
    return {'window_id': 'wfixture', 'run_id': 'tfixture', 'instance_id': 'fixture',
        'at_utc': datetime.now(UTC).isoformat(), 'feature_schema_version': 1, 'feature_schema_hash': FEATURE_HASH,
        'complete': True, 'inference_ready': True, 'features': measurements(),
        'start_monotonic_s': 0, 'end_monotonic_s': 10, 'data_quality': {'reasons': [], 'warnings': []}}


class FixedProbabilities:
    def __init__(self, probability, pre):
        self.classes_ = np.asarray(CLASS_ORDER[::-1])
        self.probability = probability
        self.named_steps = {'preprocessing': pre}

    def predict_proba(self, X):
        return np.tile(np.asarray(self.probability)[::-1], (len(X), 1))


def policy_bundle(probability=(.95, .01, .01, .02, .01), calibrated=None, anomaly=.4):
    pre = MeasurementPreprocessor().fit(feature_array([measurements(), measurements()]))
    return {'model_id': 'munit', 'classifier': FixedProbabilities(probability, pre),
        'calibrator': None if calibrated is None else FixedProbabilities(calibrated, pre),
        'anomaly_preprocessing': pre, 'isolation_forest': SimpleNamespace(score_samples=lambda X: np.full(len(X), -anomaly)),
        'anomaly_threshold': .6, 'policy': DEFAULT_POLICY}


def test_allowlist_order_and_training_only_preprocessing():
    first, second = measurements(), measurements()
    first['rtt_mean_ms'], second['rtt_mean_ms'] = 2, 4
    first['bulk_class_rate_bps'], second['bulk_class_rate_bps'] = None, None
    X = feature_array([first, second])
    pre = MeasurementPreprocessor().fit(X)
    held = measurements() | {'rtt_mean_ms': None, 'bulk_class_rate_bps': None}
    transformed = pre.transform(feature_array([held]))
    assert transformed[0, pre.feature_names_.index('rtt_mean_ms')] == 3
    assert pre.sample_count_ == 2 and 'bulk_class_rate_bps' in pre.dropped_names_
    assert len(pre.transformed_names_) == 2 * len(pre.feature_names_)
    assert pre.original_mapping_ == pre.feature_names_ * 2
    assert pre.get_feature_names_out(FEATURE_ORDER).tolist() == pre.transformed_names_
    with pytest.raises(ValueError, match='order'):
        pre.get_feature_names_out(FEATURE_ORDER[::-1])
    with pytest.raises(ValueError, match='forbidden'):
        feature_array([measurements() | {'label': 'healthy'}])
    missing = measurements() | {'shared_utilization_fraction': None}
    with pytest.raises(ValueError, match='all-missing required'):
        MeasurementPreprocessor().fit(feature_array([missing]))
    with pytest.raises(ValueError, match='finite'):
        feature_array([measurements() | {'cpu_busy_fraction': float('nan')}])


def group_fixture():
    labels, groups, episodes = [], [], []
    for c in CLASS_ORDER:
        for family in range(4):
            for repeat in range(2):
                labels.extend([c] * 2)
                groups.extend([f'{c}_family{family}'] * 2)
                episodes.extend([f'{c}_family{family}_r{repeat}'] * 2)
    return Partition(np.zeros((len(labels), len(FEATURE_ORDER))), np.asarray(labels), np.asarray(groups), np.asarray(episodes), [])


def test_group_folds_and_disjoint_calibration():
    data = group_fixture()
    fit, cal, folds = assign_groups(data)
    assert not set(data.groups[fit]) & set(data.groups[cal])
    covered = []
    for tr, va in folds:
        assert not set(data.groups[tr]) & set(data.groups[va])
        assert not set(data.groups[tr]) & set(data.groups[cal])
        assert set(data.y[tr]) == set(data.y[va]) == set(CLASS_ORDER)
        covered.extend(va)
    assert sorted(covered) == np.flatnonzero(fit).tolist()
    assert assign_groups(data)[1].tolist() == cal.tolist()


@pytest.mark.parametrize('defect,expected', [('missing','insufficient-data'), ('schema','insufficient-data'),
    ('order','insufficient-data'), ('units','insufficient-data'), ('incomplete','insufficient-data'),
    ('physical','insufficient-data'), ('old','stale'), ('stopped','stale')])
def test_input_gates(defect, expected):
    w = window()
    if defect == 'missing':
        w['features']['shared_utilization_fraction'] = None
    elif defect == 'schema':
        w['feature_schema_hash'] = 'unsupported'
    elif defect == 'order':
        w['feature_names'] = list(FEATURE_ORDER[::-1])
    elif defect == 'units':
        w['feature_units'] = UNITS | {'rtt_mean_ms': 'seconds'}
    elif defect == 'incomplete':
        w['complete'] = False
    elif defect == 'physical':
        w['features']['ping_loss_fraction'] = 1.1
    elif defect == 'old':
        w['at_utc'] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    output = infer(policy_bundle(), w, TelemetrySettings(), ServiceObjective(), mode='live', live=defect != 'stopped')
    assert output['status'] == expected and output['predicted_class'] is None


def test_recorded_raw_calibrated_order_and_contradictions():
    w = window()
    w['at_utc'] = '2020-01-01T00:00:00+00:00'
    result = infer(policy_bundle(), w, TelemetrySettings(), ServiceObjective(max_loss_fraction=.02))
    assert result['status'] == 'supported' and result['freshness'] == 'historical'
    assert list(result['raw_probabilities']) == list(CLASS_ORDER)
    assert result['calibrated_probabilities'] is None and result['probability_status'] == 'raw_uncalibrated'
    result = infer(policy_bundle(calibrated=(.75,.1,.05,.05,.05)), w, TelemetrySettings(), ServiceObjective())
    assert result['raw_probabilities']['healthy'] == .95 and result['calibrated_probabilities']['healthy'] == .75
    w['features']['udp_loss_fraction'] = .5
    result = infer(policy_bundle(), w, TelemetrySettings(), ServiceObjective(max_loss_fraction=.02))
    assert result['incident'] and result['service_violation'] and result['status'] == 'uncertain'
    assert any('conflicts' in r for r in result['reasons'])
    result = infer(policy_bundle(anomaly=.8), window(), TelemetrySettings(), ServiceObjective())
    assert result['anomalous'] and result['incident'] and result['status'] == 'uncertain'


def test_confidence_margin_ranges_and_missingness_abstention():
    result = infer(policy_bundle(probability=(.3,.3,.2,.1,.1)), window(), TelemetrySettings(), ServiceObjective())
    assert result['status'] == 'uncertain' and any('margin' in r for r in result['reasons'])
    w = window()
    w['features']['rtt_mean_ms'] = 1000
    assert infer(policy_bundle(), w, TelemetrySettings(), ServiceObjective())['unsupported_features']
    w['features']['rtt_mean_ms'] = None
    assert any('missingness' in r for r in infer(policy_bundle(), w, TelemetrySettings(), ServiceObjective())['reasons'])


def fitted_unit_bundle(model_id='munit'):
    rows = [measurements() | {'rtt_mean_ms': float(i + 1)} for i in range(20)]
    X, y = feature_array(rows), np.asarray([c for c in CLASS_ORDER for _ in range(4)])
    base = Pipeline([('preprocessing', MeasurementPreprocessor()),
        ('random_forest', RandomForestClassifier(n_estimators=4, random_state=42))]).fit(X[::2], y[::2])
    cal = CalibratedClassifierCV(FrozenEstimator(base), method='sigmoid', cv=2).fit(X[1::2], y[1::2])
    assert base[0].sample_count_ == len(X[::2])
    pre = MeasurementPreprocessor().fit(X[:4])
    isolation = IsolationForest(n_estimators=4, random_state=42).fit(pre.transform(X[:4]))
    return {'schema_version': 1, 'model_id': model_id, 'classifier': base, 'calibrator': cal,
        'anomaly_preprocessing': pre, 'isolation_forest': isolation, 'anomaly_threshold': .6,
        'policy': DEFAULT_POLICY, 'feature_order': list(FEATURE_ORDER), 'feature_units': UNITS,
        'feature_schema_hash': FEATURE_HASH, 'class_order': list(CLASS_ORDER), 'dependencies': dependency_versions(),
        'dataset': {'unit_fixture': True}, 'seed': 42, 'selected_parameters': {}}, X


def test_trusted_atomic_bundle_roundtrip_immutability(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    repo = BundleRepository(store)
    bundle, X = fitted_unit_bundle()
    assert bundle['calibrator'].estimator.estimator is bundle['classifier']
    assert not np.array_equal(ordered_probabilities(bundle['classifier'], X), ordered_probabilities(bundle['calibrator'], X))
    repo.publish(bundle, {'unit_fixture': True}, X)
    loaded = repo.load('munit')
    assert np.array_equal(ordered_probabilities(bundle['classifier'], X), ordered_probabilities(loaded['classifier'], X))
    with pytest.raises(ValueError, match='immutable'):
        repo.publish(bundle, {'unit_fixture': True}, X)
    second, X = fitted_unit_bundle('munit2')
    repo.publish(second, {'unit_fixture': True}, X)
    assert len(repo.list()) == 2
    with pytest.raises(ValueError, match='unknown trusted'):
        repo.load('muploaded')
    manifest = repo.root / 'munit' / 'manifest.json'
    manifest.chmod(0o600)
    manifest.write_text('{}')
    with pytest.raises(ValueError, match='manifest changed'):
        repo.load('munit')


def test_diagnosis_dedup_stale_view_and_test_seal(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    w = window()
    store.insert_record('runs', w['run_id'], {}, config_hash='unit')
    with store.connection() as db:
        db.execute('INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?)',
            (w['window_id'], w['run_id'], w['instance_id'], 10, 1, 1, json.dumps(w)))
        db.execute('INSERT INTO model_bundles VALUES(?,?,?,?)', ('munit', 'unit', 'unit', '{}'))
    telemetry = SimpleNamespace(settings=TelemetrySettings(), objective=ServiceObjective(), status=lambda _: {'live': True})
    service = DiagnosisService(store, telemetry)
    service.active = policy_bundle()
    first = service.diagnose('munit', w['window_id'], 'live')
    second = service.diagnose('munit', w['window_id'], 'live')
    assert first['diagnosed_utc'] == second['diagnosed_utc'] and second['deduplicated']
    assert len(service.history(w['window_id'])) == 1
    telemetry.status = lambda _: {'live': False}
    assert service.diagnose('munit', w['window_id'], 'live')['status'] == 'stale'
    assert service.diagnose('munit', w['window_id'], 'recorded')['mode'] == 'recorded'
    assert len(service.history(w['window_id'])) == 2
    monkeypatch.setattr(service, '_sealed', lambda _: True)
    with pytest.raises(ValueError, match='sealed'):
        service.diagnose('munit', w['window_id'])


def write_loader_fixture(directory):
    """Only exercises loader boundaries, never passed to quality-training pipeline."""
    schedule = Schedule.model_validate(make_schedule().model_dump()).model_dump()
    splits = {p: {'window_ids': [], 'episode_ids': [], 'family_ids': []} for p in ('train','validation','test')}
    csv_rows, labels, prov = [], [], []
    for i, e in enumerate(schedule['episodes']):
        wid, p = 'w' + str(i), e['partition']
        splits[p]['window_ids'].append(wid)
        splits[p]['episode_ids'].append(e['episode_id'])
        splits[p]['family_ids'].append(e['family_id'])
        # Deliberately nonnumeric test values prove test conversion does not occur.
        csv_rows.append(wid + ',' + ','.join('SEALED' if p == 'test' else str(measurements()[n]) for n in FEATURE_ORDER))
        labels.append({'window_id': wid, 'episode_id': e['episode_id'], 'label': e['scenario']['kind'], 'phase': 'steady'})
        prov.append({'window_id': wid, 'episode_id': e['episode_id'], 'at_utc': '2020-01-01T00:00:00+00:00',
            'data_quality': {'reasons': [], 'warnings': []}, 'start_monotonic_s': 0, 'end_monotonic_s': 10})
    for p in splits.values():
        p['family_ids'] = sorted(set(p['family_ids']))
    (directory / 'features.csv').write_text(','.join(['window_id', *FEATURE_ORDER]) + '\n' + '\n'.join(csv_rows) + '\n')
    for name, rows in [('labels.jsonl', labels), ('provenance.jsonl', prov)]:
        (directory / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (directory / 'episodes.jsonl').write_text('')
    for name, obj in [('splits.json', splits), ('schedule.json', schedule),
        ('quality_report.json', {'structural_checks_passed': True, 'dataset_ready': True, 'shortfalls': {}})]:
        (directory / name).write_text(json.dumps(obj))
    manifest = {'purpose': 'main', 'state': 'completed', 'dataset_ready': True,
        'source': 'Measured Mininet/OVS/Linux tc/iperf emulation; no synthetic rows', 'feature_schema_version': 1,
        'feature_columns': list(FEATURE_ORDER), 'units': DATASET_UNITS, 'schedule_hash': digest(schedule),
        'accepted_windows': 60, 'dataset_version': 'unit_fixture', 'batch_id': 'dunit',
        'files': {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in directory.iterdir()}}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_loader_never_converts_test_and_refuses_unready(tmp_path):
    manifest = write_loader_fixture(tmp_path)
    train, validation, _ = load_measured_dataset(tmp_path)
    assert train.counts()['windows'] == 40 and validation.counts()['windows'] == 10
    assert not set(train.groups) & set(validation.groups)
    assert train.X.shape[1] == len(FEATURE_ORDER)
    manifest['dataset_ready'] = False
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='not ready'):
        load_measured_dataset(tmp_path)


def test_loader_detects_family_partition_overlap_and_order(tmp_path):
    manifest = write_loader_fixture(tmp_path)
    manifest['feature_columns'] = list(FEATURE_ORDER[::-1])
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='schema/order'):
        load_measured_dataset(tmp_path)
    manifest['feature_columns'] = list(FEATURE_ORDER)
    splits = json.loads((tmp_path / 'splits.json').read_text())
    splits['validation']['family_ids'].append(splits['train']['family_ids'][0])
    (tmp_path / 'splits.json').write_text(json.dumps(splits))
    manifest['files']['splits.json']['sha256'] = hashlib.sha256((tmp_path / 'splits.json').read_bytes()).hexdigest()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='partition overlap'):
        load_measured_dataset(tmp_path)


def test_recovery_amendment_preserves_reserved_recipes():
    schedule = make_schedule().model_dump()
    episode = make_schedule().episodes[28]
    batch = {'schedule': schedule, 'schedule_hash': digest(schedule)}
    amendment = {'version': 'coverage_recovery_v1', 'original_schedule_hash': batch['schedule_hash'],
        'measurement_s': 100, 'episodes': {episode.episode_id: {'attempt_limit': 4}}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    before = deepcopy(episode.model_dump())
    limit, effective = recovery_limits(batch, episode)
    assert limit == 4 and effective.scenario.measurement_s == 100
    assert effective.partition == episode.partition and effective.family_id == episode.family_id
    actual = effective.model_dump()
    actual['scenario']['measurement_s'] = before['scenario']['measurement_s']
    assert actual == before and digest(schedule) == batch['schedule_hash']
    amendment['measurement_s'] = 10000
    with pytest.raises(ValueError, match='incompatible'):
        recovery_limits(batch, episode)


def test_brier_is_multiclass_and_empty_bins_remain_null():
    y = np.asarray(CLASS_ORDER)
    result = reliability(y, np.eye(5))
    assert result['multiclass_brier_sum'] == 0 and result['bins'][-1]['count'] == 5
    assert result['bins'][0]['mean_confidence'] is None


def test_duration_tolerance_accepts_float_roundoff_but_not_short_windows():
    assert valid_window_duration({'start_monotonic_s': 16374.336137181,
        'end_monotonic_s': 16384.336137181002})
    assert not valid_window_duration({'start_monotonic_s': 100, 'end_monotonic_s': 109.999})


def test_compact_dataset_status_and_dead_thread_reporting(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    repo = DatasetRepository(store)
    batch = {'batch_id': 'dunit', 'state': 'running', 'schedule_hash': 'unit', 'owner_pid': 1}
    repo.save_batch(batch)
    repo.save_attempt({'attempt_id': 'aunit', 'batch_id': 'dunit', 'episode_id': 'eunit', 'state': 'failed',
        'number': 1, 'error': 'unit failure', 'native_receiver': 'large native payload'})
    service = DatasetService(store, None, None, None)
    compact = service.status('dunit')
    assert 'native_receiver' not in compact['attempts'][0]
    assert service.status('dunit', details=True)['attempts'][0]['native_receiver']
    service.active_id = 'dunit'
    service.thread = SimpleNamespace(is_alive=lambda: False)
    assert service.status('dunit')['batch']['state'] == 'failed'
    assert repo.batch('dunit')['state'] == 'failed'


def test_declared_cadence_keeps_quality_gates_and_reserved_partitions():
    schedule = make_schedule().model_dump()
    batch = {'schedule': schedule, 'schedule_hash': digest(schedule)}
    episode = make_schedule().episodes[28]
    amendment = {'version': 'cadence_recovery_v3', 'original_schedule_hash': batch['schedule_hash'],
        'measurement_s': 100, 'sample_interval_s': 2, 'episodes': {episode.episode_id: {'attempt_limit': 8}}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    original = TelemetrySettings()
    updated = recovery_telemetry(batch, original)
    assert updated.sample_interval_s == 2 and updated.min_coverage_fraction == original.min_coverage_fraction
    assert updated.model_dump(exclude={'sample_interval_s'}) == original.model_dump(exclude={'sample_interval_s'})
    assert recovery_limits(batch, episode)[0] == 8
    amendment['sample_interval_s'] = 10
    with pytest.raises(ValueError, match='incompatible'):
        recovery_telemetry(batch, original)
