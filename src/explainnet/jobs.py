"""Single bounded local job worker with durable transitions."""

import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from explainnet.agent import RPC_CONTEXT, AgentClient, AgentUnavailable
from explainnet.contracts import JobState
from explainnet.dataset_contracts import BatchRequest, DatasetRunRequest
from explainnet.dataset_export import export_dataset
from explainnet.dataset_service import DatasetService
from explainnet.diagnosis_service import DiagnosisService
from explainnet.explanation_contracts import ExplanationRequest
from explainnet.explanation_service import ExplanationService
from explainnet.model_contracts import BundleRequest, InferenceRequest, TrainRequest
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    PathRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
)
from explainnet.recovery_contracts import RecoveryRequest
from explainnet.recovery_service import RecoveryService
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.storage import Store, utc_now
from explainnet.telemetry_contracts import CollectorStartRequest, ReferenceRequest
from explainnet.telemetry_service import TelemetryService
from explainnet.twin_contracts import (
    CalibrationRequest,
    ConstructRequest,
    SnapshotRequest,
    TwinMeasureRequest,
    TwinRequest,
    TwinResetRequest,
)
from explainnet.twin_service import TwinCanceled, TwinService
from explainnet.workflow_contracts import ApplyRequest, ModeRequest, UndoRequest, WorkflowRequest
from explainnet.workflow_service import RecoveryCoordinator

Handler = Callable[..., dict[str, Any]]


class UnsupportedJob(ValueError):
    pass


class Worker:
    def __init__(self, store: Store, agent: AgentClient, poll_s: float = 0.2, telemetry_settings=None, objective=None,
                 definition=None, config_hash="", artifact_dir=None, lab_test_hooks=False):
        self.store = store
        self.agent = agent
        self.telemetry = TelemetryService(store, agent, telemetry_settings, objective)
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.storage_error = None
        self.dataset = DatasetService(store, agent, self._submit_dataset, self.telemetry, definition, config_hash, artifact_dir)
        self.diagnosis = DiagnosisService(store, self.telemetry, artifact_dir)
        self.explanations = ExplanationService(store, self.diagnosis, definition)
        self.diagnosis.on_diagnosis = self.explanations.after_diagnosis
        self.twins = TwinService(store, agent, objective, self.diagnosis)
        self.recovery = RecoveryService(self.twins)
        self.coordinator = RecoveryCoordinator(self, lab_test_hooks)
        self.handlers: dict[str, Handler] = {"environment_check": self._environment_check}
        self.operation_types = {
            'demo_reference': InstanceRequest,
            'owner_reconcile': InstanceRequest,
            "network_start": NetworkStartRequest, "network_stop": InstanceRequest, "network_cleanup": InstanceRequest,
            "path_select": PathRequest, "network_probe": ProbeRequest, "traffic_start": TrafficStartRequest,
            "traffic_stop": TrafficRunRequest,
            "scenario_start": ScenarioStartRequest, "scenario_stop": InstanceRequest,
            "scenario_reset": InstanceRequest,
            "collector_start": CollectorStartRequest, "collector_stop": InstanceRequest,
            "telemetry_reference": ReferenceRequest,
            "dataset_plan": DatasetRunRequest, "dataset_start": BatchRequest, "dataset_resume": BatchRequest,
            "dataset_cancel": BatchRequest, "dataset_export": BatchRequest,
            "model_train": TrainRequest, "model_load": BundleRequest, "model_infer": InferenceRequest,
            "explanation_request": ExplanationRequest,
            'workflow_start': WorkflowRequest, 'workflow_apply': ApplyRequest, 'workflow_mode': ModeRequest,
            'workflow_undo': UndoRequest, 'workflow_automation_start': WorkflowRequest,
            'recovery_plan': RecoveryRequest, 'recovery_test': RecoveryRequest,
            'twin_snapshot': SnapshotRequest, 'twin_construct': ConstructRequest,
            'twin_measure': TwinMeasureRequest, 'twin_reset': TwinResetRequest,
            'twin_destroy': TwinRequest, 'twin_calibrate': CalibrationRequest,
        }
        for operation in self.operation_types:
            self.handlers[operation] = lambda payload, op=operation: self._operation(op, payload)

    def reconcile(self) -> None:
        try:
            inventory = self.agent.inventory()
            actual = {r["instance_id"]: r for r in inventory.get("instances", [])}
        except AgentUnavailable:
            actual = {}
        for cached in self.store.list_instances():
            if cached["instance_id"] not in actual:
                self.store.save_instance(cached | {"state": "failed", "live_verified": False,
                                                  "error": "agent could not verify cached ownership"})
        for record in actual.values():
            self.store.save_instance(record)

    def _operation(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = self.operation_types[operation].model_validate(payload)
        if operation == 'demo_reference':
            from explainnet.demo_reference import capture_reference
            return capture_reference(self,request)
        if operation == 'owner_reconcile':
            network = self.agent.network_inspect(request)
            self.store.save_instance(network)
            runs = []
            for run_id in network.get('runs', []):
                actual = self.agent.traffic_status(TrafficRunRequest(instance_id=request.instance_id, run_id=run_id))
                self.store.update_run(run_id, actual)
                runs.append({'run_id': run_id, 'state': actual['state']})
            if network['state'] == 'running':
                self.store.save_scenario_result(self.agent.scenario_inspect(request))
            return {'instance_id': request.instance_id, 'state': network['state'], 'runs': runs,
                'mutations_replayed': False}
        if operation.startswith('workflow_'):
            method = {'start': 'launch', 'apply': 'apply', 'mode': 'mode', 'undo': 'undo', 'automation_start': 'automation_start'}[operation[9:]]
            return getattr(self.coordinator, method)(request)
        if operation.startswith('recovery_'):
            return getattr(self.recovery, operation[9:])(request)
        if operation.startswith('twin_'):
            result = getattr(self.twins, operation[5:])(request)
            if operation == 'twin_destroy' and self.coordinator.cleanup_pending:
                self.coordinator.reconcile()
            return result
        if operation == "explanation_request":
            return self.explanations.request(request.model_id, request.window_id, request.mode)
        if operation == "model_train":
            return self.diagnosis.train(request.batch_id, profile=request.profile)
        if operation == "model_load":
            return self.diagnosis.activate(request.model_id)
        if operation == "model_infer":
            return self.diagnosis.diagnose(request.model_id, request.window_id, request.mode)
        if operation == "dataset_plan":
            return self.dataset.plan(request.schedule.model_dump())
        if operation in {"dataset_start", "dataset_resume"}:
            return self.dataset.start(request.batch_id, resume=operation == "dataset_resume")
        if operation == "dataset_cancel":
            return self.dataset.cancel(request.batch_id)
        if operation == "dataset_export":
            return export_dataset(self.store, request.batch_id)
        if operation == "collector_start":
            return self.telemetry.start(request.instance_id, request.duration_s)
        if operation == "collector_stop":
            return self.telemetry.stop(request.instance_id)
        if operation == "telemetry_reference":
            return self.telemetry.set_reference(request.window_id)
        if operation in {"network_start", "network_stop", "network_cleanup"}:
            self.store.save_instance({"instance_id": request.instance_id,
                                      "state": "starting" if operation == "network_start" else "stopping"})
        try:
            if operation == "scenario_start":
                self.store.save_scenario_result(self.agent.scenario_inspect(InstanceRequest(instance_id=request.instance_id)))
            result = getattr(self.agent, operation)(request)
        except AgentUnavailable as exc:
            # Failed acknowledgement is not proof that the mutation did not happen.
            try:
                actual = self.agent.network_inspect(InstanceRequest(instance_id=request.instance_id))
                self.store.save_instance(actual | {'acknowledgement_error': str(exc), 'outcome': 'read-back; no automatic retry'})
            except (AgentUnavailable, ValueError):
                self.store.audit('api-worker', 'mutation_outcome_unknown', {'operation': operation,
                    'instance_id': request.instance_id, 'error': str(exc), 'automatic_retry': False})
            raise
        if operation in {"network_start", "network_stop", "network_cleanup", "path_select"}:
            self.store.save_instance(result)
        elif operation == "traffic_start":
            self.store.insert_record("runs", result["run_id"], result, config_hash=result["config_hash"])
        elif operation == "traffic_stop":
            self.store.update_run(result["run_id"], result)
        elif operation.startswith("scenario_"):
            self.store.save_scenario_result(result)
        self.store.audit("api-worker", operation, {"instance_id": request.instance_id})
        return result

    def _environment_check(self) -> dict[str, Any]:
        result: dict[str, Any] = {"database": "available" if self.store.healthy() else "unavailable"}
        try:
            result["agent"] = self.agent.health()
            result["agent_status"] = "available"
        except AgentUnavailable as exc:
            result["agent_status"] = "unavailable"
            result["agent_error"] = str(exc)
        result["status"] = "healthy" if result["database"] == "available" and result["agent_status"] == "available" else "degraded"
        return result

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.interrupt_running()
        self.reconcile()
        self.telemetry.reconcile()
        self.dataset.reconcile()
        self.twins.reconcile()
        self.recovery.reconcile()
        self.coordinator.reconcile()
        self.diagnosis.start()
        self.explanations.start()
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET state='canceled',ended_utc=?,error='dataset runner interrupted; explicit resume required' "
                       "WHERE state='queued' AND origin='dataset'", (utc_now(),))
            db.execute("UPDATE jobs SET state='canceled',ended_utc=?,error='service restarted; inspect owned state and submit a new explicit intent' "
                       "WHERE state='queued' AND type!='environment_check'", (utc_now(),))
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="explainnet-worker", daemon=False)
        self._thread.start()

    def submit(self, job_type: str, request_id: str, payload: dict[str, Any] | None = None,
               idempotency_key: str | None = None) -> str:
        if idempotency_key:
            import re
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', idempotency_key):
                raise ValueError('invalid idempotency key')
            old = self.store.idempotent_job(idempotency_key, job_type, payload)
            if old:
                return old
        if self._coordinator_locked(job_type):
            raise UnsupportedJob("recovery coordinator owns laboratory mutations")
        if self._dataset_locked(job_type):
            raise UnsupportedJob("dataset experiment owns laboratory mutations until collection finishes")
        return self._enqueue(job_type, request_id, payload, "external", idempotency_key)

    def _coordinator_locked(self, job_type):
        if job_type == 'twin_destroy' and not self.coordinator.active and not self.coordinator.unsettled and self.coordinator.cleanup_pending:
            return False  # Explicit scoped cleanup may settle an already-finished worker.
        return self.coordinator.busy() and job_type.startswith(("owner_", "network_", "path_", "traffic_", "scenario_", "twin_", "recovery_", "dataset_", "model_", 'collector_'))

    def _dataset_locked(self, job_type):
        mutations = {"network_start", "network_stop", "network_cleanup", "path_select", "network_probe",
            'demo_reference',
            "traffic_start", "traffic_stop", "scenario_start", "scenario_stop", "scenario_reset",
            "collector_start", "collector_stop", "telemetry_reference", "model_train"}
        return self.dataset.thread and self.dataset.thread.is_alive() and (job_type in mutations or job_type.startswith(('twin_', 'recovery_', 'workflow_')))

    def _submit_dataset(self, job_type, request_id, payload):
        return self._enqueue(job_type, request_id, payload, "dataset")

    def _enqueue(self, job_type, request_id, payload, origin, idempotency_key=None):
        if job_type not in self.handlers:
            raise UnsupportedJob(job_type)
        if job_type in self.operation_types:
            self.operation_types[job_type].model_validate(payload)
        job_id = "j" + uuid4().hex
        return self.store.create_job(job_id, job_type, request_id, payload, origin=origin, idempotency_key=idempotency_key)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.store.next_queued()
                self.storage_error = None
            except sqlite3.OperationalError as exc:
                self.storage_error = str(exc)
                self._stop.wait(max(.5, self.poll_s))
                continue  # Expose degraded storage; never replay a claimed job.
            if job is None:
                self._stop.wait(self.poll_s)
                continue
            started = time.monotonic()
            context = RPC_CONTEXT.set(job['id'])
            try:
                if self._coordinator_locked(job['type']):
                    raise UnsupportedJob('queued mutation rejected: recovery coordinator owns laboratory mutations')
                if job["origin"] != "dataset" and self._dataset_locked(job["type"]):
                    raise UnsupportedJob("queued external mutation rejected: dataset experiment lock active")
                handler = self.handlers[job["type"]]
                result = handler() if job["type"] == "environment_check" else handler(job["payload"])
                elapsed_ms = (time.monotonic() - started) * 1000
                self.store.finish_job(job["id"], JobState.succeeded, elapsed_ms, result=result)
            except TwinCanceled as exc:
                self.store.finish_job(job['id'], JobState.canceled, (time.monotonic() - started) * 1000, error=str(exc))
            except AgentUnavailable as exc:
                self.store.finish_job(job['id'], JobState.failed, (time.monotonic() - started) * 1000,
                    result={'outcome': 'unknown', 'requires_reconciliation': True,
                        'next_step': 'read owned state or submit /v1/laboratory/reconcile; no automatic retry'}, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - persist handler failures
                elapsed_ms = (time.monotonic() - started) * 1000
                self.store.finish_job(job["id"], JobState.failed, elapsed_ms, error=str(exc))
            finally:
                RPC_CONTEXT.reset(context)

    def stop(self, timeout_s: float = 100) -> bool:
        self.coordinator.close()
        for event in self.recovery.events.values():
            event.set()
        for twin_id in list(self.twins.owned):
            try:
                self.twins.cancel(TwinRequest(twin_id=twin_id))
            except (AgentUnavailable, ValueError):
                pass
        self.dataset.close(timeout_s)
        self.diagnosis.close()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout_s)
            joined = not self._thread.is_alive()
            if joined:
                self.twins.close()
                self.explanations.close()
                self.telemetry.close()
            return joined
        self.explanations.close()
        return True
