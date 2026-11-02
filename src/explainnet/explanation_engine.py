"""Lazy SHAP runtime: frozen RF preprocessing, train-only background, checked scale."""
import hashlib
import time

from explainnet.dataset_contracts import digest
from explainnet.explanation_contracts import ADDITIVITY_TOLERANCE, BACKGROUND_VERSION, SCALE
from explainnet.model_contracts import CLASS_ORDER, FEATURE_ORDER, UNITS


def build_background(bundle, train, hashes, fit_groups, limit=24):
    import numpy as np
    if hashes != bundle['dataset']:
        raise ValueError('background dataset differs from immutable trained dataset')
    if not fit_groups or not set(fit_groups) <= set(train.groups):
        raise ValueError('background requires verified estimator-fit training groups')
    candidates = [i for i, g in enumerate(train.groups) if g in fit_groups]
    indices = sorted(candidates, key=lambda i: hashlib.sha256(
        f"{bundle['seed']}:{train.windows[i]['window_id']}".encode()).hexdigest())[:limit]
    if not indices or limit < 1:
        raise ValueError('empty background')
    pre = bundle['classifier'].named_steps['preprocessing']
    matrix = pre.transform(train.X[indices])
    if not np.isfinite(matrix).all():
        raise ValueError('nonfinite transformed background')
    payload = {'version': BACKGROUND_VERSION, 'model_id': bundle['model_id'], 'dataset': hashes,
        'partition': 'train', 'scope': 'estimator-fit groups; calibration/validation/test excluded',
        'selection': 'ascending SHA256(seed:window_id), without replacement', 'seed': bundle['seed'], 'limit': limit,
        'window_ids': [train.windows[i]['window_id'] for i in indices],
        'groups': [str(train.groups[i]) for i in indices], 'episodes': [str(train.episodes[i]) for i in indices],
        'transformed_names': list(pre.transformed_names_), 'original_mapping': list(pre.original_mapping_),
        'matrix': matrix.tolist()}
    payload['content_hash'] = digest(payload)
    return payload


def normalize_multiclass(values, expected, n_features, n_classes):
    import numpy as np
    # SHAP >=0.45 returns (samples, features, outputs); older releases used
    # one (samples,features) array per class. Reject ambiguous dimensions.
    if isinstance(values, list):
        values = np.stack(values, axis=-1)
    values, expected = np.asarray(values), np.asarray(expected)
    if values.shape != (1, n_features, n_classes) or expected.shape != (n_classes,):
        raise ValueError(f'unsupported multiclass SHAP shape {values.shape}/{expected.shape}')
    if not np.isfinite(values).all() or not np.isfinite(expected).all():
        raise ValueError('nonfinite SHAP values')
    return values[0], expected


class RFExplainer:
    def __init__(self, bundle, background):
        import numpy as np
        import shap
        from sklearn.ensemble import RandomForestClassifier
        self.bundle, self.background = bundle, background
        self.pre = bundle['classifier'].named_steps['preprocessing']
        self.rf = bundle['classifier'].named_steps['random_forest']
        if not isinstance(self.rf, RandomForestClassifier) or set(self.rf.classes_) != set(CLASS_ORDER):
            raise ValueError('unsupported underlying classifier/class map')
        if background['content_hash'] != digest({k: v for k, v in background.items() if k != 'content_hash'}):
            raise ValueError('background contents changed')
        if (background['model_id'] != bundle['model_id'] or background['partition'] != 'train'
                or background['transformed_names'] != list(self.pre.transformed_names_)
                or background['original_mapping'] != list(self.pre.original_mapping_)):
            raise ValueError('background preprocessing mapping mismatch')
        self.native_classes = self.rf.classes_.tolist()
        self.shap_version = shap.__version__
        self.explainer = shap.TreeExplainer(self.rf, data=np.asarray(background['matrix'], dtype=float),
            feature_perturbation='interventional', model_output='probability', feature_names=self.pre.transformed_names_)

    def explain(self, window, diagnosis):
        from explainnet.model_features import feature_array
        start = time.perf_counter()
        chosen = diagnosis.get('predicted_class')
        if diagnosis['model_id'] != self.bundle['model_id']:
            raise ValueError('diagnosis model differs from explainer model')
        if chosen not in self.native_classes:
            raise ValueError('diagnosis has no explainable selected class')
        transformed = self.pre.transform(feature_array([window['features']]))
        values = self.explainer.shap_values(transformed, check_additivity=True)
        values, base = normalize_multiclass(values, self.explainer.expected_value, transformed.shape[1], len(self.native_classes))
        index = self.native_classes.index(chosen)
        output = float(self.rf.predict_proba(transformed)[0, index])
        saved_raw = diagnosis.get('raw_probabilities')
        if saved_raw is not None and abs(saved_raw[chosen] - output) > 1e-9:
            raise ValueError('underlying RF output differs from persisted diagnosis')
        reconstructed = float(base[index] + values[:, index].sum())
        error = abs(output - reconstructed)
        if error > ADDITIVITY_TOLERANCE:
            raise ValueError(f'SHAP additivity failed: {error}')
        contributions = []
        for j, (name, original) in enumerate(zip(self.pre.transformed_names_, self.pre.original_mapping_, strict=True)):
            indicator = name.endswith('__missing')
            measured = window['features'][original]
            value = float(values[j, index])
            contributions.append({'transformed_feature': name, 'original_feature': original, 'contribution': value,
                'direction': 'supporting' if value > 0 else 'opposing' if value < 0 else 'neutral',
                'original_measured_value': measured, 'unit': UNITS[original], 'transformed_value': float(transformed[0, j]),
                'transformed_unit': 'missing indicator (0/1)' if indicator else UNITS[original],
                'is_missing_indicator': indicator, 'was_missing': measured is None,
                'preprocessing': 'missingness flag; not a network measurement' if indicator else 'training median imputation' if measured is None else 'unchanged measurement; no scaling',
                'training_median': float(self.pre.statistics_[self.pre.feature_names_.index(original)])})
        top = sorted((c for c in contributions if c['contribution'] != 0), key=lambda c: (-abs(c['contribution']), c['transformed_feature']))[:3]
        return {'status': 'ready', 'explained_class': chosen, 'output_scale': SCALE, 'base_value': float(base[index]),
            'underlying_model_output': output, 'reconstructed_output': reconstructed, 'additivity_absolute_error': error,
            'additivity_tolerance': ADDITIVITY_TOLERANCE, 'contributions': contributions, 'top_features': top,
            'class_index': index, 'native_class_order': self.native_classes, 'diagnosis_class_order': list(CLASS_ORDER),
            'calibrated_probabilities': diagnosis.get('calibrated_probabilities'), 'diagnosis_confidence': diagnosis.get('confidence'),
            'probability_status': diagnosis.get('probability_status'), 'diagnosis_status': diagnosis['status'],
            'diagnosis_reasons': diagnosis.get('reasons', []), 'background_version': self.background['content_hash'],
            'observation_utc': window['at_utc'], 'diagnosis_freshness': diagnosis.get('freshness'),
            'background_provenance': {k: v for k, v in self.background.items() if k != 'matrix'},
            'transformed_names': list(self.pre.transformed_names_), 'original_mapping': list(self.pre.original_mapping_),
            'original_measurements': {name: {'value': window['features'][name], 'unit': UNITS[name],
                'transformed_columns': [column for column, original in zip(self.pre.transformed_names_, self.pre.original_mapping_, strict=True) if original == name],
                'dropped_all_missing_during_fit': name in self.pre.dropped_names_} for name in FEATURE_ORDER},
            'dropped_all_missing_optional': list(self.pre.dropped_names_), 'shap_version': self.shap_version,
            'runtime_ms': (time.perf_counter() - start) * 1000,
            'interpretation': 'Signed change in raw RF class probability relative to the train background; not calibrated confidence or physical causality'}


def plain_language(result, diagnosis, localization):
    cause = diagnosis.get('predicted_class') or 'unavailable'
    wording = f"Probable class: {cause}; diagnosis {diagnosis['status']}."
    for feature in result.get('top_features', []):
        name = feature['original_feature']
        observation = (f"{name} missingness flag={feature['transformed_value']:g} (not a network measurement)"
            if feature['is_missing_indicator'] else f"{name}={feature['original_measured_value']} {feature['unit']}"
            if not feature['was_missing'] else f"{name} unavailable; training median={feature['training_median']:g} {feature['unit']}")
        wording += f" {observation} {feature['direction']} the raw RF class output ({feature['contribution']:+.4f})."
    path = localization['path']
    observed = localization['end_to_end_observations']
    wording += ' Observed service evidence: ' + ', '.join(
        f"{name}={observed[name]} {UNITS[name]}" if observed[name] is not None else f'{name} unavailable'
        for name in ('rtt_p95_ms', 'ping_loss_fraction', 'critical_goodput_bps')) + '.'
    wording += f" Affected service: {path['flow']}; observed path {path['path_name'] or 'unavailable'}."
    calibrated = diagnosis.get('calibrated_probabilities')
    if calibrated is not None and cause in calibrated:
        wording += f" Separate calibrated probability for {cause}: {calibrated[cause]:.3f}."
    else:
        wording += ' Calibrated confidence unavailable.'
    wording += f" Localization {localization['status']}; candidates {', '.join(localization['candidate_set']) or 'unavailable'}."
    if diagnosis.get('reasons'):
        wording += ' Qualifications: ' + '; '.join(diagnosis['reasons']) + '.'
    return wording + ' Contributions describe prediction influence, not a physical cause or a repair guarantee.'
