"""Read-only diagnosis policy. Scores, probabilities and service evidence stay distinct."""
import time
from datetime import UTC, datetime

import numpy as np

from explainnet.model_contracts import CLASS_ORDER, FEATURE_HASH, FEATURE_ORDER, REQUIRED, UNITS
from explainnet.model_features import feature_array
from explainnet.service_requirements import evaluate as service_evaluate

DEFAULT_POLICY = {'min_confidence': 0.70, 'min_margin': 0.15, 'range_span_multiplier': 0.5,
    'range_relative_floor': 0.25, 'selection': 'Conservative predeclared thresholds; no test-set tuning'}


def ordered_probabilities(estimator, X):
    values = estimator.predict_proba(X)
    if set(estimator.classes_) != set(CLASS_ORDER):
        raise ValueError('incompatible classifier classes')
    return values[:, [list(estimator.classes_).index(c) for c in CLASS_ORDER]]


def infer(bundle, window, settings, objective, *, mode='recorded', live=False, baseline=None, now=None):
    started = time.perf_counter()
    now = now or datetime.now(UTC)
    output = {'schema_version': 1, 'window_id': window['window_id'], 'model_id': bundle['model_id'], 'mode': mode,
        'observation_utc': window.get('at_utc'), 'diagnosed_utc': now.isoformat(), 'status': 'insufficient-data',
        'reasons': [], 'predicted_class': None, 'raw_probabilities': None, 'calibrated_probabilities': None,
        'probability_status': 'calibrated' if bundle['calibrator'] is not None else 'raw_uncalibrated',
        'class_order': list(CLASS_ORDER), 'anomaly_score': None, 'anomaly_threshold': bundle['anomaly_threshold'],
        'anomalous': None, 'anomaly_score_direction': 'larger is more anomalous; negative score_samples; not probability',
        'service_violations': [], 'service_violation': False, 'baseline_alert': bool(baseline and baseline.get('alert_latched')),
        'incident': bool(baseline and baseline.get('alert_latched')), 'confidence': None, 'margin': None,
        'freshness': 'historical' if mode == 'recorded' else 'unknown', 'unsupported_features': [],
        'limitations': ['Range checks are limited heuristics; unknown faults are not guaranteed to be detected']}

    def finish(status, reasons):
        output.update(status=status, reasons=reasons, inference_ms=(time.perf_counter() - started) * 1000,
            diagnosed_monotonic_s=time.monotonic())
        return output

    if mode not in {'recorded', 'live'}:
        raise ValueError('unknown inference mode')
    if (window.get('feature_schema_version') != 1 or window.get('feature_schema_hash') != FEATURE_HASH
            or window.get('feature_names', list(FEATURE_ORDER)) != list(FEATURE_ORDER)
            or window.get('feature_units', UNITS) != UNITS):
        return finish('insufficient-data', ['incompatible feature schema, order or units'])
    try:
        X = feature_array([window['features']])
    except (ValueError, KeyError) as exc:
        return finish('insufficient-data', [str(exc)])
    f = window['features']
    required = REQUIRED | ({'critical_goodput_bps'} if (f['critical_offered_bps'] or 0) >= settings.demand_floor_bps else set())
    missing = sorted(name for name in required if f[name] is None)
    invalid = sorted(name for name, value in f.items() if value is not None and
        (value < 0 or (name.endswith('_fraction') and value > 1)))
    if invalid:
        return finish('insufficient-data', ['invalid physical feature values: ' + ', '.join(invalid)])
    output['service_evidence'] = service_evaluate(window, objective, settings=settings)
    output['service_contract_version'] = output['service_evidence']['contract']['version']
    output['service_violations'] = output['service_evidence']['violations']
    output['service_violation'] = bool(output['service_violations'])
    output['incident'] |= output['service_violation']
    if missing or not window.get('complete') or not window.get('inference_ready'):
        return finish('insufficient-data', ['missing required inputs: ' + ', '.join(missing)] if missing else
            ['window is incomplete or failed quality gates', *window.get('data_quality', {}).get('reasons', [])])
    if mode == 'live':
        try:
            observed = datetime.fromisoformat(window['at_utc'])
            if observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
                raise ValueError('observation time must be UTC')
            age = (now - observed).total_seconds()
        except (KeyError, ValueError, TypeError):
            return finish('stale', ['invalid observation time'])
        output['observation_age_s'] = age
        if not live or age > settings.stale_after_s or age < -1:
            output['freshness'] = 'stale'
            return finish('stale', ['collector unavailable, stopped, or completed observation too old'])
        output['freshness'] = 'fresh'
    pre = bundle['classifier'].named_steps['preprocessing']
    policy, unsupported = bundle['policy'], []
    if (bundle.get('supported_topology_hashes') and
            window.get('context',{}).get('config_hash') not in bundle['supported_topology_hashes']):
        unsupported.append('topology: outside declared trained domain or topology identity unavailable')
    for j, i in enumerate(pre.kept_indices_):
        value, name = X[0, i], FEATURE_ORDER[i]
        if np.isnan(value):
            if pre.training_missing_fraction_[i] == 0:
                unsupported.append(name + ': missingness not observed during fit')
            continue
        floor = 0.10 if name.endswith('_fraction') else 5.0 if name.endswith('_ms') else 1.0
        tolerance = max((pre.maximum_[j] - pre.minimum_[j]) * policy['range_span_multiplier'],
                        abs(pre.maximum_[j]) * policy['range_relative_floor'], floor)
        if value < pre.minimum_[j] - tolerance or value > pre.maximum_[j] + tolerance:
            unsupported.append(name + ': substantially outside training range')
    for name in pre.dropped_names_:
        if f[name] is not None:
            unsupported.append(name + ': capability unsupported during fit')
    raw = ordered_probabilities(bundle['classifier'], X)[0]
    cal = ordered_probabilities(bundle['calibrator'], X)[0] if bundle['calibrator'] is not None else None
    chosen = raw if cal is None else cal
    index = int(np.argmax(chosen))
    confidence, margin = float(chosen[index]), float(np.sort(chosen)[-1] - np.sort(chosen)[-2])
    score = float(-bundle['isolation_forest'].score_samples(bundle['anomaly_preprocessing'].transform(X))[0])
    output.update(raw_probabilities=dict(zip(CLASS_ORDER, raw.tolist(), strict=True)),
        calibrated_probabilities=None if cal is None else dict(zip(CLASS_ORDER, cal.tolist(), strict=True)),
        predicted_class=CLASS_ORDER[index], confidence=confidence, margin=margin, anomaly_score=score,
        anomalous=score >= bundle['anomaly_threshold'], unsupported_features=unsupported)
    reasons = list(unsupported)
    if confidence < policy['min_confidence']:
        reasons.append('classifier confidence below policy threshold')
    if margin < policy['min_margin']:
        reasons.append('classifier margin below policy threshold')
    healthy = CLASS_ORDER[index] == 'healthy'
    if healthy and (output['incident'] or output['anomalous']):
        reasons.append('healthy classifier conflicts with anomaly or service incident')
    if not healthy and not (output['service_violation'] or output['baseline_alert'] or output['anomalous']):
        reasons.append('fault classifier lacks corroborating anomaly or service evidence')
    output['incident'] |= output['anomalous'] or not healthy
    return finish('uncertain' if reasons else 'supported', reasons)
