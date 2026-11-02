"""Bounded coordinator thread, durable action chain and measured original recovery."""
import json
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

from explainnet.incident_service import IncidentService
from explainnet.network_contracts import InstanceRequest, ProbeRequest
from explainnet.recovery_contracts import RecoveryRequest
from explainnet.recovery_ranking import health, quality, score
from explainnet.recovery_spec import POLICY_HASH
from explainnet.storage import utc_now
from explainnet.telemetry_contracts import ObserveRequest
from explainnet.telemetry_math import receiver_records
from explainnet.twin_contracts import SnapshotRequest
from explainnet.twin_service import TwinCanceled
from explainnet.twin_spec import digest
from explainnet.workflow_contracts import ApplyRequest, LabFinish, LabID, LabPrepare
from explainnet.workflow_spec import WORKFLOW_HASH, WORKFLOW_POLICY


class WorkflowCanceled(RuntimeError):
    pass


class RecoveryCoordinator:
    def __init__(self, worker, test_hooks=False):
        self.worker, self.store, self.agent = worker, worker.store, worker.agent
        self.twins, self.recovery = worker.twins, worker.recovery
        self.incidents = IncidentService(self.store, worker.explanations.definition)
        self.test_hooks = test_hooks
        self.lock = threading.RLock()
        self.thread = None
        self.events = {}
        self.active = None
        self.latest = None
        self.pending_application = None
        self.unsettled = {}
        self.cleanup_pending = {}
        self.watch = None
        self.watch_stop = threading.Event()
        self.watch_thread = None
        self.degraded = False

    def _save(self, w):
        w['updated_utc'] = utc_now()
        with self.store.connection() as db:
            db.execute('INSERT INTO recovery_workflows VALUES(?,?,?,?,?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET '
                'incident_id=excluded.incident_id,state=excluded.state,payload_json=excluded.payload_json',
                (w['workflow_id'], w['request_key'], w['instance_id'], w.get('incident_id'), w['state'],
                    w['created_utc'], json.dumps(w, allow_nan=False)))

    def _state(self, w, state, **data):
        w.update(state=state, **data)
        w.setdefault('history', []).append({'state': state, 'at_utc': utc_now()})
        self._save(w)

    def get(self, workflow_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM recovery_workflows WHERE workflow_id=?', (workflow_id,)).fetchone()
        if not row:
            raise ValueError('unknown recovery workflow')
        result = json.loads(row[0])
        explanation = result.get('explanation') or {}
        if explanation.get('status') == 'pending' and explanation.get('explanation_id'):
            try:
                current = self.worker.explanations.get(explanation['explanation_id'])
                if (current.get('model_id') == (result.get('diagnosis') or {}).get('model_id')
                        and current.get('window_id') == explanation.get('window_id')):
                    result['explanation'] = current
                else:
                    result['explanation'] = explanation | {'status': 'unsupported',
                        'reason': 'Explanation model/window lineage differs from the workflow'}
            except ValueError as exc:
                result['explanation'] = explanation | {'status': 'unsupported', 'reason': str(exc)}
        return result

    def control(self):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM recovery_control WHERE singleton=1').fetchone()
        result = json.loads(row[0]) if row else {'mode': 'recommend', 'auto_enabled': False, 'allow_observed_only': False,
            'policy_version': WORKFLOW_POLICY['version'], 'policy_hash': WORKFLOW_HASH}
        return result | {'auto_enabled': False, 'degraded': True, 'persisted_auto_enabled': result['auto_enabled']} if self.degraded else result

    def mode(self, request):
        with self.lock:
            if self.degraded and request.mode == 'lab-auto-repair':
                raise ValueError('coordinator degraded; automatic mode requires operator reconciliation')
            old = self.control()
            state = {k: v for k, v in old.items() if k not in {'degraded', 'persisted_auto_enabled'}} | {
                'policy_hash': WORKFLOW_HASH, 'policy_version': WORKFLOW_POLICY['version'],
                'mode': request.mode, 'allow_observed_only': request.allow_observed_only,
                'auto_enabled': request.mode == 'lab-auto-repair', 'changed_utc': utc_now()}
            with self.store.connection() as db:
                db.execute('INSERT INTO recovery_control VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET payload_json=excluded.payload_json',
                    (json.dumps(state),))
            self.store.audit('recovery-coordinator', 'mode_changed', {'previous': old, 'current': state})
            return state

    def stop(self):
        from explainnet.workflow_contracts import ModeRequest
        self.watch_stop.set()
        previous = self.control()
        result = self.mode(ModeRequest(mode='recommend' if previous['mode'] == 'lab-auto-repair' else previous['mode'], allow_observed_only=previous.get('allow_observed_only', False)))
        if self.active:
            w = self.get(self.active)
            if w['state'] in {'observing', 'diagnosing', 'validating', 'recommended'}:
                self.cancel(self.active)
        return result | {'new_actuation_prevented': True, 'applied_changes_finish_verification_or_rollback': True}

    def cancel(self, workflow_id):
        w = self.get(workflow_id)
        self.events.setdefault(workflow_id, threading.Event()).set()
        if w.get('experiment_id') and w['state'] == 'validating':
            try:
                self.recovery.cancel(w['experiment_id'])
            except ValueError:
                self.store.audit('recovery-coordinator', 'cancel_before_experiment_registration', {'workflow_id': workflow_id})
        return {'workflow_id': workflow_id, 'cancel_requested': True}

    def busy(self, instance_id=None):
        with self.lock:
            executing = self.active is not None and (instance_id is None or self.get(self.active)['instance_id'] == instance_id)
            return self.degraded or executing or any(instance_id is None or a['instance_id'] == instance_id for a in self.unsettled.values())

    def lifecycle(self):
        with self.lock:
            return {'active_workflow_id': self.active, 'latest_workflow_id': self.latest,
                'execution_active': self.active is not None, 'unsettled_action_ids': list(self.unsettled),
                'cleanup_pending_workflow_ids': list(self.cleanup_pending),
                'monitor_active': bool(self.watch_thread and self.watch_thread.is_alive())}

    def _execute(self, w, target, *args):
        """Release only this worker's lease, after persistence and cleanup finish."""
        try:
            target(w, *args)
        except Exception:
            self.degraded = True
            self.watch_stop.set()
            raise
        finally:
            for cleanup in getattr(self.twins, 'cleanup_threads', []):
                if cleanup.is_alive():
                    cleanup.join(100)
            pending = any(t.is_alive() for t in getattr(self.twins, 'cleanup_threads', []))
            if pending or (w.get('candidate_result') or {}).get('cleanup_error'):
                w['cleanup_pending'] = True
                self.cleanup_pending[w['workflow_id']] = w
                self.degraded = True
                try:
                    self._save(w)
                except Exception as exc:  # noqa: BLE001 - keep degraded ownership even when persistence fails
                    w['cleanup_persistence_error'] = str(exc)
            with self.lock:
                if self.active == w['workflow_id'] and self.thread is threading.current_thread():
                    self.active = None
                    self.pending_application = None

    def _guard(self, w, started):
        if self.degraded or getattr(self.worker, 'storage_error', None):
            raise RuntimeError('storage degraded; original actuation prohibited')
        if self.events[w['workflow_id']].is_set():
            raise WorkflowCanceled('workflow canceled')
        if time.monotonic() - started > w.get('timeout_s', 900):
            raise TimeoutError('bounded workflow timeout')

    def launch(self, request):
        with self.lock:
            if self.degraded or getattr(self.worker, 'storage_error', None):
                raise ValueError('storage degraded; recovery workflow prohibited')
            with self.store.connection() as db:
                row = db.execute('SELECT payload_json FROM recovery_workflows WHERE request_key=? OR workflow_id=?',
                    (request.request_key, request.workflow_id)).fetchone()
            if row:
                old = json.loads(row[0])
                if old['request_hash'] != digest(request.model_dump()):
                    raise ValueError('workflow request key reused with different inputs')
                return old | {'idempotent': True}
            if self.busy():
                raise ValueError('one bounded recovery workflow at a time')
            with self.store.connection() as db:
                recent = db.execute("SELECT payload_json FROM lab_action_state WHERE instance_id=? AND state IN ('succeeded','rolled_back') ORDER BY created_utc DESC LIMIT 1",
                    (request.instance_id,)).fetchone()
            if recent and (datetime.now(UTC) - datetime.fromisoformat(json.loads(recent[0])['ended_utc'])).total_seconds() < WORKFLOW_POLICY['cooldown_s']:
                raise ValueError('laboratory action cooldown active')
            w = request.model_dump() | {'created_utc': utc_now(), 'request_hash': digest(request.model_dump()),
                'state': 'observing', 'incident_id': None, 'history': [], 'policy_hash': WORKFLOW_HASH, 'pre_windows': []}
            self._save(w)
            self.events[request.workflow_id] = threading.Event()
            self.active = request.workflow_id
            self.latest = request.workflow_id
            self.thread = threading.Thread(target=self._execute, args=(w, self._run), name='recovery-coordinator', daemon=False)
            self.thread.start()
            return {'workflow_id': request.workflow_id, 'state': 'observing', 'bounded_background_execution': True}

    def _sample(self, instance_id):
        result = self.twins.capture(instance_id, 10)
        return result['window'], result['capture']['source_after']

    def _observed_incident(self, w, window, view):
        reasons = quality(window, view['workload'])
        if reasons:
            raise ValueError('insufficient fresh incident evidence: ' + str(reasons))
        penalty = health(window, view['workload'], getattr(self.twins, 'objective', None))
        result = {'status': 'supported', 'mode': 'live', 'incident': penalty['penalty'] > 0,
            'service_violations': penalty['service_evidence']['violations'],
            'service_evidence': penalty['service_evidence'],
            'freshness': 'fresh', 'diagnosis': 'observed service violations; classifier not assumed'}
        incident = self.incidents.observe(window, result, 'workflow:' + window['window_id'], context_token=view['ownership']['token'])
        return incident, penalty

    def _run(self, w):
        started = time.monotonic()
        w['timings_ms'] = {}
        try:
            self._state(w, 'observing')
            for _ in range(2):
                self._guard(w, started)
                window, view = self._sample(w['instance_id'])
                # Retain unsuitable captures too, including a first-window refusal.
                w['pre_windows'].append(window)
                incident, penalty = self._observed_incident(w, window, view)
                w['incident_id'] = incident or w.get('incident_id')
                w['owner_token'] = view['ownership']['token']
                self._save(w)
                if penalty['penalty'] == 0:
                    self._state(w, 'refused', reasons=['service acceptable; anomaly-only actuation prohibited'])
                    return
            w['timings_ms']['detection_observation'] = (time.monotonic() - started) * 1000
            self._state(w, 'diagnosing')
            diagnosis_started = time.monotonic()
            model = self.worker.diagnosis.status().get('active_model_id')
            if model:
                diag = self.worker.diagnosis.diagnose(model, window['window_id'], 'live')
                explanation = self.worker.explanations.request(model, window['window_id'], 'live')
                w.update(diagnosis=diag, explanation=explanation)
            else:
                w.update(diagnosis={'status': 'observed-only', 'model_id': None, 'health': penalty,
                    'reason': 'production Stage 7 model unavailable'}, explanation={'status': 'unsupported',
                    'reason': 'production SHAP unavailable; topology localization retained in snapshot'})
            if self.control()['mode'] == 'observe':
                self._state(w, 'observing', finished=True, reasons=['observe mode forbids twin testing and actuation'])
                return
            w['timings_ms']['diagnosis_and_explanation_submission'] = (time.monotonic() - diagnosis_started) * 1000
            w['initial_diagnosis'] = w['diagnosis']
            self._guard(w, started)
            snapshot_started = time.monotonic()
            snapshot = self.twins.snapshot(SnapshotRequest(instance_id=w['instance_id'], request_key='s' + uuid4().hex,
                baseline=w['baseline'], policy=w['policy'], duration_s=15, expiry_s=900))['snapshot']
            w['timings_ms']['snapshot_capture'] = (time.monotonic() - snapshot_started) * 1000
            # The primary diagnosis/explanation and candidate lineage now refer
            # to the SAME immutable snapshot observation, not another capture.
            if model:
                diagnosed = time.monotonic()
                w['diagnosis'] = self.worker.diagnosis.diagnose(model, snapshot['window']['window_id'], 'live')
                w['explanation'] = self.worker.explanations.request(model, snapshot['window']['window_id'], 'live')
                w['timings_ms']['snapshot_inference'] = (time.monotonic() - diagnosed) * 1000
                explaining = time.monotonic()
                while w['explanation']['status'] == 'pending' and time.monotonic() - explaining < 20:
                    self._guard(w, started)
                    if self.events[w['workflow_id']].wait(.2):
                        raise WorkflowCanceled('canceled while awaiting explanation')
                    w['explanation'] = self.worker.explanations.get(w['explanation']['explanation_id'])
                if w['explanation'].get('incident_id'):
                    w['incident_id'] = w['explanation']['incident_id']
                w['timings_ms']['explanation_completion_wait'] = (time.monotonic() - explaining) * 1000
            w['measurement_protocol'] = snapshot.get('measurement_protocol', 'legacy_capture_v1')
            w['service_requirements'] = snapshot.get('service_requirements')
            from explainnet.recovery_spec import generate
            from explainnet.twin_spec import reconstruct
            trial_count = (len(generate(snapshot, w['max_repairs'])['candidates']) * 2
                * min(w.get('max_hypotheses', 2), len(reconstruct(snapshot).get('hypotheses', []))))
            required_s = trial_count * 35 + 30 + WORKFLOW_POLICY['max_action_s']
            collector = self.worker.telemetry.status(w['instance_id'])
            owner_view = self.agent.twin_view(InstanceRequest(instance_id=w['instance_id']))
            w['lifetime_budget'] = {'required_s': required_s, 'trial_count': trial_count,
                'collector_remaining_s': collector.get('remaining_s'), 'traffic_remaining_s': owner_view.get('workload_remaining_s'),
                'expiry_extended': False}
            self._save(w)
            if (not collector['live'] or collector.get('remaining_s') is None or collector['remaining_s'] < required_s
                    or owner_view.get('workload_remaining_s') is None or owner_view['workload_remaining_s'] < required_s):
                raise ValueError('declared collector/workload lifetime cannot cover candidate trials and original verification: ' + str(w['lifetime_budget']))
            w.update(snapshot_id=snapshot['snapshot_id'], experiment_id='e' + uuid4().hex)
            self._state(w, 'validating')
            candidate_started = time.monotonic()
            exp = self.recovery.test(RecoveryRequest(twin_id='tw' + uuid4().hex[:16], snapshot_id=w['snapshot_id'],
                operation_id=w['experiment_id'], max_repairs=w['max_repairs'], max_hypotheses=w.get('max_hypotheses', 2),
                repetitions=2, duration_s=15, timeout_s=700))
            w['timings_ms']['candidate_experiment'] = (time.monotonic() - candidate_started) * 1000
            self._guard(w, started)
            exp['lineage'].update(incident_id=w['incident_id'], workflow_id=w['workflow_id'],
                observed_diagnosis=w['diagnosis'], explanation=w['explanation'])
            self.recovery._save(exp)
            w['candidate_result'] = exp
            w['rejection_details'] = exp.get('rejection_details', [])
            if exp['state'] != 'eligible':
                self._state(w, 'refused', reasons=['twin recommendation not eligible: ' + exp['state']])
                return
            if model and (w['diagnosis']['status'] != 'supported' or w['explanation'].get('status') != 'ready'):
                self._state(w, 'refused', reasons=['trained diagnosis/explanation prerequisites did not pass'],
                    rejection_details=w['rejection_details'] + [{'stage': 'diagnosis', 'status': w['diagnosis']['status'],
                        'reasons': w['diagnosis'].get('reasons', []), 'explanation_status': w['explanation']['status']}])
                return
            w['timings_ms']['decision_total'] = (time.monotonic() - started) * 1000
            self._state(w, 'recommended')
            ctl = self.control()
            if ctl['auto_enabled'] and ctl['mode'] == 'lab-auto-repair':
                self._apply(w, ApplyRequest(workflow_id=w['workflow_id'], action_id='a' + uuid4().hex,
                    request_key='auto' + uuid4().hex), automated=True)
        except Exception as exc:  # noqa: BLE001 - preserve explicit failure/refusal/cancellation chain
            if w['state'] not in {'succeeded', 'rolled_back', 'failed', 'interrupted'}:
                self._state(w, 'interrupted' if isinstance(exc, (WorkflowCanceled, TwinCanceled)) else 'refused' if isinstance(exc, ValueError) else 'failed', error=str(exc), canceled=isinstance(exc, (WorkflowCanceled, TwinCanceled)))
        finally:
            w['elapsed_ms'] = (time.monotonic() - started) * 1000
            self._save(w)

    def apply(self, request):
        with self.lock:
            if self.pending_application == request.model_dump():
                return {'workflow_id': request.workflow_id, 'action_id': request.action_id, 'state': 'applying', 'idempotent': True}
            with self.store.connection() as db:
                used = db.execute('SELECT action_id FROM lab_action_state WHERE request_key=?', (request.request_key,)).fetchone()
            if used and used[0] != request.action_id:
                raise ValueError('application request key already used for a different action')
            old = self.action(request.action_id, optional=True)
            if old:
                if old['request_hash'] != digest(request.model_dump()):
                    raise ValueError('action ID reused with different application')
                return old | {'idempotent': True}
            if self.busy():
                raise ValueError('workflow still running')
            w = self.get(request.workflow_id)
            self.active = w['workflow_id']
            self.latest = w['workflow_id']
            self.pending_application = request.model_dump()
            self.events[w['workflow_id']] = threading.Event()
            self.thread = threading.Thread(target=self._execute, args=(w, self._apply, request), name='original-verification', daemon=False)
            self.thread.start()
            return {'workflow_id': w['workflow_id'], 'action_id': request.action_id, 'state': 'applying'}

    def action(self, action_id, optional=False):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM lab_action_state WHERE action_id=?', (action_id,)).fetchone()
        if not row and not optional:
            raise ValueError('unknown laboratory action')
        return json.loads(row[0]) if row else None

    def _save_action(self, a):
        with self.store.connection() as db:
            db.execute('UPDATE actions SET payload_json=? WHERE id=?', (json.dumps(a, allow_nan=False), a['action_id']))
            db.execute('INSERT INTO lab_action_state VALUES(?,?,?,?,?,?) ON CONFLICT(action_id) DO UPDATE SET '
                'state=excluded.state,payload_json=excluded.payload_json', (a['action_id'], a['request_key'], a['instance_id'],
                a['state'], a['created_utc'], json.dumps(a, allow_nan=False)))

    def eligibility(self, workflow_id):
        """Read-only preview of the existing application gates; never authorizes actuation."""
        if self.busy():
            return {'available': False, 'reason': 'A recovery workflow or verification is still active.'}
        try:
            self._eligible(self.get(workflow_id), False, persist_explanation=False)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            return {'available': False, 'reason': str(exc)}
        return {'available': True, 'reason': 'Current prerequisites pass. Application independently rechecks fresh service, ownership and versions.'}

    def _eligible(self, w, automated, persist_explanation=True):
        if w['state'] != 'recommended':
            raise ValueError('workflow has no currently applicable recommendation')
        ctl = self._mode_gate(automated)
        if w['diagnosis']['status'] == 'observed-only' and not ctl['allow_observed_only']:
            raise ValueError('model/SHAP prerequisite missing; explicit observed-only laboratory opt-in required')
        if w.get('explanation',{}).get('status') == 'pending' and w['explanation'].get('explanation_id'):
            current = self.worker.explanations.get(w['explanation']['explanation_id'])
            if (current.get('model_id') != w['diagnosis'].get('model_id')
                    or current.get('window_id') != w['explanation'].get('window_id')):
                raise ValueError('completed explanation lineage differs from the workflow diagnosis')
            w['explanation'] = current
            if persist_explanation:
                self._save(w)
        if w['diagnosis']['status'] != 'observed-only' and (w['diagnosis']['status'] != 'supported'
                or w['explanation'].get('status') != 'ready'):
            raise ValueError('diagnosis/explanation uncertainty prevents application')
        exp = self.recovery.get(w['experiment_id'])
        if exp['state'] != 'eligible' or exp['recommendation']['status'] != 'eligible':
            raise ValueError('uncertain/stale/poor-fidelity recommendation refused')
        if w['policy_hash'] != WORKFLOW_HASH:
            raise ValueError('workflow policy version changed')
        if exp['policy_hash'] != POLICY_HASH or self.recovery.freshness(self.twins.get_snapshot(w['snapshot_id'])):
            raise ValueError('material configuration/policy/workload drift')
        current_model = self.worker.diagnosis.status().get('active_model_id')
        if current_model != w['diagnosis'].get('model_id'):
            raise ValueError('model version changed')
        incident = self.incidents.get(w['incident_id'])
        if incident['state'] != 'open':
            raise ValueError('incident no longer requires intervention')
        with self.store.connection() as db:
            attempts = db.execute('SELECT count(*) FROM actions WHERE incident_id=?', (w['incident_id'],)).fetchone()[0]
        if attempts >= WORKFLOW_POLICY['max_attempts_per_incident']:
            raise ValueError('bounded incident attempt limit reached')
        candidate = next(c for c in exp['candidates'] if c['candidate_id'] == exp['recommendation']['selected_candidate_id'])
        return exp, candidate

    def _mode_gate(self, automated, observed_only=False):
        if self.degraded:
            raise ValueError('coordinator degraded; operator reconciliation required')
        ctl = self.control()
        if ((automated and (not ctl['auto_enabled'] or ctl['mode'] != 'lab-auto-repair'))
                or (not automated and ctl['mode'] != 'assisted-repair')):
            raise ValueError('operating mode forbids application')
        if observed_only and not ctl['allow_observed_only']:
            raise ValueError('observed-only laboratory exception revoked before actuation')
        return ctl

    def _resolve(self, w, a):
        # Different forwarding context after a repair must resolve the SAME
        # observed incident, using fresh service evidence, not a new context key.
        incident = self.incidents.get(w['incident_id'])
        incident.pop('history', None)
        incident.pop('explanations', None)
        incident.update(state='resolved', resolved_utc=utc_now(), service_status='recovered through active repair',
            resolution_evidence=[p['window']['window_id'] for p in a['post_windows']], action_id=a['action_id'],
            physical_impairment_removed=False)
        with self.store.connection() as db:
            db.execute('UPDATE incident_state SET state=?,last_observation_utc=?,payload_json=? WHERE incident_id=?',
                ('resolved', incident['resolved_utc'], json.dumps(incident), incident['incident_id']))
            db.execute('UPDATE incidents SET payload_json=? WHERE id=?', (json.dumps(incident), incident['incident_id']))
        self.store.audit('recovery-coordinator', 'incident_recovered_by_active_repair', incident, subject_id=incident['incident_id'])

    def _transient(self, a):
        """Retain whole native intervals overlapping actuation, never prorate them."""
        try:
            applied = a.get('application') or self.agent.lab_status(LabID(action_id=a['action_id']))
            begin, end = applied.get('application_started_monotonic_s'), applied.get('application_ended_monotonic_s')
            observation = self.agent.telemetry_observe(ObserveRequest(instance_id=a['instance_id'],
                since_utc=a['created_utc'], live_receivers=True, probe_count=1))
            intervals = [r for r in receiver_records(observation, 'action' + a['action_id']) if r['valid']
                and begin is not None and end is not None and r['start_monotonic_s'] < end and r['end_monotonic_s'] > begin]
            metrics = {}
            for r in intervals:
                key = r['source_host'] + '->' + r['target_host']
                entry = metrics.setdefault(key, {'bytes': 0, 'duration_s': 0, 'packets': 0, 'lost_packets': 0})
                for name in entry:
                    entry[name] += r[name]
            for entry in metrics.values():
                entry['goodput_bps'] = 8 * entry['bytes'] / entry['duration_s']
                entry['loss_fraction'] = entry['lost_packets'] / entry['packets'] if entry['packets'] else None
            return {'application_started_monotonic_s': begin, 'application_ended_monotonic_s': end,
                'native_intervals': intervals, 'metrics': metrics or None, 'observation': observation,
                'resolution': 'whole native intervals overlapping application; includes adjacent traffic, no sub-interval loss claim',
                'status': 'measured' if intervals else 'unavailable',
                'reason': None if intervals else 'no complete native interval overlapping recorded application bounds'}
        except Exception as exc:  # noqa: BLE001 - missing disruption data never becomes zero loss
            return {'status': 'unavailable', 'metrics': None, 'reason': str(exc)}

    def _apply(self, w, request, automated=False):
        a = None
        verification_started = None
        started = time.monotonic()
        try:
            if request.test_hook and not self.test_hooks:
                raise ValueError('test-only failure hooks disabled')
            exp, candidate = self._eligible(w, automated)
            snapshot = self.twins.get_snapshot(w['snapshot_id'])
            pre, _view = self._sample(w['instance_id'])
            if _view.get('workload_remaining_s') is not None and _view['workload_remaining_s'] < WORKFLOW_POLICY['max_action_s'] + 10:
                raise ValueError('remaining workload lifetime cannot cover bounded original verification/rollback')
            if quality(pre, snapshot['workload']) or health(pre, snapshot['workload'], snapshot['policy']['objective'])['penalty'] == 0:
                raise ValueError('fresh service does not justify intervention or evidence insufficient')
            if self.recovery.freshness(snapshot):
                raise ValueError('stale after fresh pre-action measurement')
            self._guard(w, started)
            # Recheck stop immediately at actuation boundary.
            self._mode_gate(automated, w['diagnosis']['status'] == 'observed-only')
            a = {'action_id': request.action_id, 'request_key': request.request_key, 'request_hash': digest(request.model_dump()),
                'instance_id': w['instance_id'], 'incident_id': w['incident_id'], 'workflow_id': w['workflow_id'],
                'created_utc': utc_now(), 'state': 'applying', 'root_journal': None, 'logical_diff': candidate['logical_diff'],
                'pre_window': pre, 'post_windows': [], 'snapshot_id': w['snapshot_id'], 'policy_hash': WORKFLOW_HASH,
                'lineage': exp['lineage'], 'candidate_id': candidate['candidate_id'], 'automated': automated}
            self.store.insert_record('actions', a['action_id'], a, incident_id=w['incident_id'], snapshot_id=w['snapshot_id'])
            self._save_action(a)
            self._state(w, 'applying', action_id=a['action_id'])
            # Register the action before the root prepare RPC: a lost reply or
            # process crash must still leave an ID for startup reconciliation.
            a['root_journal'] = self.agent.lab_prepare(LabPrepare(instance_id=w['instance_id'], action_id=request.action_id,
                idempotency_key=request.request_key, snapshot=snapshot, action=candidate['action'], test_hook=request.test_hook))
            self._save_action(a)
            self._guard(w, started)
            self._mode_gate(automated, w['diagnosis']['status'] == 'observed-only')
            a['application'] = self.agent.lab_apply(LabID(action_id=a['action_id']))
            self._save_action(a)
            if request.test_hook == 'interrupt_after_apply':
                a.update(state='interrupted', interruption='explicit test-only crash boundary after root acknowledgement')
                self._save_action(a)
                self._state(w, 'interrupted')
                self.unsettled[a['action_id']] = a
                return
            a['state'] = 'verifying'
            verification_started = time.monotonic()
            self._save_action(a)
            self._state(w, 'verifying')
            if self.events[w['workflow_id']].wait(WORKFLOW_POLICY['settle_s']):
                raise WorkflowCanceled('canceled after application; rollback required')
            a['transient_disruption'] = self._transient(a)
            self._save_action(a)
            for _ in range(2):
                self._guard(w, started)
                if time.monotonic() - started > WORKFLOW_POLICY['max_action_s']:
                    raise TimeoutError('post-action verification timeout')
                outcome, after = self._sample(w['instance_id'])
                if time.monotonic() - started > WORKFLOW_POLICY['max_action_s']:
                    raise TimeoutError('post-action verification timeout')
                evaluated = score(pre, outcome, candidate, snapshot['workload'], snapshot['policy']['objective'])
                predicted = [t['window'] for t in exp['trials'] if t['candidate_id'] == candidate['candidate_id'] and t['state'] == 'measured']
                row = {'window': outcome, 'evaluation': evaluated, 'predicted_rtt_mean_ms': [p['features']['rtt_mean_ms'] for p in predicted],
                    'observed_rtt_mean_ms': outcome['features']['rtt_mean_ms']}
                a['post_windows'].append(row)
                self._save_action(a)
                if not evaluated['eligible'] or evaluated['score'] <= .05:
                    raise ValueError('actual original performance/quality/protected service verification failed')
                expected = a['application']['after']['view']
                if after['fingerprint'] != expected['fingerprint'] or after['ownership']['token'] != w['owner_token']:
                    raise ValueError('material invalidation during original verification')
                if datetime.now(UTC) >= datetime.fromisoformat(snapshot['expires_utc']):
                    raise ValueError('recommendation expired during verification')
            a['connectivity'] = self.agent.network_probe(ProbeRequest(instance_id=w['instance_id'], source_host='h1', target_host='h3'))
            if not a['connectivity']['passed']:
                raise ValueError('post-repair connectivity failed')
            self._guard(w, started)
            if time.monotonic() - started > WORKFLOW_POLICY['max_action_s']:
                raise TimeoutError('post-action verification timeout')
            a['kept'] = self.agent.lab_finish(LabFinish(action_id=a['action_id']))
            a['verification_ms'] = (time.monotonic() - verification_started) * 1000
            a.update(state='succeeded', ended_utc=utc_now(), elapsed_ms=(time.monotonic() - started) * 1000)
            self._save_action(a)
            self._resolve(w, a)
            self._state(w, 'succeeded', action_result=a)
        except Exception as exc:  # noqa: BLE001 - every partial action is restored, never silently kept
            if a:
                if verification_started is not None:
                    a['verification_ms'] = (time.monotonic() - verification_started) * 1000
                a.update(state='rolling_back', error=str(exc))
                self._failure_record(w, a, 'rolling_back')
                try:
                    a['rollback'] = self.agent.lab_rollback(LabID(action_id=a['action_id']))
                    a['transient_disruption'] = self._transient(a)
                    a.update(state='rolled_back', ended_utc=utc_now())
                    self._failure_record(w, a, 'rolled_back', reasons=[str(exc)])
                except Exception as rollback:  # noqa: BLE001
                    a.update(state='failed', degraded=True, rollback_error=str(rollback), ended_utc=utc_now())
                    self.degraded = True
                    self.unsettled[a['action_id']] = a
                    self.watch_stop.set()
                    try:
                        self.stop()
                    except Exception as storage:  # noqa: BLE001 - root restoration never depends on SQLite
                        a['control_persistence_error'] = str(storage)
                    self._failure_record(w, a, 'failed', degraded=True, error=str(rollback))
            else:
                self._state(w, 'refused', reasons=[str(exc)])

    def _failure_record(self, w, a, state, **fields):
        try:
            self._save_action(a)
            self._state(w, state, **fields)
        except Exception as storage:  # noqa: BLE001 - do not let a database failure skip root rollback
            self.degraded = True
            self.watch_stop.set()
            a.setdefault('persistence_errors', []).append(str(storage))
            w.update(state=state, **fields)

    def undo(self, request):
        with self.lock:
            if self.busy():
                raise ValueError('cannot undo during active workflow')
            with self.store.connection() as db:
                previous = db.execute("SELECT payload_json FROM lab_action_state WHERE json_extract(payload_json,'$.undo_request_key')=?",
                    (request.request_key,)).fetchone()
                if previous:
                    old = json.loads(previous[0])
                    if old['instance_id'] != request.instance_id or (request.action_id and request.action_id != old['action_id']):
                        raise ValueError('undo request key reused for a different target')
                    return old | {'idempotent': True}
                row = db.execute("SELECT payload_json FROM lab_action_state WHERE instance_id=? AND state='succeeded' ORDER BY created_utc DESC LIMIT 1",
                    (request.instance_id,)).fetchone()
            if not row:
                raise ValueError('no applicable successful action to undo')
            a = json.loads(row[0])
            if request.action_id and request.action_id != a['action_id']:
                raise ValueError('Undo Last only accepts the latest applicable action')
            self.active = a['workflow_id']
        try:
            a['undo'] = self.agent.lab_rollback(LabID(action_id=a['action_id']))
            a.update(state='rolled_back', ended_utc=utc_now(), undo_request_key=request.request_key)
            self._save_action(a)
            w = self.get(a['workflow_id'])
            self._state(w, 'rolled_back', undo=True)
            self.store.audit('recovery-coordinator', 'undo_last_lab_action', {'action_id': a['action_id'], 'request_key': request.request_key})
            return a
        except Exception:
            self.unsettled[a['action_id']] = a
            self.degraded = True
            raise
        finally:
            with self.lock:
                if self.active == a['workflow_id']:
                    self.active = None

    def reconcile(self):
        from explainnet.workflow_contracts import ModeRequest
        previous = self.control()
        self.mode(ModeRequest(mode='recommend' if previous['mode'] == 'lab-auto-repair' else previous['mode']))  # No restart actuation.
        with self.store.connection() as db:
            actions = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM lab_action_state WHERE state IN ('applying','verifying','rolling_back','interrupted') OR (state='failed' AND json_extract(payload_json,'$.degraded')=1)")]
            workflows = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM recovery_workflows WHERE state IN ('observing','diagnosing','validating','applying','verifying','rolling_back') OR json_extract(payload_json,'$.cleanup_pending')=1")]
        self.unsettled = {}
        for a in actions:
            a['reconciliation'] = 'interrupted; no application replay or inferred success'
            try:
                actual = self.agent.lab_status(LabID(action_id=a['action_id']))
                a['root_readback'] = actual
                if actual['state'] == 'rolled_back':
                    a.update(state='rolled_back', degraded=False, ended_utc=utc_now())
                else:
                    a.update(state='interrupted', degraded=True)
            except Exception as exc:  # noqa: BLE001
                a.update(state='interrupted', degraded=True, reconciliation_error=str(exc))
            if a.get('degraded'):
                self.unsettled[a['action_id']] = a
            self._save_action(a)
            self._state(self.get(a['workflow_id']), a['state'], interrupted=True)
        self.cleanup_pending = {}
        for w in workflows:
            if w.get('cleanup_pending'):
                try:
                    from explainnet.twin_contracts import TwinRequest
                    experiment = w.get('candidate_result') or self.recovery.get(w['experiment_id'], current=False)
                    actual = self.agent.twin_status(TwinRequest(twin_id=experiment['twin_id']))
                    if actual['state'] != 'destroyed':
                        raise ValueError('owned twin cleanup remains unfinished')
                    w['cleanup_pending'] = False
                    self._save(w)
                except Exception:  # noqa: BLE001 - uncertainty retains ownership, never replays cleanup
                    self.cleanup_pending[w['workflow_id']] = w
            if self.get(w['workflow_id'])['state'] not in {'rolled_back', 'failed'}:
                self._state(w, 'interrupted', reasons=['process restarted; workflow not replayed'])
        self.degraded = bool(self.unsettled or self.cleanup_pending)
        with self.store.connection() as db:
            latest = db.execute('SELECT workflow_id FROM recovery_workflows ORDER BY rowid DESC LIMIT 1').fetchone()
        self.latest = latest[0] if latest else None
        return self.lifecycle()

    def reconcile_action(self, action_id):
        """Explicit operator rollback of an interrupted action, never a GET/startup side effect."""
        with self.lock:
            if self.active:
                raise ValueError('execution still active; wait for verification/rollback')
            a = self.action(action_id)
            if action_id not in self.unsettled:
                raise ValueError('action is not awaiting reconciliation')
            w = self.get(a['workflow_id'])
            self.active = w['workflow_id']
        try:
            a['rollback'] = self.agent.lab_rollback(LabID(action_id=action_id))
            a.update(state='rolled_back', degraded=False, ended_utc=utc_now())
            self._save_action(a)
            self._state(w, 'rolled_back', operator_reconciliation=True)
            self.unsettled.pop(action_id, None)
            self.degraded = bool(self.unsettled or self.cleanup_pending)
            return a
        finally:
            with self.lock:
                if self.active == w['workflow_id']:
                    self.active = None

    def automation_start(self, request):
        if not self.control()['auto_enabled']:
            raise ValueError('explicit lab-auto-repair mode enable required')
        if self.watch_thread and self.watch_thread.is_alive():
            raise ValueError('automation monitor already active')
        self.watch = request
        self.watch_stop.clear()
        self.watch_thread = threading.Thread(target=self._watch_loop, name='lab-automation-monitor', daemon=False)
        self.watch_thread.start()
        return {'watching': request.instance_id, 'auto_enabled': True}

    def _watch_loop(self):
        seen = set()
        while not self.watch_stop.wait(1):
            if not self.control()['auto_enabled']:
                return
            if self.busy():
                continue
            windows = self.worker.telemetry.windows(self.watch.instance_id, 1, True)
            values = windows.get('windows', []) if isinstance(windows, dict) else windows
            if not values or values[0]['window_id'] in seen:
                continue
            window = values[0]
            seen.add(window['window_id'])
            try:
                age = (datetime.now(UTC) - datetime.fromisoformat(window['at_utc'])).total_seconds()
                if not 0 <= age <= 30:
                    raise ValueError('automation requires a telemetry window no older than 30 seconds')
                view = self.agent.twin_view(InstanceRequest(instance_id=self.watch.instance_id))
                if not quality(window, view['workload']) and health(window, view['workload'], getattr(self.twins, 'objective', None))['penalty'] > 0:
                    self.launch(self.watch.model_copy(update={'workflow_id': 'w' + uuid4().hex, 'request_key': 'watch' + uuid4().hex}))
            except Exception as exc:  # noqa: BLE001 - bounded attempts/cooldown refuse, not endless actuation
                self.store.audit('lab-automation', 'window_refused', {'window_id': window['window_id'], 'reason': str(exc)})

    def close(self):
        if self.store.healthy():
            self.stop()
        else:
            self.watch_stop.set()
        if self.thread and self.thread.is_alive():
            self.events[self.active].set()
            self.thread.join(100)
        if self.watch_thread:
            self.watch_thread.join(5)
        return not self.busy()
