"""Training-fitted median imputation without scaling; deterministic missing indicators."""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted

from explainnet.model_contracts import FEATURE_ORDER, REQUIRED


def feature_array(rows):
    for row in rows:
        if set(row) != set(FEATURE_ORDER):
            raise ValueError('incompatible feature names; metadata and labels are forbidden')
        for value in row.values():
            if value is not None and (type(value) not in (int, float) or not np.isfinite(value)):
                raise ValueError('feature values must be finite numeric measurements or null')
    return np.asarray([[np.nan if row[name] is None else row[name] for name in FEATURE_ORDER]
        for row in rows], dtype=float)


class MeasurementPreprocessor(TransformerMixin, BaseEstimator):
    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(FEATURE_ORDER) or not len(X):
            raise ValueError('incompatible input feature order or shape')
        if np.isinf(X).any():
            raise ValueError('nonfinite inputs')
        missing = np.isnan(X).all(axis=0)
        required = [i for i, name in enumerate(FEATURE_ORDER) if name in REQUIRED or name == 'critical_goodput_bps']
        if missing[required].any():
            raise ValueError('all-missing required training input')
        self.kept_indices_ = np.flatnonzero(~missing)
        self.dropped_names_ = [FEATURE_ORDER[i] for i in np.flatnonzero(missing)]
        self.statistics_ = np.nanmedian(X[:, self.kept_indices_], axis=0)
        self.sample_count_ = len(X)
        self.n_features_in_ = X.shape[1]
        self.training_missing_fraction_ = np.isnan(X).mean(axis=0)
        self.minimum_ = np.nanmin(X[:, self.kept_indices_], axis=0)
        self.maximum_ = np.nanmax(X[:, self.kept_indices_], axis=0)
        self.feature_names_ = [FEATURE_ORDER[i] for i in self.kept_indices_]
        self.transformed_names_ = self.feature_names_ + [name + '__missing' for name in self.feature_names_]
        self.original_mapping_ = self.feature_names_ * 2
        return self

    def transform(self, X):
        check_is_fitted(self, 'statistics_')
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != self.n_features_in_ or np.isinf(X).any():
            raise ValueError('incompatible input shape or nonfinite values')
        values = X[:, self.kept_indices_]
        missing = np.isnan(values)
        return np.concatenate([np.where(missing, self.statistics_, values), missing.astype(float)], axis=1)

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, 'statistics_')
        if input_features is not None and tuple(input_features) != FEATURE_ORDER:
            raise ValueError('incompatible feature order')
        return np.asarray(self.transformed_names_, dtype=object)
