"""Lightweight requests and versioned explanation semantics (no ML imports)."""
from typing import Literal

from explainnet.contracts import Identifier, Record

SCALE = 'underlying_random_forest_class_probability'
ALGORITHM_VERSION = 'tree_interventional_probability_v1'
BACKGROUND_VERSION = 'train_fit_hash_sample_v1'
ADDITIVITY_TOLERANCE = 1e-6


class ExplanationRequest(Record):
    model_id: Identifier
    window_id: Identifier
    mode: Literal['recorded', 'live'] = 'recorded'
