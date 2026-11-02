"""Root-compatible twin operations reusing the single network/TC/traffic owner."""
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from explainnet.receiver_stream import recent_receiver
from explainnet.topology.spec import identifier
from explainnet.twin_spec import digest, obsolete, reconstruct, validate_snapshot


class TwinEngine:
    def __init__(self, manager):
        self.m = manager
        self.records = {p.stem[5:]: json.loads(p.read_text()) for p in manager.state_dir.glob('twin_*.json')}
        self.cancel_events = {}

    def _save(self, record):
        self.records[record['twin_id']] = record
        path = self.m.state_dir / f"twin_{record['twin_id']}.json"
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
        temporary.replace(path)

    def view(self, instance_id):
        from explainnet.network_runtime import command
        with self.m.lock:
            live = self.m._running(instance_id)
            r = live['record']
            if not all(self.m._owned_bridge(b, r) for b in r['bridges']):
                raise ValueError('source ownership unavailable')
            queues = {}
            addresses = {v['ip']: h for h, v in r['hosts'].items()}
            for port in r['ports']:
                if port['neighbor'] not in r['switches']:
                    continue
                dev = self.m.scenarios._port(live, port['switch'], port['neighbor'])
                classes = self.m.scenarios._stats(dev, 'class')
                qdiscs = self.m.scenarios._stats(dev, 'qdisc')
                filters = json.loads(command('tc', '-j', 'filter', 'show', 'dev', dev))
                children = [{'handle': c['handle'], 'rate_bps': c['rate'] * 8, 'ceil_bps': c['ceil'] * 8}
                    for c in classes if c['handle'] != '5:1']
                mappings = []
                for f in filters:
                    options = f.get('options', {})
                    keys = options.get('keys', {})
                    src, dst = keys.get('src_ip'), keys.get('dst_ip')
                    classid = options.get('classid', options.get('flowid'))
                    if classid:
                        mappings.append({'source_host': addresses.get(str(src).split('/')[0]) if src else None,
                            'target_host': addresses.get(str(dst).split('/')[0]) if dst else None,
                            'classid': classid, 'default': f.get('kind') == 'matchall'})
                # Explicit allowlist: NEVER return netem delay/loss/jitter/seed or
                # ordinary inspect's reserved fault locations or injector journal.
                queues[f"{port['switch']}->{port['neighbor']}"] = {'child_classes': children,
                    'flow_mapping': mappings, 'queues': [{'kind': q['kind'], 'handle': q['handle'],
                        'limit_packets': q.get('options', {}).get('limit')} for q in qdiscs]}
            workload = []
            workload_versions = set()
            for session in self.m.sessions.values():
                if session['instance_id'] != instance_id:
                    continue
                for profile in session['run']['profiles']:
                    p = profile['parameters']
                    workload_versions.add(p['config_version'])
                    workload.append({k: p[k] for k in ('profile_id', 'source_host', 'target_host', 'protocol', 'offered_bps', 'packet_size')})
            workload.sort(key=lambda p: (p['source_host'], p['target_host'], p['profile_id']))
            plane = {'definition': r['definition'], 'selected_paths': dict(r['selected_paths']),
                'queue_configuration': queues, 'workload': workload}
            ownership = {'instance_id': instance_id, 'token': r['token'], 'subnet': r['subnet'],
                'switches': {s: {'name': v['name'], 'dpid': v['dpid']} for s, v in r['switches'].items()},
                'hosts': {h: {k: v[k] for k in ('name', 'ip', 'namespace')} for h, v in r['hosts'].items()},
                'bridges': r['bridges'], 'interfaces': [p['interface'] for p in r['ports']]}
            return plane | {'ownership': ownership, 'fingerprint': digest(plane),
                'workload_remaining_s': min((max(0, session['started'] + max(p['parameters']['duration_s'] + p['parameters'].get('warmup_s', 0)
                    for p in session['run']['profiles']) - time.monotonic()) for session in self.m.sessions.values()
                    if session['instance_id'] == instance_id), default=None),
                'at_utc': datetime.now(UTC).isoformat(), 'forwarding_version': r['forwarding_version'],
                'agent_epoch': self.m.observation_epoch, 'nominal_settings_source': 'approved original definition; not active netem settings',
                'workload_config_versions': sorted(workload_versions)}

    def _live_receivers(self, instance_id):
        runs = []
        with self.m.lock:
            for session in self.m.sessions.values():
                if session['instance_id'] != instance_id:
                    continue
                profiles = []
                for item in session['processes']:
                    if item['side'] != 'server' or not item['item']['parameters'].get('stream_receiver'):
                        continue
                    profiles.append({'parameters': item['item']['parameters'],
                        'server_json': recent_receiver(item['path']), 'native_stream_file': str(item['path']),
                        'receiver_clock_anchor': item['item'].get('client_launch_clock')})
                runs.append({'run_id': session['run']['run_id'], 'state': 'running', 'profiles': profiles})
        return runs

    def _background_probe(self, instance_id):
        from explainnet.network_runtime import host_command
        with self.m.lock:
            live = self.m._running(instance_id)
            if 'h5' not in live['hosts'] or 'h6' not in live['hosts']:
                return {'transmitted': None, 'received': None, 'rtt_values_ms': []}
            measured = host_command(live['hosts']['h5'], ['ping', '-n', '-c', '3', '-i', '.1', '-W', '.3',
                live['record']['hosts']['h6']['ip']], timeout=2, check=False)
            counts = re.search(r'(\d+) packets transmitted, (\d+) received', measured['stdout'])
            return {'transmitted': int(counts[1]) if counts else None, 'received': int(counts[2]) if counts else None,
                'rtt_values_ms': [float(v) for v in re.findall(r'time[=<]([\d.]+) ms', measured['stdout'])],
                'at_utc': datetime.now(UTC).isoformat(), 'source_host': 'h5', 'target_host': 'h6', 'native': measured}

    def capture(self, instance_id, duration_s=15, twin_id=None):
        from explainnet.telemetry_observe import observe
        if type(duration_s) is not int or not 10 <= duration_s <= 20:
            raise ValueError('measurement duration must be 10..20 seconds')
        ids = [instance_id] + ([twin_id] if twin_id else [])
        if twin_id:
            record = self._owned(twin_id)
            if record['snapshot']['original_instance_id'] != instance_id:
                raise ValueError('twin source mismatch')
        before = self.view(instance_id)
        # Fixed, symmetric probe preconditioning, preserved separately from the
        # measurement interval. Never discard an in-window echo or failed repeat.
        warm_start = time.monotonic()
        warmup = {i: [observe(self.m, i, 'h1', 'h3', 3, [], datetime.now(UTC).isoformat())] for i in ids}
        if (event := self.cancel_events.get(twin_id or instance_id)) and event.is_set():
            raise ValueError('twin operation canceled during probe warmup')
        warmup_ms = (time.monotonic() - warm_start) * 1000
        at_utc, start = datetime.now(UTC).isoformat(), time.monotonic()
        series = {i: [] for i in ids}
        event = self.cancel_events.setdefault(twin_id or instance_id, threading.Event())
        if event.is_set():
            raise ValueError('twin operation canceled')
        while time.monotonic() < start + duration_s:
            if event.is_set():
                raise ValueError('twin operation canceled')
            for i in ids:
                sample = observe(self.m, i, 'h1', 'h3', 3, [], at_utc)
                sample['background_probe'] = self._background_probe(i)
                series[i].append(sample)
            event.wait(.15)
        for i in ids:
            series[i][-1]['active_receiver_runs'] = self._live_receivers(i)
        return {'capture_id': 'v' + uuid4().hex, 'started_utc': at_utc, 'started_monotonic_s': start,
            'measurement_protocol': 'paired_capture_v2_fixed_probe_warmup', 'warmup_series': warmup,
            'warmup_elapsed_ms': warmup_ms,
            'duration_s': duration_s, 'series': series, 'source_before': before, 'source_after': self.view(instance_id),
            'elapsed_ms': (time.monotonic() - start) * 1000, 'original_traffic_stopped': False}

    def budget(self):
        info = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        result = {'cpus': os.cpu_count(), 'available_memory_bytes': info['MemAvailable'] * 1024,
            'memory_used_fraction': 1 - info['MemAvailable'] / info['MemTotal'], 'maximum_live_twins': 1}
        if result['cpus'] < 2 or result['available_memory_bytes'] < 1_073_741_824 or result['memory_used_fraction'] > .85:
            raise ValueError('shared-host resource budget insufficient')
        return result

    def construct(self, twin_id, snapshot, hypothesis_id):
        identifier(twin_id)
        validate_snapshot(snapshot)
        if twin_id == snapshot['original_instance_id'] or not twin_id.startswith('tw'):
            raise ValueError('twin requires a separate tw-prefixed runtime ID')
        with self.m.lock:
            old = self.records.get(twin_id)
            if old and old['state'] == 'running':
                if old['snapshot']['snapshot_hash'] == snapshot['snapshot_hash'] and old['hypothesis_id'] == hypothesis_id:
                    return self.status(twin_id)
                raise ValueError('existing twin version differs; reset/destroy explicitly')
            if twin_id in self.m.records and not old:
                raise ValueError('runtime ID belongs to a non-twin owner')
            if any(r['state'] == 'running' for r in self.records.values()):
                raise ValueError('one live twin at a time; sequential trials required')
            reasons = obsolete(snapshot, self.view(snapshot['original_instance_id']))
            if reasons:
                return {'twin_id': twin_id, 'state': 'stale', 'reasons': reasons}
            plan = reconstruct(snapshot)
            hypothesis = next((h for h in plan['hypotheses'] if h['hypothesis_id'] == hypothesis_id), None)
            if not hypothesis:
                return {'twin_id': twin_id, 'state': 'unsupported', 'reconstruction': plan}
            record = {'twin_id': twin_id, 'snapshot': snapshot, 'hypothesis_id': hypothesis_id,
                'hypothesis': hypothesis, 'state': 'constructing', 'resource_budget': self.budget(), 'created_utc': datetime.now(UTC).isoformat()}
            self._save(record)
            self.cancel_events[twin_id] = threading.Event()
            try:
                self.m.start(twin_id, snapshot['definition'])
                self.m.records[twin_id].update(role='twin', twin_snapshot_hash=snapshot['snapshot_hash'])
                for pair, path in snapshot['selected_paths'].items():
                    self.m.select_path(twin_id, pair, path)
                live = self.m._running(twin_id)
                self._queues(live, snapshot['queue_configuration'])
                profiles = [p | {'schema_version': 1, 'config_version': 'twin_observed_v1', 'duration_s': 100,
                    'warmup_s': 3, 'stream_receiver': True} for p in snapshot['workload']]
                run = self.m.traffic_start(twin_id, profiles)
                record['traffic_run_id'] = run['run_id']
                if self.cancel_events[twin_id].wait(3):
                    raise ValueError('twin operation canceled')
                for impairment in hypothesis['impairments']:
                    if self.cancel_events[twin_id].is_set():
                        raise ValueError('twin operation canceled')
                    a, b = impairment['direction'].split('->')
                    dev = self.m.scenarios._port(live, a, b)
                    self.m.scenarios._netem(dev, self.m.scenarios._base(live, a, b)[1] + impairment['added_delay_ms'], impairment['loss_fraction'])
                # Traffic's native omitted interval happened before reconstruction.
                # Declare and record a fixed settle interval AFTER installed state.
                settled = time.monotonic()
                if self.cancel_events[twin_id].wait(3):
                    raise ValueError('twin operation canceled during reconstructed-state settling')
                record['settling'] = {'version': 'reconstructed_state_v2', 'after_installation_s': 3,
                    'elapsed_ms': (time.monotonic() - settled) * 1000,
                    'reason': 'fixed protocol; no sample-dependent waiting or retry'}
                record.update(state='running', ownership=self.view(twin_id)['ownership'])
                record['isolation_evidence'] = self._isolation(twin_id, snapshot['original_instance_id'])
                if self.cancel_events[twin_id].is_set():
                    raise ValueError('twin operation canceled')
                self.m._save(self.m.records[twin_id])
                self._save(record)
                return self.status(twin_id)
            except Exception as exc:
                record.update(state='failed', error=str(exc))
                try:
                    self.m.cleanup(twin_id)
                    record['scoped_cleanup'] = True
                except Exception as cleanup:  # noqa: BLE001 - preserve partial ownership failure
                    record['cleanup_error'] = str(cleanup)
                self._save(record)
                raise

    def _isolation(self, twin_id, original_id):
        from explainnet.network_runtime import command, host_command
        twin, original = self.m._running(twin_id), self.m._running(original_id)
        bridges = {}
        for name in (twin_id, original_id):
            r = self.m.records[name]
            expected = {p['interface'] for p in r['ports']}
            actual = {b: command('ovs-vsctl', 'list-ports', b).splitlines() for b in r['bridges']}
            if {p for ports in actual.values() for p in ports} != expected:
                raise ValueError('unexpected bridge attachment; isolation refused')
            bridges[name] = actual
        cross = []
        for source, target in ((original, twin), (twin, original)):
            probe = host_command(source['hosts']['h1'], ['ping', '-n', '-c', '1', '-W', '1',
                target['record']['hosts']['h3']['ip']], timeout=2, check=False)
            routes = host_command(source['hosts']['h1'], ['ip', '-j', 'route', 'show'], timeout=2)
            if probe['exit_code'] == 0 or any('gateway' in r or r.get('dst') == 'default' for r in json.loads(routes['stdout'])):
                raise ValueError('unexpected cross-network reachability or external route')
            cross.append({'source_instance': source['record']['instance_id'], 'target_instance': target['record']['instance_id'],
                'native_ping': probe, 'routes': json.loads(routes['stdout'])})
        return {'bridge_ports': bridges, 'cross_network_probes': cross, 'unexpected_attachments': False,
            'external_default_routes': False, 'cross_network_reachable': False}

    def _queues(self, live, queues):
        for direction, policy in queues.items():
            children = {c['handle']: c for c in policy['child_classes']}
            expected_limits = {'10:': 100, '20:': 100} if children else {'10:': 1000}
            if {q['handle']: q['limit_packets'] for q in policy['queues'] if q['kind'] == 'netem'} != expected_limits:
                raise ValueError('unsupported observed queue limits')
            if not children:
                continue
            # Reuse the already validated Linux policy implementation. Refuse
            # unfamiliar mapping/hierarchies rather than silently simplifying.
            expected_mapping = any(p['source_host'] == 'h1' and p['target_host'] == 'h3' and p['classid'] == '5:10' for p in policy['flow_mapping'])
            expected_default = any(p['default'] and p['classid'] == '5:20' for p in policy['flow_mapping'])
            if (direction != 's3->s5' or set(children) != {'5:10', '5:20'} or not expected_mapping
                    or not expected_default or len(policy['flow_mapping']) != 2
                    or children['5:10']['rate_bps'] != min(3_000_000, children['5:10']['ceil_bps'])
                    or children['5:20']['rate_bps'] != 16_000_000 or children['5:20']['ceil_bps'] != 20_000_000):
                raise ValueError('unsupported observed QoS hierarchy/mapping')
            provenance = {'owner': 'twin reconstruction', 'source': 'observed queue policy', 'qos_modified': False}
            self.m.scenarios._qos(live, children['5:10']['ceil_bps'], provenance)

    def _owned(self, twin_id):
        identifier(twin_id)
        record = self.records.get(twin_id)
        if not record or twin_id == record['snapshot']['original_instance_id']:
            raise ValueError('unknown twin-owned runtime')
        return record

    def status(self, twin_id):
        record = self._owned(twin_id)
        reasons = []
        try:
            reasons = obsolete(record['snapshot'], self.view(record['snapshot']['original_instance_id']))
        except ValueError:
            reasons = ['original ownership unavailable']
        owned = self.m.inspect(twin_id, detailed=False)
        if record['state'] == 'running' and not owned.get('live_verified'):
            reasons.append('twin ownership unavailable')
        return {k: v for k, v in record.items() if k != 'snapshot'} | {'snapshot_id': record['snapshot']['snapshot_id'],
            'snapshot_hash': record['snapshot']['snapshot_hash'], 'network': owned, 'stale': bool(reasons), 'stale_reasons': reasons,
            'state': 'failed' if 'twin ownership unavailable' in reasons else record['state']}

    def destroy(self, twin_id):
        with self.m.lock:
            record = self._owned(twin_id)
            if record['state'] != 'destroyed':
                self.m.cleanup(twin_id)
                record.update(state='destroyed', destroyed_utc=datetime.now(UTC).isoformat())
                self._save(record)
            return {'twin_id': twin_id, 'state': record['state'], 'original_modified': False}

    def reset(self, twin_id, hypothesis_id=None):
        record = self._owned(twin_id)
        snapshot = record['snapshot']
        hypothesis_id = hypothesis_id or record['hypothesis_id']
        self.destroy(twin_id)
        return self.construct(twin_id, snapshot, hypothesis_id)

    def cancel(self, twin_id):
        self._owned(twin_id)
        self.cancel_events.setdefault(twin_id, threading.Event()).set()
        return {'twin_id': twin_id, 'cancel_requested': True, 'original_modified': False}

    def apply_candidate(self, twin_id, snapshot_hash, action):
        from explainnet.recovery_runtime import apply
        return apply(self, twin_id, snapshot_hash, action)
