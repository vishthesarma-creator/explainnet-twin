"""Fixed metric tolerances, measured residuals and explicit evidence/resource gates."""
import math

from explainnet.twin_spec import digest

FLOORS = {'rtt_mean_ms': (5, .25, 20), 'rtt_p95_ms': (10, .3, 30),
    'rtt_variability_ms': (3, .5, 10), 'ping_loss_fraction': (.03, 0, .05),
    'udp_loss_fraction': (.03, 0, .05), 'udp_jitter_ms': (2, .5, 8),
    'critical_goodput_bps': (100000, .15, 500000), 'shared_utilization_fraction': (.10, 0, .15),
    'qos_utilization_fraction': (.10, 0, .15), 'queue_backlog_bytes': (65536, .5, 262144),
    'critical_class_rate_bps': (100000, .15, 500000), 'bulk_class_rate_bps': (100000, .2, 500000),
    'protected_rate': (100000, .2, 500000), 'protected_loss': (.03, 0, .05)}


def freeze_policy(pilot_windows, objective):
    if len(pilot_windows) < 2 or any(not w['inference_ready'] for w in pilot_windows):
        raise ValueError('at least two suitable nominal pilot windows required to freeze tolerances')
    tolerances = {}
    for name, (floor, relative, cap) in FLOORS.items():
        values = [w['features'].get(name) for w in pilot_windows]
        values = [v for v in values if v is not None]
        spread = max(values) - min(values) if values else None
        service_floor = .05 * (objective.get('max_rtt_ms') or 100) if name == 'rtt_mean_ms' else 0
        absolute = max(floor, service_floor, 2 * spread if spread is not None else 0)
        if absolute > cap:
            raise ValueError(f'pilot variability too large to qualify tolerance: {name}')
        tolerances[name] = {'absolute': absolute, 'relative': relative, 'pilot_range': spread,
            'absolute_cap': cap, 'source': 'fixed engineering floor, nominal pilot range and service objective'}
    policy = {'version': 'fidelity_v1', 'tolerances': tolerances, 'pilot_window_ids': [w['window_id'] for w in pilot_windows],
        'objective': objective, 'max_cpu_busy_fraction': .85, 'max_memory_used_fraction': .85,
        'formula': 'absolute_error <= absolute_floor + relative*abs(original)',
        'loss_uncertainty': 'binomial standard error is descriptive; correlated packets are not independent',
        'minimum_coverage_fraction': .65, 'minimum_probes': 6}
    policy['policy_hash'] = digest(policy)
    return policy


def compare(original, twin, policy, workload, queue_configuration, stale_reasons=()):
    if policy['policy_hash'] != digest({k: v for k, v in policy.items() if k != 'policy_hash'}):
        raise ValueError('frozen fidelity policy changed')
    missing, contaminated, metrics = [], [], []
    if original['duration_s'] != twin['duration_s']:
        missing.append('measurement durations do not match')
    for label, w in [('original', original), ('twin', twin)]:
        if not w['inference_ready'] or not w['complete']:
            missing.append(label + ': suitable complete measured window unavailable')
        if w['data_quality']['coverage_fraction'] < policy['minimum_coverage_fraction'] or w['data_quality']['transmitted_probes'] < policy['minimum_probes']:
            missing.append(label + ': minimum sampling/probe evidence unavailable')
        for name in ('cpu_busy_fraction', 'memory_used_fraction'):
            value = w['features'].get(name)
            limit = policy['max_' + name]
            if value is None:
                missing.append(label + ': resource observation missing: ' + name)
            elif value > limit or any('resource contamination' in r for r in w['data_quality']['reasons']):
                contaminated.append(label + ': shared host pressure: ' + name)
    names = ['rtt_mean_ms', 'rtt_p95_ms', 'rtt_variability_ms', 'ping_loss_fraction', 'critical_goodput_bps',
        'shared_utilization_fraction', 'qos_utilization_fraction', 'queue_backlog_bytes']
    if any(p['source_host'] == 'h1' and p['target_host'] == 'h3' and p['protocol'] == 'udp' for p in workload):
        names.extend(['udp_loss_fraction', 'udp_jitter_ms'])
    if any(q['child_classes'] for q in queue_configuration.values()):
        names.extend(['critical_class_rate_bps', 'bulk_class_rate_bps'])
    def metric(name, left, right, tolerance_name):
        tolerance = policy['tolerances'][tolerance_name]
        if left is None or right is None or not math.isfinite(left) or not math.isfinite(right):
            metrics.append({'metric': name, 'original': left, 'twin': right, 'status': 'missing', 'error': None, 'tolerance': None})
            missing.append(name)
            return
        error, allowed = abs(right - left), tolerance['absolute'] + tolerance['relative'] * abs(left)
        metrics.append({'metric': name, 'original': left, 'twin': right, 'signed_error': right - left,
            'absolute_error': error, 'tolerance': allowed, 'status': 'pass' if error <= allowed else 'fail'})
    for name in names:
        metric(name, original['features'].get(name), twin['features'].get(name), name)
    for flow in workload:
        if flow['source_host'] == 'h1' and flow['target_host'] == 'h3':
            continue
        key = f"{flow['source_host']}->{flow['target_host']}:{flow['protocol']}"
        left, right = original['per_flow'].get(key, {}), twin['per_flow'].get(key, {})
        for label, flow_window, observation in [('original', original, left), ('twin', twin, right)]:
            if (observation.get('duration_s') or 0) / flow_window['duration_s'] < policy['minimum_coverage_fraction']:
                missing.append(label + ': protected flow receiver coverage insufficient: ' + key)
        metric(key + ':goodput_bps', left.get('delivered_bps'), right.get('delivered_bps'), 'protected_rate')
        if flow['protocol'] == 'udp':
            metric(key + ':loss_fraction', left.get('loss_fraction'), right.get('loss_fraction'), 'protected_loss')
    def counts(w):
        n, loss = w['data_quality']['transmitted_probes'], w['features'].get('ping_loss_fraction')
        received = w['data_quality']['successful_probe_count']
        return {'probe_transmitted': w['data_quality']['transmitted_probes'], 'probe_received': w['data_quality']['successful_probe_count'],
            'ping_loss_standard_error': math.sqrt(loss * (1 - loss) / n) if n and loss is not None else None,
            'rtt_mean_standard_error_ms': w['features']['rtt_variability_ms'] / math.sqrt(received) if received and w['features']['rtt_variability_ms'] is not None else None,
            'receiver_duration_s': w['data_quality']['receiver_duration_s'], 'coverage_fraction': w['data_quality']['coverage_fraction'],
            'flows': {key: {'packets': f['packets'], 'duration_s': f['duration_s'],
                'loss_standard_error': math.sqrt(f['loss_fraction'] * (1 - f['loss_fraction']) / f['packets']) if f['packets'] and f['loss_fraction'] is not None else None}
                for key, f in w['per_flow'].items()}}
    status = ('stale' if stale_reasons else 'insufficient-evidence' if missing or contaminated else
        'fail' if any(m['status'] == 'fail' for m in metrics) else 'pass')
    return {'status': status, 'metrics': metrics, 'missing_required_metrics': missing, 'contamination': contaminated,
        'stale_reasons': list(stale_reasons), 'policy_hash': policy['policy_hash'], 'original_window_id': original['window_id'],
        'twin_window_id': twin['window_id'], 'original_counts': counts(original), 'twin_counts': counts(twin),
        'measurement_duration_s': [original['duration_s'], twin['duration_s']],
        'interpretation': 'No-change packet fidelity for this hypothesis/workload; not exact state cloning or proven fault cause'}
