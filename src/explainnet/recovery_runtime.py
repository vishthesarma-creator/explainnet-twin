"""Root action execution on verified twin ownership only; no original repair API."""
import json

from explainnet.recovery_spec import POLICY, feasibility, validate_action
from explainnet.twin_spec import obsolete


def impairment_proof(engine, live):
    """Compare own twin netem parameters and physical parent rates, never injector truth."""
    result = {}
    for p in live['record']['ports']:
        if p['neighbor'] not in live['record']['switches']:
            continue
        dev = engine.m.scenarios._port(live, p['switch'], p['neighbor'])
        result[p['switch'] + '->' + p['neighbor']] = {
            'netem': [{k: q.get(k) for k in ('kind', 'handle', 'parent', 'options')}
                for q in engine.m.scenarios._stats(dev, 'qdisc') if q['kind'] == 'netem'],
            'physical_parent': [{k: c.get(k) for k in ('handle', 'rate', 'ceil')}
                for c in engine.m.scenarios._stats(dev, 'class') if c['handle'] == '5:1']}
    return result


def apply(engine, twin_id, snapshot_hash, action):
    validate_action(action)
    with engine.m.lock:
        r = engine._owned(twin_id)  # Registry/source separation, then actual root ownership.
        snapshot = r['snapshot']
        if r['state'] != 'running' or snapshot['snapshot_hash'] != snapshot_hash:
            raise ValueError('twin action requires running immutable snapshot lineage')
        if r.get('recovery_application'):
            raise ValueError('reset required before every action; cumulative repairs forbidden')
        stale = obsolete(snapshot, engine.view(snapshot['original_instance_id']))
        if stale:
            raise ValueError('stale recovery preconditions: ' + ', '.join(stale))
        live = engine.m._running(twin_id)
        if live['record'].get('role') != 'twin' or live['record'].get('twin_snapshot_hash') != snapshot_hash:
            raise ValueError('verified twin role/hash required; original execution forbidden')
        before_view = engine.view(twin_id)
        if before_view['fingerprint'] != snapshot['source_fingerprint']:
            raise ValueError('twin does not start from immutable observed configuration')
        feasible = feasibility(snapshot, action)
        before = impairment_proof(engine, live)
        result = {'action': action, 'state': 'applying', 'runtime_twin_id': twin_id,
            'runtime_token': live['record']['token'], 'snapshot_hash': snapshot_hash,
            'logical_diff': action['changes'], 'feasibility': feasible, 'impairment_before': before,
            'original_modified': False,
            'native_evidence_units': {'tc_netem_delay_options': 'seconds', 'tc_class_rate_and_ceil': 'bytes/second',
                'normalized_policy_and_metrics': 'milliseconds, bits/second, loss fractions'}}
        r['recovery_application'] = result
        engine._save(r)
        try:
            if engine.cancel_events[twin_id].is_set():
                raise ValueError('twin operation canceled')
            if action['family'] == 'reroute':
                for c in action['changes']:
                    engine.m.select_path(twin_id, c['pair_id'], c['to_path'])
            elif action['family'] == 'shape_background':
                # Shape selected source at its host access class, leaving switch
                # impairment qdiscs and the offered client demand untouched.
                from explainnet.network_runtime import host_command
                host = live['hosts']['h5']
                dev = host.defaultIntf().name
                classes = json.loads(host_command(host, ['tc', '-j', 'class', 'show', 'dev', dev])['stdout'])
                if len(classes) != 1 or classes[0]['handle'] != '5:1' or classes[0]['rate'] * 8 < POLICY['background_limit_bps']:
                    raise ValueError('unsupported owned background access hierarchy')
                host_command(host, ['tc', 'class', 'change', 'dev', dev, 'parent', '5:', 'classid', '5:1',
                    'htb', 'rate', str(POLICY['background_limit_bps']) + 'bit',
                    'ceil', str(POLICY['background_limit_bps']) + 'bit'])
            elif action['family'] == 'restore_qos':
                dev = engine.m.scenarios._port(live, 's3', 's5')
                for handle, rate, ceil in [('5:10', 3_000_000, 4_000_000), ('5:20', 16_000_000, 20_000_000)]:
                    engine.m.scenarios.tc(dev, 'class', 'change', 'parent', '5:1', 'classid', handle,
                        'htb', 'rate', str(rate) + 'bit', 'ceil', str(ceil) + 'bit', 'prio', '0' if handle == '5:10' else '1')
            after = impairment_proof(engine, live)
            if after != before:
                raise ValueError('candidate altered reconstructed impairment or physical capacity')
            result.update(state='applied', impairment_after=after, fault_preserved=True,
                workload_preserved=engine.view(twin_id)['workload'] == snapshot['workload'])
            if not result['workload_preserved']:
                raise ValueError('candidate changed offered traffic demand')
            engine._save(r)
            return result
        except Exception as exc:
            result.update(state='failed', error=str(exc))
            engine._save(r)
            raise
