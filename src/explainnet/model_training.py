"""Bounded group-separated local training, disjoint sigmoid calibration, validation."""
import importlib.metadata
import platform
import time
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline

from explainnet.model_contracts import CLASS_ORDER, FEATURE_HASH, FEATURE_ORDER, UNITS
from explainnet.model_features import MeasurementPreprocessor
from explainnet.model_policy import DEFAULT_POLICY, infer, ordered_probabilities
from explainnet.telemetry_monitor import evaluate

SEED = 20261007
CANDIDATES = [
    {'max_depth': None, 'min_samples_leaf': 2, 'max_features': 'sqrt'},
    {'max_depth': 8, 'min_samples_leaf': 2, 'max_features': 0.7},
    {'max_depth': None, 'min_samples_leaf': 1, 'max_features': 0.7},
]


def dependency_versions():
    return {'python': platform.python_version(), **{p: importlib.metadata.version(p)
        for p in ('scikit-learn', 'numpy', 'scipy', 'joblib')}}


def classification(y, probabilities):
    predicted = np.asarray(CLASS_ORDER)[np.argmax(probabilities, axis=1)]
    return {'macro_f1': float(f1_score(y, predicted, labels=CLASS_ORDER, average='macro', zero_division=0)),
        'accuracy': float(np.mean(y == predicted)),
        'per_class': classification_report(y, predicted, labels=CLASS_ORDER, output_dict=True, zero_division=0),
        'confusion_matrix': confusion_matrix(y, predicted, labels=CLASS_ORDER).tolist(), 'class_order': list(CLASS_ORDER)}


def reliability(y, probabilities):
    truth = np.asarray([[int(label == c) for c in CLASS_ORDER] for label in y])
    confidence = probabilities.max(axis=1)
    correct = np.asarray(CLASS_ORDER)[probabilities.argmax(axis=1)] == y
    bins = []
    for lo, hi in zip(np.linspace(0, 1, 6)[:-1], np.linspace(0, 1, 6)[1:], strict=True):
        selected = (confidence >= lo) & ((confidence < hi) if hi < 1 else (confidence <= hi))
        bins.append({'lower': float(lo), 'upper': float(hi), 'count': int(selected.sum()),
            'mean_confidence': float(confidence[selected].mean()) if selected.any() else None,
            'accuracy': float(correct[selected].mean()) if selected.any() else None})
    return {'multiclass_brier_sum': float(np.mean(np.sum((probabilities - truth) ** 2, axis=1))),
        'brier_convention': 'Mean sum of squared error over five classes (0..2)', 'bins': bins,
        'expected_calibration_error': float(sum(b['count'] / len(y) * abs(b['mean_confidence'] - b['accuracy'])
            for b in bins if b['count'])), 'samples': len(y)}


def assign_groups(data):
    """One train family per class held for calibration; three remaining families form CV."""
    rng = np.random.default_rng(SEED)
    calibration, folds = [], [[], [], []]
    for label in CLASS_ORDER:
        groups = sorted(set(data.groups[data.y == label]))
        if len(groups) != 4:
            raise ValueError('initial_v1 requires exactly four train families per class')
        groups = list(rng.permutation(groups))
        calibration.append(groups[0])
        for fold, group in zip(folds, groups[1:], strict=True):
            fold.append(group)
    cal = np.isin(data.groups, calibration)
    fit = ~cal
    splits = []
    for groups in folds:
        valid = fit & np.isin(data.groups, groups)
        train = fit & ~valid
        if set(data.y[valid]) != set(CLASS_ORDER) or set(data.y[train]) != set(CLASS_ORDER):
            raise ValueError('CV fold lacks class coverage')
        splits.append((np.flatnonzero(train), np.flatnonzero(valid)))
    return fit, cal, splits


def pipeline(parameters, y, random_seed=SEED):
    counts = Counter(y.tolist())
    weighting = 'balanced' if max(counts.values()) / min(counts.values()) > 1.25 else None
    return Pipeline([('preprocessing', MeasurementPreprocessor()), ('random_forest', RandomForestClassifier(
        n_estimators=160, random_state=random_seed, n_jobs=1, class_weight=weighting, **parameters))])


def detection(y, detected):
    fault = y != 'healthy'
    tp, fp = int((fault & detected).sum()), int((~fault & detected).sum())
    tn, fn = int((~fault & ~detected).sum()), int((fault & ~detected).sum())
    return {'true_positive': tp, 'false_positive': fp, 'true_negative': tn, 'false_negative': fn,
        'detection_fraction': tp / max(1, tp + fn), 'healthy_false_alert_fraction': fp / max(1, fp + tn)}


def train_models(train, validation, hashes, settings, objective, profile='stage7'):
    """Called only after measured loader gate. Unit tests do not invoke quality training."""
    start = time.perf_counter()
    seed = 20261028 if profile == 'completion3' else SEED
    def build(parameters, labels):
        return pipeline(parameters, labels, random_seed=seed) if profile == 'completion3' else pipeline(parameters, labels)
    if profile == 'completion3':
        fit, cal, folds = np.ones(len(train.y), dtype=bool), np.zeros(len(train.y), dtype=bool), []
    else:
        fit, cal, folds = assign_groups(train)
    calibration_data = train
    if profile in {'stage13', 'completion3'}:
        fit = np.ones(len(train.y), dtype=bool)
        calibration_data, cal = validation, np.ones(len(validation.y), dtype=bool)
        groups_by_class = {c: sorted(set(train.groups[train.y == c])) for c in CLASS_ORDER}
        folds = []
        if min(map(len, groups_by_class.values())) < 4:
            raise ValueError('four group-separated folds require at least four training families per class')
        for i in range(4):
            held = np.isin(train.groups,[group for c in CLASS_ORDER for j,group in enumerate(groups_by_class[c]) if j % 4 == i])
            folds.append((np.flatnonzero(~held),np.flatnonzero(held)))
    elif profile != 'stage7':
        raise ValueError('unsupported training profile')
    search, oof_predictions, fitted_candidates = [], [], []
    for parameters in CANDIDATES:
        fold_results, oof = [], np.zeros((len(train.y), len(CLASS_ORDER)))
        for tr, va in folds:
            estimator = build(parameters, train.y[tr]).fit(train.X[tr], train.y[tr])
            probabilities = ordered_probabilities(estimator, train.X[va])
            oof[va] = probabilities
            fold_results.append({'fit_groups': sorted(set(train.groups[tr])), 'validation_groups': sorted(set(train.groups[va])),
                'fit_windows': len(tr), 'validation_windows': len(va), 'preprocessor_fit_windows': estimator[0].sample_count_,
                'metrics': classification(train.y[va], probabilities)})
        search.append({'parameters': parameters, 'folds': fold_results,
            'mean_macro_f1': float(np.mean([f['metrics']['macro_f1'] for f in fold_results]))})
        oof_predictions.append(oof)
        if profile in {'stage13', 'completion3'}:
            fitted = build(parameters,train.y[fit]).fit(train.X[fit],train.y[fit])
            fitted_candidates.append(fitted)
            search[-1]['validation_selection'] = classification(validation.y,ordered_probabilities(fitted,validation.X))
    best = int(np.argmax([candidate['validation_selection']['macro_f1'] if profile in {'stage13','completion3'}
        else candidate['mean_macro_f1'] for candidate in search]))
    classifier = (fitted_candidates[best] if profile in {'stage13','completion3'}
        else build(CANDIDATES[best], train.y[fit]).fit(train.X[fit], train.y[fit]))
    # FrozenEstimator prevents either preprocessing or RF from being fitted on calibration examples.
    calibration_counts = Counter(calibration_data.y[cal].tolist())
    ready = (set(calibration_counts) == set(CLASS_ORDER) and min(calibration_counts.values()) >= 10
        and all(len(set(calibration_data.episodes[cal & (calibration_data.y == c)])) >= 2 for c in CLASS_ORDER))
    calibrator = (CalibratedClassifierCV(FrozenEstimator(classifier), method='sigmoid', n_jobs=1)
        .fit(calibration_data.X[cal], calibration_data.y[cal])) if ready else None
    healthy = train.y == 'healthy'
    anomaly_pre = MeasurementPreprocessor().fit(train.X[healthy])
    isolation = IsolationForest(n_estimators=160, max_samples='auto', contamination='auto',
        random_state=seed, n_jobs=1).fit(anomaly_pre.transform(train.X[healthy]))
    scores = -isolation.score_samples(anomaly_pre.transform(validation.X))
    # Bounded validation tradeoff: maximise detection with <=10% healthy false alerts.
    candidates = sorted(set(np.quantile(scores, np.linspace(0, 1, 21)).tolist() + [float(scores.max() + 1e-9)]))
    tradeoffs = [{'threshold': t, **detection(validation.y, scores >= t)} for t in candidates]
    permitted = [t for t in tradeoffs if t['healthy_false_alert_fraction'] <= 0.10]
    chosen = max(permitted, key=lambda t: (t['detection_fraction'], -t['healthy_false_alert_fraction'], t['threshold']))
    model_id = 'm' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '_' + hashes['manifest_sha256'][:12]
    bundle = {'schema_version': 1, 'model_id': model_id, 'classifier': classifier, 'calibrator': calibrator,
        'anomaly_preprocessing': anomaly_pre, 'isolation_forest': isolation, 'anomaly_threshold': chosen['threshold'],
        'policy': dict(DEFAULT_POLICY), 'feature_order': list(FEATURE_ORDER), 'feature_units': UNITS,
        'feature_schema_hash': FEATURE_HASH, 'class_order': list(CLASS_ORDER), 'dependencies': dependency_versions(),
        'dataset': hashes, 'seed': seed, 'selected_parameters': CANDIDATES[best], 'training_profile':profile}
    if profile == 'completion3':
        from explainnet.service_requirements import VERSION
        bundle['supported_topology_hashes'] = [hashes['topology_hash']]
        bundle['service_contract_version'] = VERSION
        bundle['runtime_dependencies'] = dependency_versions() | {'shap':importlib.metadata.version('shap')}
    raw = ordered_probabilities(classifier, validation.X)
    calibrated = ordered_probabilities(calibrator, validation.X) if calibrator is not None else None
    diagnoses, baseline_predictions = [], []
    for episode in sorted(set(validation.episodes)):
        indices = np.flatnonzero(validation.episodes == episode)
        indices = sorted(indices, key=lambda i: validation.windows[i]['start_monotonic_s'])
        windows = [validation.windows[i] for i in indices]
        baseline = evaluate(windows, settings, objective)
        for i, alert in zip(indices, baseline, strict=True):
            diagnoses.append((i, infer(bundle, validation.windows[i], settings, objective, baseline=alert)))
            baseline_predictions.append((i, alert['status'] == 'alert'))
    diagnoses.sort(key=lambda entry: entry[0])
    results = [entry[1] for entry in diagnoses]
    supported = np.asarray([r['status'] == 'supported' for r in results])
    selected_probs = raw if calibrated is None else calibrated
    runtimes = [r['inference_ms'] for r in results]
    pre = classifier[0]
    report = {'schema_version': 1, 'status': 'trained_and_validated', 'model_id': model_id, 'dataset': hashes,
        'data_coverage': {'train': train.counts(), 'validation': validation.counts(),
            'estimator_fit_windows': int(fit.sum()), 'calibration_windows': int(cal.sum()),
            'estimator_fit_groups': sorted(set(train.groups[fit])), 'calibration_groups': sorted(set(calibration_data.groups[cal])),
            'calibration_episodes': sorted(set(calibration_data.episodes[cal])), 'calibration_partition': 'validation' if profile in {'stage13','completion3'} else 'train',
            'healthy_anomaly_windows': int(healthy.sum()),
            'healthy_anomaly_episodes': len(set(train.episodes[healthy]))},
        'training_profile':profile,
        'selection': {'metric': 'validation raw macro-F1' if profile in {'stage13','completion3'} else 'mean training group-CV macro-F1', 'seed': seed, 'candidates': search,
            'selected_candidate': best, 'class_weight': classifier[-1].class_weight},
        'training_cross_validation': classification(train.y[fit], oof_predictions[best][fit]),
        'validation': {'raw_classifier': classification(validation.y, raw),
            'calibrated_classifier': classification(validation.y, calibrated) if calibrated is not None else None,
            'anomaly': chosen, 'threshold_candidates': tradeoffs, 'threshold_selection': 'validation development tradeoff, not held-out test performance',
            'threshold_baseline': detection(validation.y, np.asarray([p for _, p in sorted(baseline_predictions)])),
            'combined_incident': detection(validation.y, np.asarray([r['incident'] for r in results])),
            'abstention': {'coverage_fraction': float(supported.mean()), 'supported_windows': int(supported.sum()),
                'status_counts': dict(Counter(r['status'] for r in results)),
                'supported_metrics': classification(validation.y[supported], selected_probs[supported]) if supported.any() else None,
                'reason_counts': dict(Counter(reason for r in results for reason in r['reasons']))},
            'inference_runtime_ms': {'mean': float(np.mean(runtimes)), 'p95': float(np.quantile(runtimes, .95)), 'max': max(runtimes)}},
        'calibration': {'ready': ready, 'method': ('sigmoid on validation; all validation scores are development evidence' if profile in {'stage13','completion3'} else 'sigmoid on disjoint train groups') if ready else 'raw uncalibrated: insufficient independent evidence',
            'fit_examples': int(cal.sum()), 'fit_episodes': len(set(calibration_data.episodes[cal])), 'fit_families': len(set(calibration_data.groups[cal])),
            'validation_raw': reliability(validation.y, raw),
            'validation_calibrated': reliability(validation.y, calibrated) if calibrated is not None else None,
            'validation_episodes': len(set(validation.episodes)), 'validation_families': len(set(validation.groups))},
        'preprocessing': {'fit_examples': pre.sample_count_, 'feature_order': list(FEATURE_ORDER), 'units': UNITS,
            'transformed_names': pre.transformed_names_, 'original_mapping': pre.original_mapping_,
            'dropped_all_missing_optional': pre.dropped_names_, 'statistics': pre.statistics_.tolist(),
            'method': 'training-fitted median and missing indicators; all-missing optional columns omitted; no scaling'},
        'policy': bundle['policy'], 'dependencies': bundle['dependencies'], 'training_runtime_s': time.perf_counter() - start,
        'test_partition': 'sealed; not converted to model inputs or used for fitting/tuning/scoring',
        'macro_f1_ambition': 0.85, 'ambition_met_on_validation': classification(validation.y, selected_probs)['macro_f1'] >= .85,
        'limitations': ['Emulator measurements; compact groups and correlated within-episode windows',
            f'Calibration has {min(len(set(calibration_data.groups[cal & (calibration_data.y == c)])) for c in CLASS_ORDER)} families per class; reliability estimates have uncertainty',
            'Anomaly threshold selected on validation: validation is development evidence, Stage 13 test remains sealed',
            'Workload and missing class-counter capabilities can confound fault labels',
            'Training alone does not qualify per-event explanations, twin fidelity or original recovery'],
        'validation_diagnoses': results}
    return bundle, report
