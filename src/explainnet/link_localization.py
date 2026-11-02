"""Observed link evidence only. Scores are heuristics, never probabilities or SHAP."""
import json
import math
from itertools import pairwise

from explainnet.telemetry_math import configuration_key
from explainnet.telemetry_storage import reject_ground_truth


def observed_samples(store, window):
    """Fetch only this window's indexed source IDs; decode after releasing the DB lock."""
    ids = window.get('sample_ids', [])
    if not ids:
        return []
    with store.connection() as db:
        rows = db.execute('SELECT payload_json FROM telemetry_samples WHERE run_id=? '
            'AND source=\'network_agent\' AND sample_id IN (' + ','.join('?' for _ in ids) + ')',
            (window['run_id'], *ids)).fetchall()
    return [json.loads(row[0]) for row in rows]


def affected_path(window, definition):
    """Stage 5 service objectives/probes concern the configured critical pair."""
    if hasattr(definition, 'model_dump'):
        definition = definition.model_dump(mode='json')
    pairs = (definition or {}).get('pairs', [])
    pair = next((p for p in pairs if p['pair_id'] == 'critical'), None)
    selected = window.get('context', {}).get('selected_paths', {}).get('critical')
    if pair is None or selected not in pair['paths']:
        return {'flow': 'h1->h3', 'path_name': selected, 'switches': [], 'directions': [],
            'limitation': 'observed critical path unavailable; no default path assumed'}
    switches = pair['paths'][selected]
    # Loss/RTT probes traverse both directions. One-way receiver observations alone
    # cannot exclude a reverse-path impairment affecting the control/probe traffic.
    forward = [f'{a}->{b}' for a, b in pairwise(switches)]
    return {'flow': f"{pair['source_host']}->{pair['target_host']}", 'path_name': selected,
        'switches': switches, 'directions': forward + [f'{b}->{a}' for a, b in pairwise(switches)]}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def localize(window, definition, samples=()):
    reject_ground_truth(window)
    path = affected_path(window, definition)
    # Explicit source/type/time/identity/configuration gates, even for indexed raw samples.
    points = []
    for sample in samples:
        reject_ground_truth(sample)
        if (sample.get('source') == 'network_agent' and sample.get('run_id') == window['run_id']
                and window['start_monotonic_s'] <= sample.get('monotonic_s', -1) <= window['end_monotonic_s']):
            points.append(sample)
    points.sort(key=lambda p: p['monotonic_s'])
    ranked = []
    for direction in path['directions']:
        observations, score = [], 0
        totals = window.get('directional', {}).get(direction, {})
        dt = totals.get('duration_s', 0)
        weighted = totals.get('weighted_utilization')
        utilization = weighted / dt if finite(weighted) and finite(dt) and dt > 0 and not totals.get('invalid_intervals') else None
        if utilization is not None:
            observations.append({'measurement': 'utilization', 'value': utilization, 'unit': 'fraction',
                'source': 'valid directional counter intervals', 'threshold': .9})
            score += 2 if utilization > .9 else 0
        drop_rates, backlogs, class_rates = [], [], []
        for old, new in pairwise(points):
            if configuration_key(old) != configuration_key(new):
                continue
            a, b = old.get('links', {}).get(direction), new.get('links', {}).get(direction)
            elapsed = new['monotonic_s'] - old['monotonic_s']
            if not a or not b or not b.get('identity') or a.get('identity') != b['identity'] or not 0 < elapsed <= 5:
                continue
            interval_drops = []
            for handle, queue in b.get('queues', {}).items():
                before = a.get('queues', {}).get(handle, {}).get('drops')
                after = queue.get('drops')
                if finite(before) and finite(after) and after >= before:
                    interval_drops.append((after - before) / elapsed)
                if finite(queue.get('backlog')):
                    backlogs.append(queue['backlog'])
            # Hierarchical queues may double count the same packet; take maximum.
            if interval_drops:
                drop_rates.append(max(interval_drops))
            for handle, cls in b.get('classes', {}).items():
                before, after = a.get('classes', {}).get(handle, {}).get('bytes'), cls.get('bytes')
                if finite(before) and finite(after) and after >= before:
                    class_rates.append({'handle': handle, 'rate_bps': 8 * (after - before) / elapsed})
        if drop_rates:
            value = sum(drop_rates) / len(drop_rates)
            observations.append({'measurement': 'queue_drop_rate', 'value': value, 'unit': 'packets/second',
                'source': 'same-identity queue counter deltas; mean interval maxima'})
            score += 3 if value > 0 else 0
        if backlogs:
            value = max(backlogs)
            observations.append({'measurement': 'queue_backlog', 'value': value, 'unit': 'bytes',
                'source': 'maximum sampled queue backlog'})
            score += 1 if value > 0 else 0
        if class_rates:
            observations.append({'measurement': 'class_throughput_samples', 'values': class_rates,
                'unit': 'bits/second', 'source': 'observed class counter deltas; no policy inferred'})
        ranked.append({'direction': direction, 'score': score, 'observations': observations})
    ranked.sort(key=lambda c: (-c['score'], c['direction']))
    top = ranked[0]['score'] if ranked else None
    candidates = [c['direction'] for c in ranked if c['score'] == top]
    return {'method': 'observed_link_heuristic_v1', 'path': path, 'ranking': ranked,
        'candidate_set': candidates, 'status': 'unsupported' if not ranked else 'ambiguous' if len(candidates) > 1 or top == 0 else 'ranked',
        'localization_probability': None, 'shap_used': False, 'approved_qos_policy_corroboration': None,
        'end_to_end_observations': {n: window['features'].get(n) for n in ('rtt_p95_ms', 'ping_loss_fraction', 'udp_loss_fraction', 'critical_goodput_bps')},
        'assumptions': 'Same observed path in both directions; score = 3 for measured drops >0, 2 for utilization >0.9, 1 for backlog >0. Ties retained.',
        'limitations': ['A leading score is a suspect, not proven causality; end-to-end delay/loss alone cannot distinguish links',
            'Host access links are uninstrumented; unobserved links and receiver/host faults remain possible',
            'Shared traffic can cause directional queue evidence; scores are not calibrated probabilities',
            'No injection settings, journal, scenario identity, SHAP importance or ground truth used']}
