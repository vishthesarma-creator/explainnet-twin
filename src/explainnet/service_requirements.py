"""Versioned critical-service requirements, independent of classifier/fidelity policy.

The bounds inherit the pre-existing recovery_v1 critical-service declaration.
An application objective may tighten these bounds; it cannot relax that class.
No injector state or predicted fault class is an input.
"""
import math

VERSION = 'critical_service_v2'
DECLARED = {'max_rtt_ms': 20, 'max_loss_fraction': .02, 'max_jitter_ms': 5,
    'minimum_delivered_fraction': .9}


def resolve(features, objective=None, reference=None, settings=None):
    objective = objective.model_dump() if hasattr(objective, 'model_dump') else objective or {}
    bounds = dict(DECLARED)
    for key in ('max_rtt_ms', 'max_loss_fraction', 'max_jitter_ms'):
        if objective.get(key) is not None:
            bounds[key] = min(bounds[key], objective[key])
    if reference and reference.get('rtt_p95_ms') is not None:
        bounds['max_rtt_ms'] = min(bounds['max_rtt_ms'], reference['rtt_p95_ms'] + getattr(settings, 'reference_rtt_margin_ms', 15))
    offered = features.get('critical_offered_bps')
    floor = getattr(settings, 'demand_floor_bps', 100000)
    required = offered * bounds['minimum_delivered_fraction'] if offered is not None and offered >= floor else None
    minimum = objective.get('min_goodput_bps')
    if required is not None and minimum is not None and offered >= minimum:
        required = max(required, minimum)
    return {'version': VERSION, 'flow': 'h1->h3', 'rtt_metric': 'rtt_p95_ms', **bounds,
        'required_delivered_bps': required, 'offered_bps': offered,
        'declaration': 'existing recovery_v1 critical class, tightened by explicit application objective/nominal reference',
        'objective': objective, 'reference_window_id': (reference or {}).get('window_id')}


def evaluate(window, objective=None, reference=None, settings=None, recovering=False):
    f = window['features']
    contract = resolve(f, objective, reference, settings)
    fraction = getattr(settings, 'recovery_fraction', .9) if recovering else 1
    limits = [('rtt_p95_ms', contract['max_rtt_ms'] * fraction, 'ms'),
        ('ping_loss_fraction', contract['max_loss_fraction'] * fraction, 'fraction')]
    critical = [k for k in window.get('per_flow', {}) if k.startswith('h1->h3:')]
    udp = 'h1->h3:udp' in critical or not critical  # Absence is unavailable evidence, not a zero-loss TCP assumption.
    if udp:
        limits += [('udp_loss_fraction', contract['max_loss_fraction'] * fraction, 'fraction'),
            ('udp_jitter_ms', contract['max_jitter_ms'] * fraction, 'ms')]
    violations, missing = [], []
    for name, threshold, unit in limits:
        actual = f.get(name)
        if actual is None or not math.isfinite(actual):
            missing.append(name)
        elif actual > threshold:
            violations.append({'rule': name, 'actual': actual, 'threshold': threshold, 'unit': unit, 'affected': contract['flow']})
    required = contract['required_delivered_bps']
    if required is not None and required > 0:
        delivered = f.get('critical_goodput_bps')
        if delivered is None:
            missing.append('critical_goodput_bps')
        elif delivered < required / fraction:
            violations.append({'rule': 'delivered_demand', 'actual': delivered, 'threshold': required / fraction,
                'unit': 'bps', 'affected': contract['flow'], 'offered_demand_bps': contract['offered_bps']})
    return {'contract': contract, 'violations': violations, 'missing': missing,
        'service_violation': bool(violations), 'service_acceptable': not violations and not missing}
