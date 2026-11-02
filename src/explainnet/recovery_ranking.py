"""Auditable dimensionless penalties, hard constraints and descriptive repeats."""
import math
import statistics

from explainnet.recovery_spec import POLICY
from explainnet.service_requirements import evaluate as service_evaluate


def health(window, workload, objective=None):
    f = window['features']
    critical = next(p for p in workload if p['source_host'] == 'h1' and p['target_host'] == 'h3')
    evidence = service_evaluate(window | {'features': f | {'critical_offered_bps': critical['offered_bps']}}, objective)
    service = evidence['contract']
    required = service['required_delivered_bps']
    loss = max(f['ping_loss_fraction'], f['udp_loss_fraction']) if critical['protocol'] == 'udp' else f['ping_loss_fraction']
    values = {'rtt': (f['rtt_p95_ms'], service['max_rtt_ms']), 'loss': (loss, service['max_loss_fraction']),
        'jitter': (f['udp_jitter_ms'] if critical['protocol'] == 'udp' else 0, service['max_jitter_ms'])}
    components = {k: max(0, value / max(limit, 1e-9) - 1) * POLICY['weights'][k]
        for k, (value, limit) in values.items()}
    components['demand'] = (max(0, 1 - f['critical_goodput_bps'] / max(required, 1)) * POLICY['weights']['demand']
        if required is not None else 0)
    return {'components': components, 'penalty': sum(components.values()), 'service_evidence': evidence,
        'normalization': {'required_delivered_bps': required, 'offered_bps': critical['offered_bps'], **service}}


def quality(window, workload):
    reasons = []
    if not any(p['source_host'] == 'h1' and p['target_host'] == 'h3' for p in workload):
        reasons.append('unsupported critical workload endpoints')
    if not window['complete'] or not window['inference_ready']:
        reasons.append('incomplete or unsuitable telemetry window')
    required = ['rtt_mean_ms', 'rtt_p95_ms', 'ping_loss_fraction', 'critical_goodput_bps', 'cpu_busy_fraction', 'memory_used_fraction']
    if any(p['source_host'] == 'h1' and p['target_host'] == 'h3' and p['protocol'] == 'udp' for p in workload):
        required += ['udp_loss_fraction', 'udp_jitter_ms']
    for key in required:
        v = window['features'].get(key)
        if v is None or not math.isfinite(v):
            reasons.append('missing required metric: ' + key)
    for key in ('cpu_busy_fraction', 'memory_used_fraction'):
        if (window['features'].get(key) or 0) > .85:
            reasons.append('shared host resource contamination')
    if window['data_quality']['coverage_fraction'] < .65 or window['data_quality']['transmitted_probes'] < 6:
        reasons.append('insufficient coverage/probe count')
    for p in workload:
        key = f"{p['source_host']}->{p['target_host']}:{p['protocol']}"
        flow = window['per_flow'].get(key, {})
        if (flow.get('duration_s') or 0) / window['duration_s'] < .65 or flow.get('delivered_bps') is None:
            reasons.append('insufficient flow receiver evidence: ' + key)
    return reasons


def score(control, outcome, candidate, workload, objective=None):
    reasons = quality(control, workload) + quality(outcome, workload)
    if reasons:
        return {'eligible': False, 'reasons': reasons, 'score': None}
    baseline, action = health(control, workload, objective), health(outcome, workload, objective)
    if candidate['action']['family'] != 'no_change':
        if any(v > 0 for v in action['components'].values()):
            reasons.append('critical service requirement violated')
        for p in workload:
            if p['source_host'] == 'h1' and p['target_host'] == 'h3':
                continue
            key = f"{p['source_host']}->{p['target_host']}:{p['protocol']}"
            left, right = control['per_flow'][key], outcome['per_flow'][key]
            if right['delivered_bps'] < left['delivered_bps'] * (1 - POLICY['protected_rate_degradation']):
                reasons.append('protected throughput degraded: ' + key)
            if p['protocol'] == 'udp' and (left['loss_fraction'] is None or right['loss_fraction'] is None
                    or right['loss_fraction'] > left['loss_fraction'] + POLICY['protected_loss_increase']):
                reasons.append('protected loss degraded: ' + key)
    improvement = baseline['penalty'] - action['penalty']
    cost = candidate['expected_disruption']
    uncertainty = 0 if candidate['action']['family'] == 'no_change' else POLICY['uncertainty_floor']
    return {'eligible': not reasons, 'reasons': reasons, 'health_no_change': baseline, 'health_action': action,
        'improvement': improvement, 'action_cost_penalty': cost, 'uncertainty_penalty': uncertainty,
        'score': improvement - cost - uncertainty}


def rank(candidates, trials, workload, hypotheses, repetitions, unresolved=False, objective=None):
    rows = []
    for candidate in candidates:
        results = [t for t in trials if t['candidate_id'] == candidate['candidate_id']]
        evaluations = []
        for t in results:
            controls = [b for b in trials if b['hypothesis_id'] == t['hypothesis_id'] and b['repetition'] == t['repetition']
                and b['family'] == 'no_change' and b['state'] == 'measured']
            if t['state'] != 'measured' or not controls:
                evaluations.append({'eligible': False, 'reasons': ['failed/missing trial or matched control'], 'score': None})
            else:
                evaluations.append(score(controls[0]['window'], t['window'], candidate, workload, objective))
        expected = len(hypotheses) * repetitions
        scores = [r['score'] for r in evaluations if r['score'] is not None]
        complete = len(results) == expected and len({(t['hypothesis_id'], t['repetition']) for t in results}) == expected
        valid = complete and all(r['eligible'] for r in evaluations)
        spread = max(scores) - min(scores) if scores else None
        repeat_penalty = (spread or 0) / 2
        # Every matched repeat/hypothesis must exceed the meaningful margin.
        conservative = min(scores) - repeat_penalty if scores else None
        rows.append({'candidate_id': candidate['candidate_id'], 'family': candidate['action']['family'],
            'repeat_count': len(results), 'required_count': expected, 'evaluations': evaluations,
            'score_mean': statistics.mean(scores) if scores else None, 'score_min': min(scores) if scores else None,
            'score_max': max(scores) if scores else None, 'score_spread': spread,
            'repeat_uncertainty_penalty': repeat_penalty, 'conservative_score': conservative,
            'eligible': valid, 'qualifies': valid and candidate['action']['family'] != 'no_change'
                and conservative > POLICY['meaningful_margin'], 'cost': candidate['expected_disruption'],
            'change_count': len(candidate['logical_diff'])})
    qualified = [r for r in rows if r['qualifies']]
    selected = None
    if qualified:
        best = max(r['conservative_score'] for r in qualified)
        tied = [r for r in qualified if best - r['conservative_score'] <= POLICY['practical_tie']]
        selected = min(tied, key=lambda r: (r['cost'], r['change_count'], r['candidate_id']))['candidate_id']
    return {'status': 'uncertain' if selected and unresolved else 'eligible' if selected else 'no-safe-repair',
        'selected_candidate_id': None if unresolved else selected, 'provisional_candidate_id': selected if unresolved else None,
        'rows': rows, 'reasons': ['unresolved reconstruction hypotheses'] if unresolved else [] if selected
            else ['no repair passes every hard constraint and repeat improvement margin'],
        'confidence_intervals': None, 'interpretation': 'Descriptive independent fresh-runtime repetitions, not packet independence'}
