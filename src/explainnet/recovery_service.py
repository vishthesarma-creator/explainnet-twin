"""Durable sequential twin experiments. No original mutation or model training."""
import json
import random
import threading
import time
from datetime import UTC, datetime

from explainnet.network_contracts import InstanceRequest
from explainnet.recovery_contracts import AgentRecoveryAction
from explainnet.recovery_ranking import rank
from explainnet.recovery_spec import POLICY, POLICY_HASH, generate
from explainnet.rejection_details import experiment_rejections
from explainnet.storage import utc_now
from explainnet.twin_contracts import CaptureRequest, ConstructRequest, TwinRequest, TwinResetRequest
from explainnet.twin_fidelity import compare
from explainnet.twin_service import TwinCanceled
from explainnet.twin_spec import digest, obsolete, reconstruct


class RecoveryService:
    def __init__(self, twins):
        self.twins, self.store, self.agent = twins, twins.store, twins.agent
        self.events = {}
        self.lock = threading.Lock()

    def _save(self, result):
        with self.store.connection() as db:
            db.execute('INSERT INTO recovery_experiments VALUES(?,?,?,?,?,?) ON CONFLICT(operation_id) DO UPDATE SET '
                'state=excluded.state,payload_json=excluded.payload_json', (result['operation_id'], result['snapshot_id'],
                result['twin_id'], result['state'], result['created_utc'], json.dumps(result, allow_nan=False)))

    def get(self, operation_id, current=True):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM recovery_experiments WHERE operation_id=?', (operation_id,)).fetchone()
        if not row:
            raise ValueError('unknown recovery experiment')
        result = json.loads(row[0])
        if current and result['state'] in {'eligible', 'uncertain', 'no-safe-repair'}:
            snapshot = self.twins.get_snapshot(result['snapshot_id'])
            try:
                reasons = self.freshness(snapshot)
            except Exception as exc:  # noqa: BLE001 - unavailable ownership is not current eligibility
                reasons = ['original ownership unavailable: ' + str(exc)]
            if reasons:
                result.update(state='stale', current_reasons=reasons, historical_state=result['state'])
                result['recommendation'] = result['recommendation'] | {'status': 'stale', 'selected_candidate_id': None}
        return result

    def freshness(self, snapshot):
        try:
            view = self.agent.twin_view(InstanceRequest(instance_id=snapshot['original_instance_id']))
        except (ValueError, RuntimeError) as exc:
            return ['original ownership unavailable: ' + str(exc)]
        reasons = obsolete(snapshot, view)
        for key in ('agent_epoch', 'forwarding_version', 'workload_config_versions'):
            if view.get(key) != snapshot['provenance'].get(key):
                reasons.append('original version changed: ' + key)
        return reasons

    def plan(self, request):
        snapshot = self.twins.get_snapshot(request.snapshot_id)
        if request.twin_id == snapshot['original_instance_id']:
            raise ValueError('original target forbidden; candidate execution requires a separate twin ID')
        result = generate(snapshot, request.max_repairs)
        result.update(snapshot_id=request.snapshot_id, reconstruction=reconstruct(snapshot), stale_reasons=self.freshness(snapshot))
        return result

    def cancel(self, operation_id):
        result = self.get(operation_id, current=False)
        if result['state'] != 'running':
            return {'operation_id': operation_id, 'cancel_requested': False, 'state': result['state']}
        self.events.setdefault(operation_id, threading.Event()).set()
        try:
            self.agent.twin_cancel(TwinRequest(twin_id=result['twin_id']))
        except Exception as exc:  # noqa: BLE001 - cancellation also works before construction registers root ownership
            self.store.audit('recovery-service', 'cancel_pending', {'error': str(exc)}, subject_id=operation_id)
        return {'operation_id': operation_id, 'cancel_requested': True, 'original_modified': False}

    def reconcile(self):
        with self.store.connection() as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM recovery_experiments WHERE state='running'")]
        for result in rows:
            result.update(state='failed', progress='interrupted; explicit new experiment required',
                error='service restart; partial trials cannot support a recommendation')
            self._save(result)

    def test(self, request):
        with self.lock:
            return self._test(request)

    def _test(self, request):
        request_hash = digest(request.model_dump())
        try:
            old = self.get(request.operation_id, current=False)
        except ValueError:
            old = None
        if old:
            if old['request_hash'] != request_hash:
                raise ValueError('recovery operation ID reused with different inputs')
            return old | {'idempotent': True}
        snapshot = self.twins.get_snapshot(request.snapshot_id)
        if request.twin_id == snapshot['original_instance_id']:
            raise ValueError('original target forbidden')
        generated = generate(snapshot, request.max_repairs)
        plan = reconstruct(snapshot)
        hypotheses = plan.get('hypotheses', [])[:request.max_hypotheses]
        unresolved = len(plan.get('hypotheses', [])) > len(hypotheses) or bool(plan.get('untried_directions'))
        # Fixed conservative budget includes reset/isolation/warmup and durable
        # ingestion. Budget is checked before construction; expiry never renewed.
        count = len(generated['candidates']) * request.repetitions * len(hypotheses)
        estimated_s = count * (request.duration_s + 20) + 30
        result = {'operation_id': request.operation_id, 'snapshot_id': request.snapshot_id, 'twin_id': request.twin_id,
            'snapshot_hash': snapshot['snapshot_hash'], 'created_utc': utc_now(), 'request_hash': request_hash,
            'request': request.model_dump(), 'state': 'running', 'progress': 'checking freshness and experiment budget',
            'policy_version': POLICY['version'], 'policy_hash': POLICY_HASH, **generated,
            'lineage': {'incident_id': None, 'diagnosis_window_id': snapshot['window']['window_id'],
                'diagnosis': snapshot['diagnosis'], 'model_id': snapshot['diagnosis'].get('model_id'),
                'fidelity_policy_hash': snapshot['policy']['policy_hash']},
            'hypotheses': hypotheses, 'unresolved_hypotheses': unresolved,
            'untried_directions': plan.get('untried_directions', []), 'retained_ambiguity': plan.get('ambiguity', []),
            'trials': [], 'failures': [],
            'budget': {'estimated_s': estimated_s, 'trial_count': count, 'timeout_s': request.timeout_s,
                'snapshot_expires_utc': snapshot['expires_utc'], 'retries': 0},
            'original_repaired': False, 'sealed_test_accessed': False}
        with self.store.connection() as db:
            explanation = db.execute('SELECT payload_json FROM explanations WHERE window_id=? ORDER BY created_utc DESC LIMIT 1',
                (snapshot['window']['window_id'],)).fetchone()
        if explanation:
            payload = json.loads(explanation[0])
            result['lineage'].update(incident_id=payload.get('incident_id'), diagnosis_id=payload.get('diagnosis_id'),
                explanation_id=payload.get('explanation_id'))
        else:
            result['lineage'].update(diagnosis_id=None, explanation_id=None,
                limitation='No persisted incident/model explanation for this observed snapshot; heuristic experiment only')
        self._save(result)
        for c in generated['candidates']:
            self.store.insert_record('candidates', request.operation_id + '_' + c['candidate_id'], c, snapshot_id=request.snapshot_id)
        started = time.monotonic()
        event = self.events.setdefault(request.operation_id, threading.Event())
        owned = False

        def guard():
            if event.is_set():
                raise TwinCanceled('recovery experiment canceled')
            if time.monotonic() - started > request.timeout_s:
                raise TimeoutError('bounded recovery job timeout')
            reasons = self.freshness(snapshot)
            if reasons:
                raise ValueError('stale: ' + '; '.join(reasons))

        def save_progress(text):
            result['progress'] = text
            result['elapsed_ms'] = (time.monotonic() - started) * 1000
            self._save(result)

        try:
            guard()
            if not hypotheses or plan['status'] != 'supported':
                result.update(state='unsupported', reasons=plan.get('reasons', [plan.get('reason', 'unsupported reconstruction')]))
                return result
            remaining = (datetime.fromisoformat(snapshot['expires_utc']) - datetime.now(UTC)).total_seconds()
            if estimated_s > remaining or estimated_s > request.timeout_s:
                result.update(state='insufficient-evidence', reasons=['finite snapshot/job lifetime cannot accommodate the requested bounded experiment'])
                return result
            # Construct verifies unique root registry ownership. Subsequent reset
            # recreates traffic, forwarding, shaping and impairment every time.
            construction_started = time.monotonic()
            self.twins.construct(ConstructRequest(twin_id=request.twin_id, snapshot_id=request.snapshot_id,
                hypothesis_id=hypotheses[0]['hypothesis_id']))
            result['twin_construction_ms'] = (time.monotonic() - construction_started) * 1000
            owned = True
            rng = random.Random(request.seed)
            order = []
            for h in hypotheses:
                for repetition in range(request.repetitions):
                    repairs = list(generated['candidates'][1:])
                    rng.shuffle(repairs)
                    # A matched fresh-runtime no-change anchors each block.
                    order.extend((h['hypothesis_id'], repetition, c) for c in [generated['candidates'][0], *repairs])
            result['randomized_order'] = [{'hypothesis_id': h, 'repetition': r, 'candidate_id': c['candidate_id']} for h, r, c in order]
            result['seed'] = request.seed
            for index, (hypothesis, repetition, candidate) in enumerate(order):
                guard()
                trial_started = time.monotonic()
                t = {'trial_id': request.operation_id + '_' + str(index), 'candidate_id': candidate['candidate_id'],
                    'hypothesis_id': hypothesis, 'repetition': repetition, 'family': candidate['action']['family'],
                    'state': 'running', 'created_utc': utc_now()}
                result['trials'].append(t)
                save_progress(f'trial {index + 1}/{count}: reset, warmup, {t["family"]}')
                try:
                    reset_started = time.monotonic()
                    reset = self.twins.reset(TwinResetRequest(twin_id=request.twin_id, hypothesis_id=hypothesis))
                    t['reset_ms'] = (time.monotonic() - reset_started) * 1000
                    t['reset'] = {'runtime_token': reset['ownership']['token'], 'snapshot_hash': reset['snapshot_hash'],
                        'hypothesis_id': reset['hypothesis_id'], 'state': reset['state']}
                    guard()
                    application_started = time.monotonic()
                    application = self.agent.twin_apply_candidate(AgentRecoveryAction(twin_id=request.twin_id,
                        snapshot_hash=snapshot['snapshot_hash'], action=candidate['action']))
                    t['candidate_application_ms'] = (time.monotonic() - application_started) * 1000
                    t['application'] = application
                    save_progress(f'trial {index + 1}/{count}: action applied; matched capture')
                    # Allow the rerouted path/class to settle with unchanged offered demand.
                    if event.wait(1):
                        raise TwinCanceled('recovery experiment canceled')
                    capture_started = time.monotonic()
                    capture = self.agent.twin_capture(CaptureRequest(instance_id=snapshot['original_instance_id'],
                        twin_id=request.twin_id, duration_s=request.duration_s))
                    t['paired_capture_rpc_ms'] = (time.monotonic() - capture_started) * 1000
                    t['capture_elapsed_ms'] = capture.get('elapsed_ms')
                    materialization_started = time.monotonic()
                    left, _ = self.twins.materialize(capture, snapshot['original_instance_id'])
                    right, _ = self.twins.materialize(capture, request.twin_id)
                    t['materialization_ms'] = (time.monotonic() - materialization_started) * 1000
                    t.update(original_window=left, window=right, capture_id=capture['capture_id'])
                    stale = obsolete(snapshot, capture['source_after'])
                    digests = {p['observed_config_hash'] for p in capture['series'][snapshot['original_instance_id']]}
                    expected = snapshot['provenance'].get('observation_config_digest')
                    if len(digests) != 1 or (expected and digests != {expected}):
                        stale.append('original observed configuration digest changed')
                    if capture['source_before']['fingerprint'] != capture['source_after']['fingerprint']:
                        stale.append('original changed during capture')
                    t['original_unchanged'] = not stale
                    if stale:
                        raise ValueError('stale: ' + '; '.join(stale))
                    guard()
                    if t['family'] == 'no_change':
                        fidelity = compare(left, right, snapshot['policy'], snapshot['workload'], snapshot['queue_configuration'])
                        t['fidelity'] = fidelity
                        if fidelity['status'] != 'pass':
                            t.update(state='refused', reasons=['no-change fidelity failed: ' + fidelity['status']])
                            t['elapsed_ms'] = (time.monotonic() - trial_started) * 1000
                            result.update(state='insufficient-evidence', reasons=t['reasons'])
                            save_progress('fidelity refusal; no candidate recommendation')
                            return result
                    t['state'] = 'measured'
                except Exception as exc:
                    t.update(state='canceled' if event.is_set() or isinstance(exc, TwinCanceled) else 'failed', error=str(exc))
                    if not event.is_set() and not isinstance(exc, TwinCanceled):
                        try:
                            failed = self.agent.twin_status(TwinRequest(twin_id=request.twin_id))
                            t['failed_application'] = failed.get('recovery_application')
                        except Exception as inspection:  # noqa: BLE001 - preserve both errors, no retry
                            t['application_inspection_error'] = str(inspection)
                    result['failures'].append({'trial_id': t['trial_id'], 'error': str(exc)})
                    save_progress('trial failed; snapshot restoration required')
                    if event.is_set() or isinstance(exc, TwinCanceled):
                        raise TwinCanceled(str(exc)) from exc
                    if 'stale' in str(exc):
                        raise
                    # Bounded restoration after a failed candidate; no retries.
                    guard()
                    t['failure_restoration'] = self.twins.reset(TwinResetRequest(twin_id=request.twin_id, hypothesis_id=hypothesis))['state']
                finally:
                    t['elapsed_ms'] = (time.monotonic() - trial_started) * 1000
                save_progress(f'trial {index + 1}/{count} completed')
            guard()
            recommendation = rank(generated['candidates'], result['trials'], snapshot['workload'], hypotheses,
                request.repetitions, unresolved, objective=snapshot['policy']['objective'])
            selected = next((c for c in generated['candidates'] if c['candidate_id'] == recommendation['selected_candidate_id']), None)
            recommendation.update(logical_diff=selected['logical_diff'] if selected else [],
                original_logical_instance_id=snapshot['original_instance_id'],
                prerequisites={'snapshot_hash': snapshot['snapshot_hash'], 'source_fingerprint': snapshot['source_fingerprint'],
                    'policy_hash': POLICY_HASH, 'fidelity_policy_hash': snapshot['policy']['policy_hash'],
                    'selected_paths': snapshot['selected_paths'], 'fresh_original_observation_required': True},
                expires_utc=snapshot['expires_utc'], runtime_identifiers_in_logical_diff=False)
            result.update(state=recommendation['status'], recommendation=recommendation)
            return result
        except TwinCanceled as exc:
            result.update(state='canceled', error=str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - durable job status retains partial raw evidence
            result.update(state='stale' if 'stale' in str(exc) else 'failed', error=str(exc))
            return result
        finally:
            if owned:
                try:
                    # Destroying the owned trial leaves no action active. The
                    # next use must reconstruct the same snapshot from scratch.
                    result['cleanup'] = self.twins.destroy(TwinRequest(twin_id=request.twin_id))
                except Exception as exc:  # noqa: BLE001
                    result['cleanup_error'] = str(exc)
                    result['state'] = 'failed'
                    result.pop('recommendation', None)
            if result['state'] in {'eligible', 'uncertain', 'no-safe-repair'}:
                current_reasons = self.freshness(snapshot)
                if current_reasons:
                    result.update(state='stale', reasons=current_reasons)
                    result['recommendation'].update(status='stale', selected_candidate_id=None)
            canceled_before_publication = event.is_set() and result['state'] != 'failed'
            if canceled_before_publication:
                result.update(state='canceled', error='canceled before publication')
                result.pop('recommendation', None)
            result['progress'] = 'finished; no original action applied'
            result['rejection_details'] = experiment_rejections(result)
            result['elapsed_ms'] = (time.monotonic() - started) * 1000
            self._save(result)
            if canceled_before_publication:
                raise TwinCanceled('recovery experiment canceled before publication')
