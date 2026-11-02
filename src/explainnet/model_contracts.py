"""Read-only model operations and versioned measurement input schema."""
import hashlib
from typing import Literal

from explainnet.contracts import Identifier, Record
from explainnet.telemetry_contracts import FEATURES

FEATURE_ORDER = tuple(sorted(FEATURES))
FEATURE_HASH = hashlib.sha256(','.join(FEATURE_ORDER).encode()).hexdigest()
CLASS_ORDER = ('healthy', 'saturation', 'loss', 'latency', 'qos')
REQUIRED = frozenset({'ping_loss_fraction', 'shared_utilization_fraction', 'critical_offered_bps',
    'offered_demand_bps', 'active_flow_count', 'primary_path_fraction'})
DATASET_UNITS = {'_ms': 'milliseconds', '_bps': 'bits/second', '_fraction': 'fraction',
    '_pps': 'packets/second', '_bytes': 'bytes', 'active_flow_count': 'count'}
UNITS = {name: next((unit for suffix, unit in DATASET_UNITS.items() if name.endswith(suffix)), 'count')
    for name in FEATURE_ORDER}


class TrainRequest(Record):
    batch_id: Identifier
    profile: Literal['stage7', 'stage13', 'completion3'] = 'stage7'


class BundleRequest(Record):
    model_id: Identifier


class InferenceRequest(BundleRequest):
    window_id: Identifier
    mode: Literal['recorded', 'live'] = 'recorded'
