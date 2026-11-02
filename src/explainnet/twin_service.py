"""Unprivileged durable twin orchestration; all packet work belongs to the agent."""
import json
import statistics
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from explainnet.link_localization import localize
from explainnet.storage import utc_now
from explainnet.telemetry_contracts import TelemetrySettings
from explainnet.telemetry_math import aggregate_windows, receiver_records
from explainnet.telemetry_storage import TelemetryRepository
from explainnet.twin_contracts import (
    AgentConstructRequest,
    CaptureRequest,
    TwinMeasureRequest,
    TwinRequest,
    TwinResetRequest,
)
from explainnet.twin_fidelity import compare, freeze_policy
from explainnet.twin_spec import digest, obsolete, reconstruct, validate_snapshot


class TwinCanceled(RuntimeError):
    """A canceled operation is distinct from an ordinary failure."""


class TwinService:
    def __init__(self, store, agent, objective=None, diagnosis=None):
        self.store, self.agent = store, agent
        self.repo = TelemetryRepository(store)
        self.objective = objective.model_dump() if hasattr(objective, 'model_dump') else objective or {
            'schema_version': 1, 'max_rtt_ms': 100, 'min_goodput_bps': 1000000,
            'max_loss_fraction': .02, 'max_jitter_ms': None}
        self.diagnosis = diagnosis
        self.lock = threading.RLock()
        self.owned = set()
        self.cleanup_threads = []

    def get_snapshot(self, snapshot_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM twin_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
        if not row:
            raise ValueError('unknown immutable twin snapshot')
        return validate_snapshot(json.loads(row[0]))

    def _get_instance(self, twin_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM twin_instances WHERE twin_id=?', (twin_id,)).fetchone()
        if not row:
            raise ValueError('unknown persisted twin')
        return json.loads(row[0])

    def _save_instance(self, result, snapshot_id):
        with self.store.connection() as db:
            db.execute('INSERT INTO twin_instances VALUES(?,?,?,?) ON CONFLICT(twin_id) DO UPDATE SET '
                'snapshot_id=excluded.snapshot_id,state=excluded.state,payload_json=excluded.payload_json',
                (result['twin_id'], snapshot_id, result['state'], json.dumps(result, allow_nan=False)))

    def _trial(self, trial_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM twin_trials WHERE trial_id=?', (trial_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_trial(self, result):
        with self.store.connection() as db:
            db.execute('INSERT INTO twin_trials VALUES(?,?,?,?,?) ON CONFLICT(trial_id) DO UPDATE SET '
                'state=excluded.state,payload_json=excluded.payload_json', (result['trial_id'], result['twin_id'],
                result['state'], result['created_utc'], json.dumps(result, allow_nan=False)))

    @staticmethod
    def background(points):
        probes = [p['background_probe'] for p in points if 'background_probe' in p]
        values = [v for p in probes for v in p['rtt_values_ms']]
        return {'transmitted': sum(p.get('transmitted') or 0 for p in probes),
            'received': sum(p.get('received') or 0 for p in probes),
            'rtt_mean_ms': statistics.mean(values) if values else None, 'sample_count': len(values)}

    def materialize(self, capture, instance_id):
        """Save native frames/intervals and reuse Stage 5 definitions without clipping."""
        run_id = 't9' + uuid4().hex
        session = {'run_id': run_id, 'instance_id': instance_id, 'started_utc': capture['started_utc'],
            'started_monotonic_s': capture['started_monotonic_s'],
            'ended_monotonic_s': capture['started_monotonic_s'] + capture['duration_s']}
        self.store.insert_record('runs', run_id, session | {'kind': 'twin_no_change_observation'},
            config_hash=capture['source_before']['fingerprint'])
        points = capture['series'][instance_id]
        for point in capture.get('warmup_series', {}).get(instance_id, []):
            point = point | {'run_id': run_id, 'nominal_definition': capture['source_before']['definition']}
            self.repo.ingest(point)
        for point in points:
            point['run_id'] = run_id
            point['nominal_definition'] = capture['source_before']['definition']
            self.repo.ingest(point)
        # Native streams include the entire ongoing run. Persist interval rows
        # only for this matched window; the final raw frame retains the native
        # stream. Re-ingesting all historical intervals on a Windows mount can
        # delay snapshot publication until its observations are already stale.
        anchor, end = session['started_monotonic_s'], session['ended_monotonic_s']
        records = receiver_records(points[-1], run_id)
        selected = [r for r in records if r['valid'] and anchor <= r['start_monotonic_s'] < r['end_monotonic_s'] <= end]
        selected += [r for r in records if not r['valid']][:20]
        for record in selected:
            self.repo.ingest(record)
        settings = TelemetrySettings(window_s=capture['duration_s'], sample_interval_s=2.5,
            max_cpu_busy_fraction=.85, max_memory_used_fraction=.85)
        windows = aggregate_windows(self.repo.samples(run_id), session, settings, session['ended_monotonic_s'], final=True)
        if not windows:
            raise ValueError('no actual measurement window available')
        self.repo.save_windows(windows, [{'status': 'twin_observation', 'window_id': w['window_id']} for w in windows])
        return windows[0], self.background(points)

    def capture(self, instance_id, duration_s=15):
        capture = self.agent.twin_capture(CaptureRequest(instance_id=instance_id, duration_s=duration_s))
        window, background = self.materialize(capture, instance_id)
        return {'capture': capture, 'window': window, 'background_probe': background}

    def pilot_reference(self, window_ids, definition_hash):
        windows, background = [], []
        if not 2 <= len(window_ids) <= 4 or len(set(window_ids)) != len(window_ids):
            raise ValueError('two to four distinct measured nominal pilot windows required')
        with self.store.connection() as db:
            for wid in window_ids:
                membership = db.execute('SELECT partition FROM dataset_members WHERE window_id=?', (wid,)).fetchone()
                if membership and membership[0] == 'test':
                    raise ValueError('test partition sealed until Stage 13')
                row = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (wid,)).fetchone()
                if not row:
                    raise ValueError('pilot must reference stored measured evidence')
                w = json.loads(row[0])
                if not w['inference_ready'] or not w['complete']:
                    raise ValueError('pilot evidence unsuitable')
                rows = db.execute('SELECT payload_json FROM telemetry_samples WHERE run_id=? AND source=\'network_agent\'', (w['run_id'],)).fetchall()
                points = [json.loads(r[0]) for r in rows]
                if not points or any('nominal_definition' not in p or digest(p['nominal_definition']) != definition_hash for p in points):
                    raise ValueError('pilot nominal definition differs')
                windows.append(w)
                background.append(self.background(points)['rtt_mean_ms'])
        reference = {'window_ids': window_ids, 'definition_hash': definition_hash,
            'rtt_mean_ms': statistics.mean(w['features']['rtt_mean_ms'] for w in windows),
            'background_rtt_mean_ms': statistics.mean(background) if all(v is not None for v in background) else None,
            'source': 'operator-designated nominal pilot; stored native observations, no injector settings'}
        return reference, freeze_policy(windows, self.objective)

    def snapshot(self, request):
        with self.lock:
            request_hash = digest(request.model_dump())
            with self.store.connection() as db:
                row = db.execute('SELECT payload_json FROM twin_snapshots WHERE request_key=?', (request.request_key,)).fetchone()
                audit = db.execute("SELECT payload_json FROM audit_events WHERE event_type='twin_snapshot_request' AND subject_id=?", (request.request_key,)).fetchone()
            if row:
                if audit and json.loads(audit[0])['request_hash'] != request_hash:
                    raise ValueError('snapshot request key reused with different inputs')
                s = json.loads(row[0])
                return {'snapshot': s, 'reconstruction': reconstruct(s), 'idempotent': True}
            if set(request.baseline) != {'window_ids', 'definition_hash'}:
                raise ValueError('baseline requires stored pilot IDs and nominal definition hash only')
            reference, policy = self.pilot_reference(**request.baseline)
            if request.policy != policy:
                raise ValueError('policy must equal frozen policy derived from registered nominal pilots and service objective')
            captured = self.capture(request.instance_id, request.duration_s)
            c, w = captured['capture'], captured['window']
            view = c['source_after']
            if digest(view['definition']) != reference['definition_hash']:
                raise ValueError('nominal reference belongs to a different topology')
            if c['source_before']['fingerprint'] != view['fingerprint']:
                raise ValueError('source drift during snapshot; explicit bounded refresh required')
            located = localize(w, view['definition'], c['series'][request.instance_id])
            diagnosis = {'status': 'unavailable', 'model_id': None, 'probabilities': None,
                'uncertainty': 'No verified active model available', 'reason': 'Stage 7 measured model prerequisite incomplete'}
            if self.diagnosis and self.diagnosis.status().get('active_model_id'):
                model = self.diagnosis.status()['active_model_id']
                record = self.diagnosis.diagnose(model, w['window_id'], 'recorded')
                diagnosis = {'status': record.get('status'), 'model_id': model,
                    'probabilities': {'raw': record.get('raw_probabilities'), 'calibrated': record.get('calibrated_probabilities')},
                    'uncertainty': {k: record.get(k) for k in ('predicted_class', 'confidence', 'margin', 'unsupported_features')},
                    'reason': record.get('reasons', [])}
            now = datetime.now(UTC)
            snapshot = {k: view[k] for k in ('definition', 'selected_paths', 'queue_configuration', 'workload', 'ownership')}
            from explainnet.service_requirements import resolve
            snapshot.update(schema_version=2, snapshot_id='sn' + uuid4().hex, at_utc=now.isoformat(),
                expires_utc=(now + timedelta(seconds=request.expiry_s)).isoformat(), original_instance_id=request.instance_id,
                source_fingerprint=view['fingerprint'], window={k: w[k] for k in ('window_id', 'duration_s', 'complete',
                    'inference_ready', 'features', 'per_flow', 'data_quality', 'at_utc', 'sample_ids')},
                background_probe=captured['background_probe'], diagnosis=diagnosis,
                service_requirements=resolve(w['features'], self.objective),
                measurement_protocol=c.get('measurement_protocol', 'legacy_capture_v1'),
                localization={'status': located['status'], 'candidate_set': located['candidate_set'],
                    'uncertainty': 'Observed heuristic suspects, not calibrated probabilities or proven causes'},
                baseline=reference, policy=policy, provenance={'capture_id': c['capture_id'], 'source_window_id': w['window_id'],
                    'agent_epoch': view['agent_epoch'], 'forwarding_version': view['forwarding_version'],
                    'nominal_settings_source': view['nominal_settings_source'],
                    'observation_config_digest': c['series'][request.instance_id][-1]['observed_config_hash'],
                    'workload_config_versions': view.get('workload_config_versions', []),
                    'observation_age_s': max(0, (now - datetime.fromisoformat(w['at_utc'])).total_seconds()), 'policy_hash': policy['policy_hash']})
            snapshot['snapshot_hash'] = digest(snapshot)
            validate_snapshot(snapshot)
            with self.store.connection() as db:
                db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?)', (snapshot['snapshot_id'], w['run_id'],
                    digest(view['definition']), snapshot['snapshot_hash'], utc_now(), json.dumps(snapshot)))
                db.execute('INSERT INTO twin_snapshots VALUES(?,?,?,?)', (snapshot['snapshot_id'], request.request_key,
                    snapshot['snapshot_hash'], json.dumps(snapshot)))
            self.store.audit('twin-service', 'twin_snapshot_request', {'request_hash': request_hash}, subject_id=request.request_key)
            return {'snapshot': snapshot, 'reconstruction': reconstruct(snapshot), 'idempotent': False}

    def construct(self, request):
        with self.lock:
            snapshot = self.get_snapshot(request.snapshot_id)
            try:
                prior = self._get_instance(request.twin_id)
            except ValueError:
                prior = None
            if prior and prior['state'] in {'constructing', 'running', 'failed'} and (
                    prior['snapshot_id'] != request.snapshot_id or prior.get('hypothesis_id') != request.hypothesis_id):
                raise ValueError('persisted twin ownership differs; explicit scoped destruction required')
            pending = {'twin_id': request.twin_id, 'snapshot_id': request.snapshot_id, 'state': 'constructing',
                'hypothesis_id': request.hypothesis_id, 'progress': 'agent constructing isolated network'}
            self._save_instance(pending, request.snapshot_id)
            self.owned.add(request.twin_id)
            try:
                result = self.agent.twin_construct(AgentConstructRequest(twin_id=request.twin_id, snapshot=snapshot,
                    hypothesis_id=request.hypothesis_id))
            except Exception as exc:
                failure = pending | {'state': 'failed', 'error': str(exc)}
                try:
                    self.agent.twin_cancel(TwinRequest(twin_id=request.twin_id))
                    failure['cleanup'] = self.agent.twin_destroy(TwinRequest(twin_id=request.twin_id))
                except Exception as cleanup:  # noqa: BLE001 - root ownership journal survives
                    failure['cleanup_error'] = str(cleanup)
                self._save_instance(failure, request.snapshot_id)
                if 'canceled' in str(exc):
                    raise TwinCanceled(str(exc)) from exc
                raise
            self._save_instance(result | {'snapshot_id': request.snapshot_id}, request.snapshot_id)
            if result['state'] == 'running':
                self.owned.add(request.twin_id)
            return result

    def status(self, twin_id):
        cached = self._get_instance(twin_id)
        if cached['state'] in {'unsupported', 'stale', 'constructing'}:
            return cached
        live = self.agent.twin_status(TwinRequest(twin_id=twin_id))
        with self.store.connection() as db:
            trials = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM twin_trials WHERE twin_id=? ORDER BY rowid', (twin_id,))]
        return live | {'trials': trials, 'current_validity': 'stale' if live['stale'] else 'current'}

    def measure(self, request):
        with self.lock:
            old = self._trial(request.trial_id)
            request_hash = digest(request.model_dump())
            if old:
                if old['request_hash'] != request_hash:
                    raise ValueError('trial ID reused with different inputs')
                return old
            cached = self._get_instance(request.twin_id)
            snapshot = self.get_snapshot(cached['snapshot_id'])
            result = {'trial_id': request.trial_id, 'twin_id': request.twin_id, 'created_utc': utc_now(),
                'request_hash': request_hash, 'state': 'running', 'progress': 'matched packet capture',
                'hypothesis_id': cached.get('hypothesis_id'), 'parameters': cached.get('hypothesis')}
            self._save_trial(result)
            try:
                status = self.agent.twin_status(TwinRequest(twin_id=request.twin_id))
                if status['stale'] or status['state'] != 'running':
                    result.update(state='stale', reasons=status['stale_reasons'], progress='refused obsolete measurement')
                    self._save_trial(result)
                    return result
                c = self.agent.twin_capture(CaptureRequest(instance_id=snapshot['original_instance_id'],
                    twin_id=request.twin_id, duration_s=request.duration_s))
                left, bg_left = self.materialize(c, snapshot['original_instance_id'])
                right, bg_right = self.materialize(c, request.twin_id)
                stale = obsolete(snapshot, c['source_after'])
                source_digests = {p['observed_config_hash'] for p in c['series'][snapshot['original_instance_id']]}
                reference_digest = snapshot['provenance'].get('observation_config_digest')
                if len(source_digests) != 1 or (reference_digest and source_digests != {reference_digest}):
                    stale.append('observed configuration digest changed since snapshot')
                if c['source_before']['fingerprint'] != c['source_after']['fingerprint']:
                    stale.append('original state changed during measurement')
                verdict = compare(left, right, snapshot['policy'], snapshot['workload'], snapshot['queue_configuration'], stale)
                result.update(state=verdict['status'], fidelity=verdict, original=left, twin=right,
                    original_background_probe=bg_left, twin_background_probe=bg_right,
                    elapsed_ms=c['elapsed_ms'], original_traffic_stopped=c['original_traffic_stopped'], progress='completed')
                self._save_trial(result)
                return result
            except Exception as exc:
                result.update(state='canceled' if 'canceled' in str(exc) else 'failed', error=str(exc), progress='scoped cleanup')
                try:
                    result['cleanup'] = self.agent.twin_destroy(TwinRequest(twin_id=request.twin_id))
                except Exception as cleanup:  # noqa: BLE001
                    result['cleanup_error'] = str(cleanup)
                self._save_trial(result)
                if result['state'] == 'canceled':
                    raise TwinCanceled(str(exc)) from exc
                raise

    def reset(self, request):
        with self.lock:
            request_hash = digest(request.model_dump())
            if request.request_key:
                with self.store.connection() as db:
                    row = db.execute("SELECT payload_json FROM audit_events WHERE event_type='twin_reset_request' AND subject_id=? ORDER BY id DESC LIMIT 1",
                        (request.request_key,)).fetchone()
                if row:
                    saved = json.loads(row[0])
                    if saved['request_hash'] != request_hash:
                        raise ValueError('reset request key reused with different inputs')
                    return saved['result']
            cached = self._get_instance(request.twin_id)
            result = self.agent.twin_reset(request)
            self._save_instance(result | {'snapshot_id': cached['snapshot_id']}, cached['snapshot_id'])
            if request.request_key:
                self.store.audit('twin-service', 'twin_reset_request', {'request_hash': request_hash, 'result': result},
                    subject_id=request.request_key)
            return result

    def destroy(self, request):
        with self.lock:
            cached = self._get_instance(request.twin_id)
            if cached['state'] in {'stale', 'unsupported'}:
                return cached | {'original_modified': False}
            result = self.agent.twin_destroy(request)
            self._save_instance(result | {'snapshot_id': cached['snapshot_id']}, cached['snapshot_id'])
            self.owned.discard(request.twin_id)
            return result

    def cancel(self, request):
        # Deliberately outside the orchestration lock: interrupt a running capture.
        self._get_instance(request.twin_id)
        result = self.agent.twin_cancel(request)
        thread = threading.Thread(target=self._cancel_cleanup, args=(request,), daemon=True)
        self.cleanup_threads.append(thread)
        thread.start()
        return result | {'scoped_cleanup_scheduled': True}

    def _cancel_cleanup(self, request):
        try:
            self.destroy(request)
        except Exception as exc:  # noqa: BLE001 - persist cleanup failure
            cached = self._get_instance(request.twin_id)
            self._save_instance(cached | {'state': 'failed', 'cleanup_error': str(exc)}, cached['snapshot_id'])

    def calibrate(self, request):
        with self.lock:
            request_hash = digest(request.model_dump())
            old = self._trial(request.operation_id)
            if old:
                if old.get('request_hash') != request_hash:
                    raise ValueError('calibration operation ID reused with different inputs')
                return old
            cached = self._get_instance(request.twin_id)
            snapshot = self.get_snapshot(cached['snapshot_id'])
            hypotheses = reconstruct(snapshot)['hypotheses'][:request.max_trials]
            result = {'trial_id': request.operation_id, 'twin_id': request.twin_id, 'created_utc': utc_now(),
                'kind': 'bounded_calibration', 'state': 'running', 'request_hash': request_hash,
                'max_trials': request.max_trials, 'trials': [], 'progress': 'sequential hypothesis verification'}
            self._save_trial(result)
            trials, reason = [], 'available bounded hypotheses exhausted; ambiguity retained'
            for index, h in enumerate(hypotheses):
                trial_id = request.operation_id + '_' + str(index)
                existing = self._trial(trial_id)
                if existing:
                    trials.append(existing)
                    continue
                try:
                    reset = self.reset(TwinResetRequest(twin_id=request.twin_id, hypothesis_id=h['hypothesis_id']))
                except Exception as exc:
                    result.update(state='failed', error=str(exc), termination_reason='scoped reset failed')
                    self._save_trial(result)
                    raise
                if reset['state'] != 'running':
                    reason = reset['state']
                    break
                try:
                    trial = self.measure(TwinMeasureRequest(twin_id=request.twin_id, trial_id=trial_id, duration_s=request.duration_s))
                except Exception as exc:
                    result.update(state='canceled' if isinstance(exc, TwinCanceled) else 'failed',
                        error=str(exc), termination_reason='bounded measurement interrupted')
                    self._save_trial(result)
                    raise
                trials.append(trial)
                result.update(trials=trials, progress=f'{len(trials)} bounded trials complete')
                self._save_trial(result)
                if trial['state'] in {'stale', 'insufficient-evidence', 'failed', 'canceled'}:
                    reason = trial['state']
                    break
            result.update(state='completed', trials=trials, termination_reason=reason, repairs_executed=False,
                ambiguous_directions=reconstruct(snapshot).get('ambiguity', []), progress='completed')
            self._save_trial(result)
            return result

    def reconcile(self):
        with self.store.connection() as db:
            db.execute("UPDATE twin_trials SET state='failed',payload_json=json_set(payload_json,'$.state','failed',"
                "'$.error','service interrupted; explicit new trial required') WHERE state='running'")
            ids = [r[0] for r in db.execute("SELECT twin_id FROM twin_instances WHERE state IN ('running','constructing')")]
        for twin_id in ids:
            try:
                cached = self._get_instance(twin_id)
                live = self.agent.twin_status(TwinRequest(twin_id=twin_id))
                self._save_instance(live | {'reconciliation': 'read back on restart; no mutation replayed'}, cached['snapshot_id'])
            except Exception as exc:  # noqa: BLE001 - retain ownership for explicit cleanup
                cached = self._get_instance(twin_id)
                self._save_instance(cached | {'state': 'failed', 'cleanup_error': str(exc)}, cached['snapshot_id'])

    def close(self):
        for twin_id in list(self.owned):
            try:
                self.cancel(TwinRequest(twin_id=twin_id))
                self.destroy(TwinRequest(twin_id=twin_id))
            except Exception as exc:  # noqa: BLE001 - root ownership journal survives failure
                self.store.audit('twin-service', 'twin_close_cleanup_failed', {'error': str(exc)}, subject_id=twin_id)
