"""Durable root-owned original action journal and scoped rollback, stdlib only."""
import json
import os
import time
from datetime import UTC, datetime

from explainnet.recovery_runtime import impairment_proof
from explainnet.recovery_spec import feasibility
from explainnet.topology.spec import host_routes
from explainnet.twin_spec import digest, obsolete


class LabActionEngine:
    def __init__(self, manager):
        self.m = manager
        self.records = {p.stem[11:]: json.loads(p.read_text()) for p in manager.state_dir.glob('lab_action_*.json')}

    def _save(self, r):
        r['updated_utc'] = datetime.now(UTC).isoformat()
        self.records[r['action_id']] = r
        path = self.m.state_dir / ('lab_action_' + r['action_id'] + '.json')
        tmp = path.with_suffix('.tmp')
        with tmp.open('w') as stream:
            stream.write(json.dumps(r, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
        directory = os.open(self.m.state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _live(self, r):
        from explainnet.network_runtime import process_identity
        live = self.m._running(r['instance_id'])
        record = live['record']
        if record.get('role') == 'twin' or record['token'] != r['owner_token']:
            raise ValueError('original owner role/token mismatch; no mutation allowed')
        if not all(self.m._owned_bridge(b, record) for b in record['bridges']):
            raise ValueError('original bridge ownership lost')
        if not record.get('host_processes') or any(process_identity(p['pid']) != p for p in record['host_processes']):
            raise ValueError('original host process/namespace ownership lost')
        return live

    def guard(self, instance_id):
        if any(r['instance_id'] == instance_id and r['state'] in {'prepared', 'applying', 'applied', 'rolling_back', 'failed'}
                for r in self.records.values()):
            raise ValueError('original mutation lease held by laboratory recovery')

    def _flows(self, live):
        from explainnet.network_runtime import command
        # Only configuration, no durations/counters. Other owned flow cookies are
        # included so unsafe Undo can detect an intervening forwarding change.
        rows = {}
        for switch, node in live['switches'].items():
            native = command('ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', node.name)
            rows[switch] = sorted(line[line.index('priority='):] for line in native.splitlines() if 'priority=' in line)
        return rows

    def _readback(self, r):
        live = self._live(r)
        view = self.m.twins.view(r['instance_id'])
        view.pop('at_utc', None)
        view.pop('workload_remaining_s', None)  # Countdown is readiness, not installed configuration.
        return {'view': view, 'flows': self._flows(live), 'impairment_digest': digest(impairment_proof(self.m.twins, live))}

    def _export(self, r):
        # Actual native impairment state is root journal evidence, never a
        # diagnosis/builder input. Only equality digests cross this boundary.
        return {k: v for k, v in r.items() if k not in {'native_impairment_before', 'snapshot'}}

    def prepare(self, instance_id, action_id, snapshot, action, idempotency_key, test_hook=None):
        with self.m.lock:
            from explainnet.workflow_spec import WORKFLOW_HASH
            request_hash = digest({'instance': instance_id, 'snapshot': snapshot['snapshot_hash'], 'action': action,
                'key': idempotency_key, 'test_hook': test_hook})
            old = self.records.get(action_id)
            if old:
                if old['request_hash'] != request_hash:
                    raise ValueError('action ID reused with different mutation')
                return self._export(old)
            if any(r['idempotency_key'] == idempotency_key for r in self.records.values()):
                raise ValueError('laboratory idempotency key already used')
            self.guard(instance_id)
            if test_hook and not self.m.allow_lab_test_hooks:
                raise ValueError('test hooks disabled in normal operation')
            live = self.m._running(instance_id)
            if instance_id != snapshot['original_instance_id'] or live['record'].get('role') == 'twin':
                raise ValueError('original logical target mismatch or twin target forbidden')
            view = self.m.twins.view(instance_id)
            if view.get('workload_remaining_s') is not None and view['workload_remaining_s'] < 160:
                raise ValueError('insufficient workload lifetime for bounded original verification/rollback')
            reasons = obsolete(snapshot, view)
            if reasons or view['forwarding_version'] != snapshot['provenance']['forwarding_version']:
                raise ValueError('stale original preconditions: ' + str(reasons))
            feasible = feasibility(snapshot, action)
            r = {'action_id': action_id, 'instance_id': instance_id, 'idempotency_key': idempotency_key,
                'request_hash': request_hash, 'state': 'prepared', 'created_utc': datetime.now(UTC).isoformat(),
                'owner_token': live['record']['token'], 'snapshot': snapshot, 'action': action,
                'workflow_policy_hash': WORKFLOW_HASH, 'logical_diff': action['changes'],
                'previous_owned_state': view, 'rollback_paths': view['selected_paths'], 'feasibility': feasible,
                'resolved_targets': [{'pair_id': c['pair_id'], 'hosts': {h: live['record']['hosts'][h]
                    for h in ('h1', 'h3') if c['pair_id'] == 'critical'} | {h: live['record']['hosts'][h]
                    for h in ('h2', 'h4') if c['pair_id'] == 'bulk'},
                    'switches': [live['record']['switches'][s]['name'] for s in next(p for p in snapshot['definition']['pairs']
                        if p['pair_id'] == c['pair_id'])['paths'][c['to_path']]]} for c in action['changes']],
                'native_impairment_before': impairment_proof(self.m.twins, live), 'steps': [], 'test_hook': test_hook,
                'rollback_plan': 'restore recorded paths/cookies in both directions; never reset network or impairment'}
            r['before'] = self._readback(r)
            self._save(r)  # Durable before the FIRST mutation.
            return self._export(r)

    def apply(self, action_id):
        with self.m.lock:
            r = self.records[action_id]
            if r['state'] != 'prepared':
                return self._export(r)  # Never replay an interrupted/applied action.
            live = self._live(r)
            if self._readback(r) != r['before']:
                raise ValueError('material original change since action preparation')
            r.update(state='applying', applying_utc=datetime.now(UTC).isoformat(), application_started_monotonic_s=time.monotonic())
            self._save(r)
            start = time.monotonic()
            def ack(switch):
                r['steps'].append({'switch': switch, 'at_utc': datetime.now(UTC).isoformat(),
                    'acknowledgement': 'per-switch OpenFlow bundle installed; no global atomicity claim'})
                self._save(r)
                if r['test_hook'] == 'partial_failure' and len(r['steps']) == 1:
                    raise RuntimeError('explicit test hook: failure after first switch bundle')
            try:
                for c in r['logical_diff']:
                    self.m.select_path(r['instance_id'], c['pair_id'], c['to_path'], _recovery=True, _switch_callback=ack)
                r['after'] = self._readback(r)
                if r['after']['view']['selected_paths'] != r['feasibility']['selected_paths']:
                    raise ValueError('installed logical forwarding differs from proposal')
                if r['after']['impairment_digest'] != r['before']['impairment_digest']:
                    raise ValueError('original impairment or physical capacity changed')
                # Independently read route cookies on every expected switch.
                for route in host_routes(live['record']['definition'], live['record']['selected_paths']):
                    if route['pair_id'] not in {c['pair_id'] for c in r['logical_diff']}:
                        continue
                    for switch in route['switches']:
                        for host in (route['source_host'], route['target_host']):
                            if not any('nw_src=' + live['record']['hosts'][host]['ip'] in line
                                    for line in r['after']['flows'][switch]):
                                raise ValueError('missing intended bidirectional forwarding readback')
                r.update(state='applied', fault_preserved=True, workload_preserved=r['after']['view']['workload'] == r['before']['view']['workload'],
                    application_ended_monotonic_s=time.monotonic(),
                    application_elapsed_ms=(time.monotonic() - start) * 1000)
                self._save(r)
                if r['test_hook'] == 'verification_failure':
                    from explainnet.network_runtime import command
                    bridge = live['record']['switches']['s4']['name']
                    cookie = self.m._cookie(live['record'], 900)
                    command('ovs-ofctl', '-O', 'OpenFlow13', '--bundle', 'add-flow', bridge,
                        f"cookie={cookie},priority=500,ip,nw_src={live['record']['hosts']['h1']['ip']},nw_dst={live['record']['hosts']['h3']['ip']},actions=drop")
                    r['test_drop'] = {'bridge': bridge, 'cookie': cookie}
                    self._save(r)
                return self._export(r)
            except Exception as exc:
                r.update(state='failed', error=str(exc), application_ended_monotonic_s=time.monotonic(),
                    application_elapsed_ms=(time.monotonic() - start) * 1000)
                self._save(r)
                raise

    def status(self, action_id):
        r = self.records[action_id]
        return self._export(r) | {'current': self._readback(r)}

    def finish(self, action_id, verified):
        with self.m.lock:
            r = self.records[action_id]
            if r['state'] == 'kept':
                return self.status(action_id)
            if not verified or r['state'] != 'applied' or self._readback(r) != r['after']:
                raise ValueError('cannot keep unverified or materially changed action')
            r.update(state='kept', kept_utc=datetime.now(UTC).isoformat())
            self._save(r)
            return self.status(action_id)

    def rollback(self, action_id):
        with self.m.lock:
            from explainnet.network_runtime import command
            r = self.records[action_id]
            self._live(r)
            if r['state'] == 'rolled_back':
                return self.status(action_id)
            current = self._readback(r)
            # Undo a kept action only if the exact owned configuration still
            # applies, including workload/version/flows/impairment state.
            if r['state'] == 'kept' and current != r['after']:
                raise ValueError('unsafe undo: intervening configuration/workload/version changed')
            if current['view']['workload'] != r['before']['view']['workload']:
                raise ValueError('rollback refused: intervening workload change; operator reconciliation required')
            r.update(state='rolling_back', rollback_started_utc=datetime.now(UTC).isoformat())
            self._save(r)
            try:
                if r.get('test_drop'):
                    command('ovs-ofctl', '-O', 'OpenFlow13', '--bundle', 'del-flows', r['test_drop']['bridge'],
                        'cookie=' + r['test_drop']['cookie'] + '/-1')
                for c in r['logical_diff']:
                    self.m.select_path(r['instance_id'], c['pair_id'], r['rollback_paths'][c['pair_id']], _recovery=True)
                actual = self._readback(r)
                if (actual['view']['selected_paths'] != r['rollback_paths'] or actual['flows'] != r['before']['flows']
                        or actual['impairment_digest'] != r['before']['impairment_digest']):
                    raise ValueError('restoration readback differs from recorded previous configuration')
                probe = self.m.probe(r['instance_id'], 'h1', 'h3')
                if not probe['passed']:
                    raise ValueError('restoration connectivity probe failed')
                r.update(state='rolled_back', restoration=actual, restoration_probe=probe, rollback_ended_utc=datetime.now(UTC).isoformat())
                self._save(r)
                return self._export(r)
            except Exception as exc:
                r.update(state='failed', degraded=True, rollback_error=str(exc))
                self._save(r)
                raise

    def test_stimulus(self, instance_id, recipe):
        if not self.m.allow_lab_test_hooks:
            raise ValueError('test hooks disabled in normal operation')
        with self.m.lock:
            from explainnet.scenario_spec import recipe as parameters
            self.guard(instance_id)
            live = self.m._running(instance_id)
            if live['record'].get('role') == 'twin':
                raise ValueError('test stimulus requires its owned original')
            values = parameters(recipe)
            dev = self.m.scenarios._port(live, 's2', 's3')
            self.m.scenarios._netem(dev, self.m.scenarios._base(live, 's2', 's3')[1] + values['added_delay_ms'])
            (self.m.state_dir / ('ground_truth_' + instance_id + '.json')).write_text(json.dumps(recipe))
            return {'instance_id': instance_id, 'test_stimulus_applied': True}
