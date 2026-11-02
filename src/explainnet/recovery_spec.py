"""Stage 10 logical policy and feasibility; stdlib only, shared with root guard."""
from itertools import pairwise
from typing import Literal, TypedDict

from explainnet.service_requirements import DECLARED, VERSION
from explainnet.topology.spec import fields, host_routes, number, validate_definition
from explainnet.twin_spec import digest, validate_snapshot

# Declared laboratory service policy, independent of experimental truth. Changing
# these values requires a new version on both sides of the privilege boundary.
POLICY = {
    'version': 'recovery_v2', 'service_contract_version': VERSION, 'permitted_pairs': ['critical', 'bulk'],
    'families': ['no_change', 'reroute', 'shape_background', 'restore_qos'],
    'background_endpoints': ['h5', 'h6'], 'background_limit_bps': 80_000_000,
    'approved_qos': {'direction': 's3->s5', 'critical_rate_bps': 3_000_000,
        'critical_ceil_bps': 4_000_000, 'bulk_rate_bps': 16_000_000, 'bulk_ceil_bps': 20_000_000,
        'source_host': 'h1', 'target_host': 'h3'},
    'service': dict(DECLARED),
    'weights': {'rtt': 1, 'loss': 1, 'jitter': .25, 'demand': 1},
    'costs': {'no_change': 0, 'reroute': .02, 'shape_background': .08, 'restore_qos': .04},
    'meaningful_margin': .05, 'practical_tie': .03, 'uncertainty_floor': .02,
    'protected_rate_degradation': .15, 'protected_loss_increase': .03,
    'max_repairs': 3, 'max_repetitions': 3, 'max_hypotheses': 2,
    'max_duration_s': 20, 'max_job_s': 700,
}
POLICY_HASH = digest(POLICY)


class RerouteChange(TypedDict):
    pair_id: str
    from_path: str
    to_path: str


class BackgroundChange(TypedDict):
    source_host: str
    target_host: str
    limit_bps: int


class QoSChange(TypedDict):
    direction: str
    critical_rate_bps: int
    critical_ceil_bps: int
    bulk_rate_bps: int
    bulk_ceil_bps: int
    source_host: str
    target_host: str


class NoChange(TypedDict):
    family: Literal['no_change']
    changes: list[None]
    policy_hash: str


class Reroute(TypedDict):
    family: Literal['reroute']
    changes: list[RerouteChange]
    policy_hash: str


class ShapeBackground(TypedDict):
    family: Literal['shape_background']
    changes: list[BackgroundChange]
    policy_hash: str


class RestoreQoS(TypedDict):
    family: Literal['restore_qos']
    changes: list[QoSChange]
    policy_hash: str


RecoveryAction = NoChange | Reroute | ShapeBackground | RestoreQoS


def validate_action(action: RecoveryAction):
    fields(action, ['family', 'changes', 'policy_hash'])
    if action['policy_hash'] != POLICY_HASH or action['family'] not in POLICY['families']:
        raise ValueError('unapproved recovery policy/action family')
    changes = action['changes']
    if not isinstance(changes, list) or len(changes) > 2:
        raise ValueError('bounded exact logical changes required')
    if action['family'] == 'no_change':
        if changes:
            raise ValueError('no-change has no configuration changes')
    elif action['family'] == 'reroute':
        if not changes:
            raise ValueError('reroute requires a permitted pair')
        for c in changes:
            fields(c, ['pair_id', 'from_path', 'to_path'])
            if c['pair_id'] not in POLICY['permitted_pairs']:
                raise ValueError('forbidden forwarding endpoints')
        if len({c['pair_id'] for c in changes}) != len(changes):
            raise ValueError('duplicate forwarding target')
    elif action['family'] == 'shape_background':
        if changes != [{'source_host': 'h5', 'target_host': 'h6', 'limit_bps': POLICY['background_limit_bps']}]:
            raise ValueError('unapproved background shaping change')
    elif changes != [POLICY['approved_qos']]:
        raise ValueError('QoS must restore the declared approved policy')
    return action


def feasibility(snapshot, action):
    validate_snapshot(snapshot)
    validate_action(action)
    definition = validate_definition(snapshot['definition'])
    selected = dict(snapshot['selected_paths'])
    pairs = {p['pair_id']: p for p in definition['pairs']}
    if action['family'] == 'reroute':
        for c in action['changes']:
            p = pairs.get(c['pair_id'])
            if not p or c['from_path'] != selected[c['pair_id']] or c['to_path'] not in p['paths']:
                raise ValueError('missing path or forwarding precondition mismatch')
            endpoints = {'critical': ('h1', 'h3'), 'bulk': ('h2', 'h4')}[c['pair_id']]
            if (p['source_host'], p['target_host']) != endpoints:
                raise ValueError('forbidden logical pair endpoints')
            if not any({w['source_host'], w['target_host']} == {p['source_host'], p['target_host']}
                    for w in snapshot['workload']):
                raise ValueError('forwarding target has no observed affected workload; no-op')
            if p['paths'][c['from_path']] == p['paths'][c['to_path']]:
                raise ValueError('equivalent/no-op path')
            selected[c['pair_id']] = c['to_path']
    elif action['family'] == 'shape_background':
        access = next((h['access_bps'] for h in definition['hosts'] if h['host_id'] == 'h5'), None)
        if access is None or POLICY['background_limit_bps'] > access:
            raise ValueError('background shaping exceeds physical access capacity')
        if any(w['source_host'] == 'h5' and w['target_host'] != 'h6' for w in snapshot['workload']):
            raise ValueError('source access shaping would affect another endpoint; unavailable selective capability')
        if not any(p['source_host'] == 'h5' and p['target_host'] == 'h6'
                and p['offered_bps'] > POLICY['background_limit_bps'] for p in snapshot['workload']):
            raise ValueError('no eligible background demand; no-op shaping')
    elif action['family'] == 'restore_qos':
        q = snapshot['queue_configuration'].get('s3->s5', {})
        children = {c['handle']: c for c in q.get('child_classes', [])}
        if set(children) != {'5:10', '5:20'}:
            raise ValueError('unsupported QoS hierarchy; no approved restoration capability')
        mapping = q.get('flow_mapping', [])
        if (len(mapping) != 2 or not any(m['source_host'] == 'h1' and m['target_host'] == 'h3'
                and m['classid'] == '5:10' and not m['default'] for m in mapping)
                or not any(m['default'] and m['classid'] == '5:20' for m in mapping)):
            raise ValueError('unsupported QoS mapping; approved restoration changes existing service classes only')
        if (children['5:10']['rate_bps'] == 3_000_000 and children['5:10']['ceil_bps'] == 4_000_000
                and children['5:20']['rate_bps'] == 16_000_000 and children['5:20']['ceil_bps'] == 20_000_000):
            raise ValueError('already approved QoS; no-op')
        link = next(l for l in definition['links'] if {l['source'], l['target']} == {'s3', 's5'})
        cap = link['forward_bps'] if link['source'] == 's3' else link['reverse_bps']
        if cap != 20_000_000 or 3_000_000 + 16_000_000 > cap:
            raise ValueError('guaranteed scheduling allocation exceeds physical capacity')
    routes = host_routes(definition, selected)
    loads = {}
    capacities = {l[a] + '->' + l[b]: l[prefix + '_bps'] for l in definition['links']
        for a, b, prefix in [('source', 'target', 'forward'), ('target', 'source', 'reverse')]}
    # Offered demand is not a guaranteed allocation on a congested source path.
    # Refuse new overload introduced by forwarding; existing congestion may be
    # retained for controls and shaping experiments.
    def demand(paths):
        result = {}
        for w in snapshot['workload']:
            route = next(r for r in paths if {r['source_host'], r['target_host']} == {w['source_host'], w['target_host']})
            switches = route['switches'] if route['source_host'] == w['source_host'] else list(reversed(route['switches']))
            rate = w['offered_bps']
            if action['family'] == 'shape_background' and w['source_host'] == 'h5' and w['target_host'] == 'h6':
                rate = min(rate, POLICY['background_limit_bps'])
            for a, b in pairwise(switches):
                result[a + '->' + b] = result.get(a + '->' + b, 0) + rate
        return result
    original_loads = demand(host_routes(definition, snapshot['selected_paths']))
    loads = demand(routes)
    for direction, load in loads.items():
        cap = capacities[direction]
        number(cap, 1000, 100_000_000)
        if load > cap and load > original_loads.get(direction, 0):
            raise ValueError('candidate introduces demand exceeding physical capacity: ' + direction)
    return {'selected_paths': selected, 'offered_load_bps': loads, 'physical_capacities_bps': {
        direction: cap for direction, cap in capacities.items()}, 'physical_capacity_increased': False}


def generate(snapshot, max_repairs=3):
    validate_snapshot(snapshot)
    proposed = [{'family': 'no_change', 'changes': [], 'policy_hash': POLICY_HASH}]
    pairs = {p['pair_id']: p for p in snapshot['definition']['pairs']}
    reroutes = {}
    for pair_id in POLICY['permitted_pairs']:
        p = pairs.get(pair_id)
        if p:
            current = snapshot['selected_paths'][pair_id]
            alternatives = sorted(k for k, path in p['paths'].items() if path != p['paths'][current])
            if alternatives:
                reroutes[pair_id] = {'pair_id': pair_id, 'from_path': current, 'to_path': alternatives[0]}
    for changes in ([reroutes['critical']] if 'critical' in reroutes else [],):
        if changes:
            proposed.append({'family': 'reroute', 'changes': changes, 'policy_hash': POLICY_HASH})
    if len(reroutes) > 1:
        proposed.append({'family': 'reroute', 'changes': list(reroutes.values()), 'policy_hash': POLICY_HASH})
    proposed += [{'family': 'shape_background', 'changes': [{'source_host': 'h5', 'target_host': 'h6',
        'limit_bps': POLICY['background_limit_bps']}], 'policy_hash': POLICY_HASH},
        {'family': 'restore_qos', 'changes': [POLICY['approved_qos']], 'policy_hash': POLICY_HASH}]
    if 'bulk' in reroutes:
        proposed.append({'family': 'reroute', 'changes': [reroutes['bulk']], 'policy_hash': POLICY_HASH})
    accepted, rejected, seen = [], [], set()
    for a in proposed:
        try:
            proof = feasibility(snapshot, a)
            key = digest(a | {'changes': sorted(a['changes'], key=lambda c: digest(c))})
            if key in seen:
                raise ValueError('duplicate/equivalent action')
            seen.add(key)
            if len(accepted) >= max_repairs + 1:
                raise ValueError('bounded candidate budget exhausted')
            accepted.append({'candidate_id': 'c' + key[:20], 'action': a, 'logical_diff': a['changes'],
                'feasibility': proof, 'policy_version': POLICY['version'],
                'expected_disruption': POLICY['costs'][a['family']] * max(1, len(a['changes'])),
                'prerequisites': {'snapshot_hash': snapshot['snapshot_hash'], 'source_fingerprint': snapshot['source_fingerprint'],
                    'selected_paths': snapshot['selected_paths'], 'verified_twin_only': True},
                'evidence': {'localization': snapshot['localization'], 'diagnosis': snapshot['diagnosis'],
                    'interpretation': 'Observed path alternatives, not SHAP causality or injector state'}})
        except ValueError as exc:
            rejected.append({'action': a, 'reason': str(exc)})
    return {'candidates': accepted, 'rejected': rejected, 'policy': POLICY, 'policy_hash': POLICY_HASH,
        'feasible_repair_count': len(accepted) - 1}
