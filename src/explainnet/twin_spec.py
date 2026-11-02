"""Stdlib snapshot allowlist and bounded observational reconstruction, shared with root."""
import hashlib
import json
from datetime import UTC, datetime
from itertools import pairwise

from explainnet.topology.spec import fields, host_routes, identifier, number, validate_definition

FORBIDDEN = {'scenario', 'scenario_name', 'fault_label', 'label', 'severity', 'laboratory_journal',
    'injected_parameters', 'injection_parameters', 'intended_location', 'netem_seed', 'activated_utc',
    'deactivated_utc', 'injection_schedule', 'configured_loss', 'configured_delay', 'activated_monotonic_s', 'deactivated_monotonic_s'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def reject_hidden(value):
    if isinstance(value, dict):
        if set(value) & FORBIDDEN:
            raise ValueError('hidden experimental state forbidden in twin inputs')
        for child in value.values():
            reject_hidden(child)
    elif isinstance(value, list):
        for child in value:
            reject_hidden(child)


def validate_snapshot(s):
    fields(s, ['schema_version', 'snapshot_id', 'at_utc', 'expires_utc', 'original_instance_id', 'definition',
        'selected_paths', 'queue_configuration', 'workload', 'ownership', 'source_fingerprint', 'window',
        'background_probe', 'diagnosis', 'localization', 'baseline', 'policy', 'provenance', 'snapshot_hash'],
        ['service_requirements', 'measurement_protocol'])
    reject_hidden(s)
    if s['schema_version'] not in {1, 2} or s['snapshot_hash'] != digest({k: v for k, v in s.items() if k != 'snapshot_hash'}):
        raise ValueError('snapshot version/hash mismatch')
    if s['schema_version'] == 2:
        from explainnet.service_requirements import resolve
        if s.get('service_requirements') != resolve(s['window']['features'], s['policy']['objective']):
            raise ValueError('shared service declaration mismatch')
        if s.get('measurement_protocol') != 'paired_capture_v2_fixed_probe_warmup':
            raise ValueError('unsupported measurement protocol')
    identifier(s['snapshot_id'])
    identifier(s['original_instance_id'])
    validate_definition(s['definition'])
    for stamp in ('at_utc', 'expires_utc'):
        dt = datetime.fromisoformat(s[stamp])
        if dt.tzinfo is None or dt.utcoffset() != UTC.utcoffset(dt):
            raise ValueError('snapshot requires UTC')
    duration = (datetime.fromisoformat(s['expires_utc']) - datetime.fromisoformat(s['at_utc'])).total_seconds()
    number(duration, 10, 900)
    for pair in s['definition']['pairs']:
        if s['selected_paths'].get(pair['pair_id']) not in pair['paths']:
            raise ValueError('observed path unavailable')
    if not 1 <= len(s['workload']) <= 3:
        raise ValueError('bounded twin requires 1..3 observable flows')
    for p in s['workload']:
        fields(p, ['profile_id', 'source_host', 'target_host', 'protocol', 'offered_bps', 'packet_size'])
        identifier(p['profile_id'])
        number(p['offered_bps'], 1000, 100000000)
        if p['protocol'] not in {'udp', 'tcp'} or p['source_host'] == p['target_host']:
            raise ValueError('unsupported observable flow')
        hosts = {h['host_id'] for h in s['definition']['hosts']}
        if p['source_host'] not in hosts or p['target_host'] not in hosts:
            raise ValueError('unknown observable endpoint')
        if p['packet_size'] is not None:
            number(p['packet_size'], 64, 1400)
        if p['protocol'] == 'tcp' and p['packet_size'] is not None:
            raise ValueError('TCP packet size unsupported')
    directions = {f"{l[a]}->{l[b]}" for l in s['definition']['links'] for a, b in [('source', 'target'), ('target', 'source')]}
    if set(s['queue_configuration']) != directions or set(s['selected_paths']) != {p['pair_id'] for p in s['definition']['pairs']}:
        raise ValueError('observed directional topology incomplete')
    for policy in s['queue_configuration'].values():
        fields(policy, ['child_classes', 'flow_mapping', 'queues'])
        if len(policy['child_classes']) > 3 or len(policy['flow_mapping']) > 8 or len(policy['queues']) > 5:
            raise ValueError('observed policy exceeds bounds')
        for c in policy['child_classes']:
            fields(c, ['handle', 'rate_bps', 'ceil_bps'])
            if c['handle'] not in {'5:10', '5:20'}:
                raise ValueError('unsupported observed class')
            number(c['rate_bps'], 1000, 20000000)
            number(c['ceil_bps'], c['rate_bps'], 20000000)
        for f in policy['flow_mapping']:
            fields(f, ['source_host', 'target_host', 'classid', 'default'])
            if f['classid'] not in {'5:10', '5:20'} or type(f['default']) is not bool:
                raise ValueError('unsupported flow mapping')
            for k in ('source_host', 'target_host'):
                if f[k] is not None and f[k] not in hosts:
                    raise ValueError('unknown queue endpoint')
        for q in policy['queues']:
            fields(q, ['kind', 'handle', 'limit_packets'])
            if q['kind'] not in {'htb', 'netem'} or q['handle'] not in {'5:', '10:', '20:'}:
                raise ValueError('unsupported observed queue')
            if q['limit_packets'] is not None:
                number(q['limit_packets'], 1, 1000)
    fields(s['ownership'], ['instance_id', 'token', 'subnet', 'switches', 'hosts', 'bridges', 'interfaces'])
    if (s['ownership']['instance_id'] != s['original_instance_id'] or set(s['ownership']['hosts']) != hosts
            or set(s['ownership']['switches']) != set(s['definition']['switches'])):
        raise ValueError('logical/runtime ownership mismatch')
    for v in s['ownership']['switches'].values():
        fields(v, ['name', 'dpid'])
    for v in s['ownership']['hosts'].values():
        fields(v, ['name', 'ip', 'namespace'])
    plane = {k: s[k] for k in ('definition', 'selected_paths', 'queue_configuration', 'workload')}
    if s['source_fingerprint'] != digest(plane):
        raise ValueError('observable fingerprint mismatch')
    fields(s['background_probe'], ['transmitted', 'received', 'rtt_mean_ms', 'sample_count'])
    fields(s['diagnosis'], ['status', 'model_id', 'probabilities', 'uncertainty', 'reason'])
    probabilities = s['diagnosis']['probabilities']
    if probabilities is not None:
        fields(probabilities, ['raw', 'calibrated'])
        for distribution in probabilities.values():
            if distribution is not None:
                fields(distribution, ['healthy', 'saturation', 'loss', 'latency', 'qos'])
                for value in distribution.values():
                    number(value, 0, 1)
    if isinstance(s['diagnosis']['uncertainty'], dict):
        fields(s['diagnosis']['uncertainty'], ['predicted_class', 'confidence', 'margin', 'unsupported_features'])
    fields(s['localization'], ['status', 'candidate_set', 'uncertainty'])
    if len(s['localization']['candidate_set']) > len(directions) or not set(s['localization']['candidate_set']) <= directions:
        raise ValueError('suspect direction outside topology')
    fields(s['baseline'], ['window_ids', 'definition_hash', 'rtt_mean_ms', 'background_rtt_mean_ms', 'source'])
    fields(s['provenance'], ['capture_id', 'source_window_id', 'agent_epoch', 'forwarding_version', 'nominal_settings_source', 'observation_age_s', 'policy_hash'], ['observation_config_digest', 'workload_config_versions'])
    for version in s['provenance'].get('workload_config_versions', []):
        identifier(version)
    number(s['provenance']['observation_age_s'], 0, 30)
    if s['baseline']['definition_hash'] != digest(s['definition']):
        raise ValueError('nominal baseline topology mismatch')
    window = s['window']
    fields(window, ['window_id', 'duration_s', 'complete', 'inference_ready', 'features', 'per_flow', 'data_quality', 'at_utc', 'sample_ids'])
    feature_names = {'rtt_mean_ms', 'rtt_p95_ms', 'rtt_variability_ms', 'ping_loss_fraction', 'udp_loss_fraction',
        'critical_goodput_bps', 'udp_jitter_ms', 'shared_utilization_fraction', 'qos_utilization_fraction',
        'shared_drop_rate_pps', 'critical_class_rate_bps', 'bulk_class_rate_bps', 'queue_backlog_bytes',
        'offered_demand_bps', 'critical_offered_bps', 'active_flow_count', 'primary_path_fraction',
        'cpu_busy_fraction', 'memory_used_fraction', 'critical_drop_rate_pps', 'bulk_drop_rate_pps'}
    fields(window['features'], feature_names)
    if type(window['complete']) is not bool or type(window['inference_ready']) is not bool:
        raise ValueError('explicit evidence flags required')
    number(window['duration_s'], 10, 20)
    if len(window['sample_ids']) > 1000:
        raise ValueError('snapshot observation count exceeds bound')
    for v in window['features'].values():
        if v is not None:
            number(v, 0, 1e12)
    for flow in window['per_flow'].values():
        fields(flow, ['bytes', 'duration_s', 'packets', 'lost_packets', 'delivered_bps', 'loss_fraction'])
    fields(window['data_quality'], ['reasons', 'warnings', 'coverage_fraction', 'sample_count', 'transmitted_probes',
        'successful_probe_count', 'probe_timeouts', 'failed_probe_batches', 'receiver_duration_s', 'missing_metrics',
        'missing_metric_reasons', 'counter_resets', 'stale_age_s'])
    fields(s['policy'], ['version', 'tolerances', 'pilot_window_ids', 'objective', 'max_cpu_busy_fraction',
        'max_memory_used_fraction', 'formula', 'loss_uncertainty', 'minimum_coverage_fraction', 'minimum_probes', 'policy_hash'])
    for tolerance in s['policy']['tolerances'].values():
        fields(tolerance, ['absolute', 'relative', 'pilot_range', 'absolute_cap', 'source'])
        number(tolerance['absolute'], 0, tolerance['absolute_cap'])
        number(tolerance['relative'], 0, 1)
    if (s['policy']['policy_hash'] != digest({k: v for k, v in s['policy'].items() if k != 'policy_hash'})
            or s['provenance']['policy_hash'] != s['policy']['policy_hash']):
        raise ValueError('policy hash mismatch')
    fields(s['policy']['objective'], ['schema_version', 'max_rtt_ms', 'min_goodput_bps', 'max_loss_fraction', 'max_jitter_ms'])
    return s


def obsolete(snapshot, view, now=None):
    now = now or datetime.now(UTC)
    reasons = []
    if now >= datetime.fromisoformat(snapshot['expires_utc']):
        reasons.append('snapshot expired')
    if view['fingerprint'] != snapshot['source_fingerprint']:
        reasons.append('original topology/path/policy/workload drift')
    if view['ownership']['token'] != snapshot['ownership']['token']:
        reasons.append('original ownership changed')
    return reasons


def reconstruct(snapshot, max_hypotheses=2):
    """No classifier label is needed or used to infer effective conditions."""
    validate_snapshot(snapshot)
    number(max_hypotheses, 1, 3)
    w, baseline = snapshot['window'], snapshot['baseline']
    if not w['complete'] or not w['inference_ready']:
        return {'status': 'insufficient-evidence', 'hypotheses': [], 'reason': 'suitable measured window unavailable'}
    # Observed queue class settings or excess offered load already explain loss/
    # queue delay; do not additionally infer netem solely from those outcomes.
    policies = [q for q in snapshot['queue_configuration'].values() if q.get('child_classes')]
    capacities = {f'{l[a]}->{l[b]}': l[key] for l in snapshot['definition']['links']
        for a, b, key in [('source', 'target', 'forward_bps'), ('target', 'source', 'reverse_bps')]}
    routes = host_routes(snapshot['definition'], snapshot['selected_paths'])
    demand = {}
    for flow in snapshot['workload']:
        route = next(r for r in routes if {r['source_host'], r['target_host']} == {flow['source_host'], flow['target_host']})
        switches = route['switches'] if route['source_host'] == flow['source_host'] else route['switches'][::-1]
        for a, b in pairwise(switches):
            demand[f'{a}->{b}'] = demand.get(f'{a}->{b}', 0) + flow['offered_bps']
    saturated = any(value > capacities.get(direction, float('inf')) for direction, value in demand.items())
    if policies or saturated:
        return {'status': 'supported', 'hypotheses': [{'hypothesis_id': 'h0', 'impairments': [],
            'assumption': 'Reproduce observed queue policy and offered demand on fixed nominal capacities; no extra impairment inferred'}],
            'ambiguity': [], 'evidence': {'observed_queue_policy': bool(policies), 'offered_load_exceeds_nominal_capacity': saturated}}
    nominal = baseline.get('rtt_mean_ms')
    actual = w['features'].get('rtt_mean_ms')
    loss = w['features'].get('udp_loss_fraction')
    if actual is None or nominal is None or loss is None:
        return {'status': 'insufficient-evidence', 'hypotheses': [], 'reason': 'receiver loss and qualified RTT reference required'}
    excess = max(0, actual - nominal)
    added, probability = excess if excess > 5 else 0, loss if loss > .02 else 0
    if not added and not probability:
        return {'status': 'supported', 'hypotheses': [{'hypothesis_id': 'h0', 'impairments': [],
            'assumption': 'Observed metrics within nominal baseline bounds; no additional impairment inferred'}], 'ambiguity': []}
    candidates = list(snapshot['localization'].get('candidate_set', []))
    # A heuristic leading score does not eliminate other path explanations.
    # Prefer the observed suspect and its reverse, retain all other directions
    # as untried ambiguity instead of implying unique identification.
    critical = next((r for r in routes if r['source_host'] == 'h1' and r['target_host'] == 'h3'), None)
    if candidates and critical:
        preferred = []
        for d in candidates:
            a, b = d.split('->')
            preferred.extend([d, f'{b}->{a}'])
        candidates = list(dict.fromkeys(preferred + [d for a, b in pairwise(critical['switches']) for d in (f'{a}->{b}', f'{b}->{a}')]))
    bg = snapshot['background_probe']
    bg_nominal = baseline.get('background_rtt_mean_ms')
    bg_actual = bg.get('rtt_mean_ms')
    if added and bg_actual is not None and bg_nominal is not None and bg_actual - bg_nominal > 5:
        # h5/h6 are attached at s2/s3. Its path genuinely constrains the shared
        # segment, but the round-trip measurements still do not identify direction.
        candidates = [d for d in candidates if d in {'s2->s3', 's3->s2'}]
    if not candidates or added > 150 or probability > .2:
        return {'status': 'insufficient-evidence', 'hypotheses': [], 'reason': 'no bounded plausible direction or impairment exceeds reconstruction limits'}
    hypotheses = [{'hypothesis_id': f'h{i}', 'impairments': [{'direction': direction,
        'added_delay_ms': added, 'loss_fraction': probability}],
        'assumption': 'All excess round-trip delay allocated to this one direction; no RTT/2 or symmetry assumption. Receiver loss treated as effective independent drop probability.'}
        for i, direction in enumerate(candidates[:max_hypotheses])]
    return {'status': 'supported', 'hypotheses': hypotheses, 'ambiguity': candidates,
        'untried_directions': candidates[max_hypotheses:],
        'evidence': {'excess_rtt_ms': excess, 'effective_receiver_loss_fraction': loss,
            'background_probe': bg, 'reference': baseline},
        'limitations': ['End-to-end observations do not uniquely identify location/direction or loss process',
            'Independent drops are an effective hypothesis, not a clone of future random outcomes']}
