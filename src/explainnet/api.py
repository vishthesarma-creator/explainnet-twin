"""Local FastAPI service for typed laboratory jobs and live agent inspection."""

import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from explainnet import __version__
from explainnet.agent import AgentClient, AgentUnavailable
from explainnet.config import Settings, load_network, load_profiles, load_settings
from explainnet.contracts import Identifier
from explainnet.dataset_contracts import BatchRequest, DatasetRunRequest
from explainnet.explanation_contracts import ExplanationRequest
from explainnet.jobs import Worker
from explainnet.model_contracts import BundleRequest, InferenceRequest, TrainRequest
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkLaunchRequest,
    NetworkStartRequest,
    PathRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    TrafficSubmission,
    WorkloadProfile,
)
from explainnet.response_evidence import CHUNK_BYTES, EvidenceFiles, encoded, projection
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.storage import Store
from explainnet.telemetry_contracts import CollectorStartRequest, ReferenceRequest
from explainnet.twin_contracts import (
    CalibrationRequest,
    ConstructRequest,
    SnapshotRequest,
    TwinMeasureRequest,
    TwinRequest,
    TwinResetRequest,
)


def create_app(settings: Settings) -> FastAPI:
    store = Store(settings.database_path)
    agent = AgentClient(settings.agent_socket)
    worker = Worker(store, agent, telemetry_settings=settings.telemetry, objective=settings.objective,
                    definition=load_network(settings.topology_file) if settings.topology_file else None,
                    config_hash=settings.config_hash, artifact_dir=settings.dataset_artifact_dir, lab_test_hooks=settings.lab_test_hooks)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if store.healthy():
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="ExplainNet Twin", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.worker = worker
    read_evidence = EvidenceFiles(settings.runtime_dir / 'read_evidence')

    def bounded_read(value):
        if len(encoded(value)) <= 512 * 1024:
            return value
        ref = read_evidence.put(value, read_only=True)
        return projection(value) | {'response_schema_version': 2, 'evidence': ref,
            'evidence_retrieval': '/v1/evidence/' + ref['sha256']}

    @app.get('/v1/evidence/{sha256}')
    def read_evidence_page(sha256: str, request: Request, offset: int = Query(default=0, ge=0)):
        try:
            return read_evidence.page(sha256, offset)
        except (OSError, ValueError) as exc:
            return error(request, 404, 'evidence_unavailable', str(exc) + '; refresh the source if its read cache expired')

    def error(request: Request, status: int, code: str, message: str, incident_id: str | None = None) -> JSONResponse:
        if status >= 500 and incident_id is None:
            incident_id = "e" + uuid4().hex
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "request_id": request.state.request_id,
            "incident_id": incident_id,
        }})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _exc: RequestValidationError):
        return error(request, 422, "invalid_request", "request does not match the operation schema")

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = supplied if supplied and len(supplied) <= 64 and supplied.isascii() and supplied.isprintable() else uuid4().hex
        try:
            response = await call_next(request)
        except (sqlite3.Error, OSError) as exc:
            response = error(request, 503, "dependency_unavailable", str(exc))
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.get("/v1/health")
    def health(request: Request):
        db_ok = store.healthy()
        try:
            agent_health = agent.health()
            agent_ok = True
        except AgentUnavailable:
            agent_ok = False
            agent_health = {}
        worker_ok = bool(worker._thread and worker._thread.is_alive()) and not worker.storage_error
        status = "unavailable" if not db_ok else "healthy" if agent_ok and worker_ok else "degraded"
        return JSONResponse(status_code=503 if status == "unavailable" else 200, content={
            "status": status, "database": "available" if db_ok else "unavailable",
            "agent": "available" if agent_ok else "unavailable", "request_id": request.state.request_id,
            "worker_live": bool(worker._thread and worker._thread.is_alive()), "storage_error": worker.storage_error,
            'agent_version': agent_health.get('agent_version'), 'agent_protocol_version': agent.protocol_version,
        })

    @app.get("/v1/capabilities")
    def capabilities(request: Request):
        try:
            agent_caps = agent.capabilities()
        except AgentUnavailable:
            agent_caps = None
        return {"implemented_jobs": sorted(worker.handlers), "future_operations": "unsupported",
                "agent": agent_caps, "request_id": request.state.request_id}

    @app.get("/v1/config")
    def config(request: Request):
        from explainnet.application_profiles import identity
        from explainnet.service_requirements import resolve
        return {"schema_version": settings.schema_version, "config_hash": settings.config_hash,
                'identity': identity(settings),
                'service_requirements': resolve({}, settings.objective),
                "data_dir": str(settings.data_dir), "runtime_dir": str(settings.runtime_dir),
                "host": settings.host, "port": settings.port,
                "objective": settings.objective.model_dump(),
                "laboratory_policy": settings.laboratory_policy.model_dump(),
                "request_id": request.state.request_id}

    @app.get("/v1/agent/inventory")
    def inventory(request: Request):
        try:
            return {"inventory": agent.inventory(), "request_id": request.state.request_id}
        except AgentUnavailable as exc:
            return error(request, 503, "agent_unavailable", str(exc))

    @app.post("/v1/jobs/environment-check", status_code=202)
    def environment_check(request: Request):
        if not store.healthy():
            return error(request, 503, "database_unavailable", "initialize storage before submitting jobs")
        job_id = worker.submit("environment_check", request.state.request_id)
        return {"job_id": job_id, "state": "queued", "request_id": request.state.request_id}

    def submit_operation(request: Request, operation: str, payload):
        if not store.healthy():
            return error(request, 503, "database_unavailable", "run database init/migrations before submitting jobs")
        try:
            job_id = worker.submit(operation, request.state.request_id, payload.model_dump(),
                idempotency_key=request.headers.get('Idempotency-Key'))
        except ValueError as exc:
            return error(request, 409, "experiment_locked", str(exc))
        return JSONResponse(status_code=202, content={"job_id": job_id, "state": "queued",
                                                    "request_id": request.state.request_id})

    @app.post("/v1/networks/start")
    def network_start(body: NetworkLaunchRequest, request: Request):
        try:
            definition = load_network(settings.topology_file)
            if body.switches != len(definition.switches):
                from explainnet.network_contracts import NetworkDefinition
                from explainnet.topology.spec import scale_definition
                definition = NetworkDefinition.model_validate(scale_definition(definition.model_dump(),body.switches))
        except (ValueError, TypeError, OSError) as exc:
            return error(request, 422, "invalid_topology", str(exc))
        return submit_operation(request, "network_start", NetworkStartRequest(instance_id=body.instance_id,
                                                                              definition=definition))

    @app.get("/v1/networks/{instance_id}")
    def network_status(instance_id: str, request: Request):
        try:
            result = agent.network_inspect(InstanceRequest(instance_id=instance_id))
            return bounded_read(result)
        except AgentUnavailable as exc:
            return error(request, 503, "agent_unavailable", str(exc))
        except ValueError as exc:
            return error(request, 422, "invalid_instance", str(exc))

    @app.post("/v1/networks/stop")
    def network_stop(body: InstanceRequest, request: Request):
        return submit_operation(request, "network_stop", body)

    @app.post("/v1/networks/cleanup")
    def network_cleanup(body: InstanceRequest, request: Request):
        return submit_operation(request, "network_cleanup", body)

    @app.post("/v1/networks/path")
    def select_path(body: PathRequest, request: Request):
        return submit_operation(request, "path_select", body)

    @app.post("/v1/networks/probe")
    def network_probe(body: ProbeRequest, request: Request):
        return submit_operation(request, "network_probe", body)

    @app.post("/v1/traffic/start")
    def traffic_start(body: TrafficSubmission, request: Request):
        try:
            configured = load_profiles(settings.traffic_profiles_file)
            if len(set(body.profile_ids)) != len(body.profile_ids):
                raise ValueError("duplicate profiles")
            profiles = [configured[name] for name in body.profile_ids]
            if (body.offered_bps is not None or body.packet_size is not None) and len(profiles) != 1:
                raise ValueError("rate/packet overrides require a single selected profile")
            overrides = {k: v for k, v in {"duration_s": body.duration_s, "offered_bps": body.offered_bps,
                                           "packet_size": body.packet_size, 'stream_receiver': body.stream_receiver}.items() if v is not None}
            profiles = [WorkloadProfile.model_validate(p.model_dump() | overrides) for p in profiles]
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return error(request, 422, "invalid_traffic", str(exc))
        return submit_operation(request, "traffic_start", TrafficStartRequest(instance_id=body.instance_id, profiles=profiles))

    @app.get("/v1/traffic/{instance_id}/{run_id}")
    def traffic_status(instance_id: str, run_id: str, request: Request):
        try:
            result = agent.traffic_status(TrafficRunRequest(instance_id=instance_id, run_id=run_id))
            return bounded_read(result)
        except AgentUnavailable as exc:
            return error(request, 503, "agent_unavailable", str(exc))
        except ValueError as exc:
            return error(request, 422, "invalid_traffic_run", str(exc))

    @app.post("/v1/traffic/stop")
    def traffic_stop(body: TrafficRunRequest, request: Request):
        return submit_operation(request, "traffic_stop", body)

    @app.post('/v1/traffic/workload/start')
    def observation_workload(body: TrafficStartRequest, request: Request):
        if any(p.config_version != 'workflow_observation_v1' or not p.stream_receiver for p in body.profiles):
            return error(request, 422, 'explicit_workload_required', 'Use bounded workflow_observation_v1 profiles with native receiver streaming')
        return submit_operation(request, 'traffic_start', body)

    def evidence_page(value, offset):
        import base64
        import hashlib
        raw = encoded(value)
        if offset > len(raw):
            return JSONResponse(status_code=416, content={'error': 'offset exceeds evidence'})
        block = raw[offset:offset + CHUNK_BYTES]
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'offset': offset, 'total_bytes': len(raw),
            'next_offset': offset + len(block), 'complete': offset + len(block) == len(raw),
            'base64': base64.b64encode(block).decode()}

    @app.get('/v1/jobs/{job_id}/evidence')
    def job_evidence(job_id: Identifier, request: Request, offset: int = Query(default=0, ge=0)):
        job = store.get_job(job_id)
        if not job:
            return error(request, 404, 'job_not_found', 'job does not exist')
        return evidence_page(job, offset)

    @app.get('/v1/traffic/{instance_id}/{run_id}/evidence')
    def traffic_evidence(instance_id: Identifier, run_id: Identifier, request: Request, offset: int = Query(default=0, ge=0)):
        try:
            return evidence_page(agent.traffic_status(TrafficRunRequest(instance_id=instance_id, run_id=run_id)), offset)
        except AgentUnavailable as exc:
            return error(request, 503, 'agent_unavailable', str(exc))

    @app.post('/v1/laboratory/reconcile')
    def owner_reconcile(body: InstanceRequest, request: Request):
        return submit_operation(request, 'owner_reconcile', body)

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        if not store.healthy():
            return error(request, 503, "database_unavailable", "storage unavailable")
        job = store.get_job(job_id)
        if job and job.get('result'):
            job['result'] = projection(job['result'])
            job['evidence_retrieval'] = f'/v1/jobs/{job_id}/evidence'
        return job if job else error(request, 404, "job_not_found", "job does not exist")

    @app.post("/v1/laboratory/scenarios/start")
    def scenario_start(body: ScenarioStartRequest, request: Request):
        return submit_operation(request, "scenario_start", body)

    @app.post("/v1/laboratory/scenarios/stop")
    def scenario_stop(body: InstanceRequest, request: Request):
        return submit_operation(request, "scenario_stop", body)

    @app.post("/v1/laboratory/scenarios/reset")
    def scenario_reset(body: InstanceRequest, request: Request):
        return submit_operation(request, "scenario_reset", body)

    @app.get("/v1/laboratory/scenarios/{instance_id}")
    def scenario_inspect(instance_id: str, request: Request):
        try:
            result = agent.scenario_inspect(InstanceRequest(instance_id=instance_id))
            return bounded_read(result)
        except AgentUnavailable as exc:
            return error(request, 503, "agent_unavailable", str(exc))
        except ValueError as exc:
            return error(request, 422, "invalid_instance", str(exc))

    @app.post("/v1/jobs/{job_type}")
    def unsupported_job(job_type: str, request: Request):
        return error(request, 501, "unsupported_operation", f"job type {job_type!r} is not implemented")

    @app.post("/v1/models/train")
    def model_train(body: TrainRequest, request: Request):
        return submit_operation(request, "model_train", body)

    @app.post("/v1/explanations/request")
    def explanation_request(body: ExplanationRequest, request: Request):
        return submit_operation(request, "explanation_request", body)

    @app.get("/v1/explanations")
    def explanation_status():
        return worker.explanations.status()

    @app.get("/v1/explanations/window/{window_id}")
    def explanation_history(window_id: Identifier):
        return {'window_id': window_id, 'records': worker.explanations.history(window_id)}

    @app.get("/v1/explanations/{explanation_id}")
    def explanation_get(explanation_id: Identifier, request: Request):
        try:
            return worker.explanations.get(explanation_id)
        except ValueError as exc:
            return error(request, 404, 'explanation_not_found', str(exc))

    @app.get("/v1/incidents")
    def incidents(instance_id: Identifier | None = None):
        return {'records': worker.explanations.incidents.list(instance_id)}

    @app.get("/v1/incidents/{incident_id}")
    def incident_get(incident_id: Identifier, request: Request):
        try:
            return worker.explanations.incidents.get(incident_id)
        except ValueError as exc:
            return error(request, 404, 'incident_not_found', str(exc))

    @app.post("/v1/models/load")
    def model_load(body: BundleRequest, request: Request):
        return submit_operation(request, "model_load", body)

    @app.post("/v1/models/infer")
    def model_infer(body: InferenceRequest, request: Request):
        return submit_operation(request, "model_infer", body)

    @app.get("/v1/models")
    def model_status():
        return worker.diagnosis.status()

    @app.get("/v1/models/{model_id}")
    def model_inspect(model_id: Identifier, request: Request):
        try:
            BundleRequest(model_id=model_id)
            return worker.diagnosis.bundles.inspect(model_id)
        except ValueError as exc:
            return error(request, 404, "model_not_found", str(exc))

    @app.get("/v1/diagnoses/{window_id}")
    def diagnoses(window_id: Identifier):
        from explainnet.telemetry_contracts import ReferenceRequest
        ReferenceRequest(window_id=window_id)
        return {"window_id": window_id, "records": worker.diagnosis.history(window_id)}

    @app.post("/v1/telemetry/start")
    def collector_start(body: CollectorStartRequest, request: Request):
        return submit_operation(request, "collector_start", body)

    @app.post("/v1/telemetry/stop")
    def collector_stop(body: InstanceRequest, request: Request):
        return submit_operation(request, "collector_stop", body)

    @app.post("/v1/telemetry/reference")
    def telemetry_reference(body: ReferenceRequest, request: Request):
        return submit_operation(request, "telemetry_reference", body)

    @app.get("/v1/telemetry/{instance_id}/status")
    def collector_status(instance_id: Identifier):
        InstanceRequest(instance_id=instance_id)
        return worker.telemetry.status(instance_id)

    @app.get("/v1/telemetry/{instance_id}/windows")
    def telemetry_windows(instance_id: Identifier, limit: int = Query(default=50, ge=1, le=200), ready_only: bool = False):
        InstanceRequest(instance_id=instance_id)
        return worker.telemetry.windows(instance_id, limit, ready_only)

    @app.get("/v1/telemetry/{instance_id}/latest")
    def telemetry_latest(instance_id: Identifier):
        InstanceRequest(instance_id=instance_id)
        return worker.telemetry.windows(instance_id, 1)

    @app.get("/v1/telemetry/{instance_id}/alerts")
    def telemetry_alerts(instance_id: Identifier):
        InstanceRequest(instance_id=instance_id)
        return worker.telemetry.alerts(instance_id)

    @app.post("/v1/datasets/plan")
    def dataset_plan(body: DatasetRunRequest, request: Request):
        return submit_operation(request, "dataset_plan", body)

    @app.post("/v1/datasets/start")
    def dataset_start(body: BatchRequest, request: Request):
        return submit_operation(request, "dataset_start", body)

    @app.post("/v1/datasets/resume")
    def dataset_resume(body: BatchRequest, request: Request):
        return submit_operation(request, "dataset_resume", body)

    @app.post("/v1/datasets/cancel")
    def dataset_cancel(body: BatchRequest, request: Request):
        return submit_operation(request, "dataset_cancel", body)

    @app.post("/v1/datasets/export")
    def dataset_export(body: BatchRequest, request: Request):
        return submit_operation(request, "dataset_export", body)

    @app.get("/v1/datasets/{batch_id}")
    def dataset_status(batch_id: Identifier, request: Request, details: bool = False):
        try:
            return worker.dataset.status(batch_id, details=details)
        except ValueError as exc:
            return error(request, 404, "dataset_not_found", str(exc))

    @app.post("/v1/control/stop")
    def stop(request: Request):
        if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return error(request, 403, "forbidden", "local callers only")
        server = getattr(request.app.state, "server", None)
        if server is None:
            return error(request, 503, "service_control_unavailable", "server control is not attached")
        threading.Timer(0.2, lambda: setattr(server, "should_exit", True)).start()
        return {"stopping": True, "request_id": request.state.request_id}

    @app.post('/v1/twins/snapshot')
    def twin_snapshot(body: SnapshotRequest, request: Request):
        return submit_operation(request, 'twin_snapshot', body)

    @app.post('/v1/demo/reference')
    def demo_reference(body: InstanceRequest, request: Request):
        return submit_operation(request, 'demo_reference', body)

    @app.get('/v1/demo/reference/{instance_id}')
    def demo_reference_read(instance_id: Identifier):
        from explainnet.demo_reference import latest_reference
        return {'reference':latest_reference(store,instance_id)}

    @app.get('/v1/demo/host-status')
    def demo_host_status():
        from explainnet.demo_reference import campaign_status
        return campaign_status(Path(__file__).resolve().parents[2])

    @app.post('/v1/twins/construct')
    def twin_construct(body: ConstructRequest, request: Request):
        return submit_operation(request, 'twin_construct', body)

    @app.post('/v1/twins/measure')
    def twin_measure(body: TwinMeasureRequest, request: Request):
        return submit_operation(request, 'twin_measure', body)

    @app.post('/v1/twins/reset')
    def twin_reset(body: TwinResetRequest, request: Request):
        return submit_operation(request, 'twin_reset', body)

    @app.post('/v1/twins/destroy')
    def twin_destroy(body: TwinRequest, request: Request):
        return submit_operation(request, 'twin_destroy', body)

    @app.post('/v1/twins/calibrate')
    def twin_calibrate(body: CalibrationRequest, request: Request):
        return submit_operation(request, 'twin_calibrate', body)

    @app.post('/v1/twins/cancel')
    def twin_cancel(body: TwinRequest, request: Request):
        try:
            return worker.twins.cancel(body)
        except (ValueError, AgentUnavailable) as exc:
            return error(request, 409, 'twin_cancel_failed', str(exc))

    @app.get('/v1/twins/snapshots/{snapshot_id}')
    def twin_snapshot_get(snapshot_id: Identifier, request: Request):
        try:
            return bounded_read(worker.twins.get_snapshot(snapshot_id))
        except ValueError as exc:
            return error(request, 404, 'snapshot_not_found', str(exc))

    @app.get('/v1/twins/{twin_id}')
    def twin_status(twin_id: Identifier, request: Request):
        try:
            return bounded_read(worker.twins.status(twin_id))
        except (ValueError, AgentUnavailable) as exc:
            return error(request, 409, 'twin_status_failed', str(exc))

    from explainnet.recovery_contracts import RecoveryID, RecoveryRequest

    @app.post('/v1/recovery/plan')
    def recovery_plan(body: RecoveryRequest, request: Request):
        return submit_operation(request, 'recovery_plan', body)

    @app.post('/v1/recovery/test')
    def recovery_test(body: RecoveryRequest, request: Request):
        return submit_operation(request, 'recovery_test', body)

    @app.post('/v1/recovery/cancel')
    def recovery_cancel(body: RecoveryID, request: Request):
        try:
            return worker.recovery.cancel(body.operation_id)
        except ValueError as exc:
            return error(request, 409, 'recovery_cancel_failed', str(exc))

    @app.get('/v1/recovery/{operation_id}')
    def recovery_get(operation_id: Identifier, request: Request):
        try:
            return bounded_read(worker.recovery.get(operation_id))
        except ValueError as exc:
            return error(request, 404, 'recovery_not_found', str(exc))

    from explainnet.workflow_contracts import (
        ApplyRequest,
        ModeRequest,
        UndoRequest,
        WorkflowID,
        WorkflowRequest,
    )

    @app.post('/v1/lab/workflow')
    def workflow_start(body: WorkflowRequest, request: Request):
        return submit_operation(request, 'workflow_start', body)

    @app.post('/v1/lab/apply')
    def workflow_apply(body: ApplyRequest, request: Request):
        return submit_operation(request, 'workflow_apply', body)

    @app.post('/v1/lab/mode')
    def workflow_mode(body: ModeRequest, request: Request):
        return submit_operation(request, 'workflow_mode', body)

    @app.post('/v1/lab/undo')
    def workflow_undo(body: UndoRequest, request: Request):
        return submit_operation(request, 'workflow_undo', body)

    @app.post('/v1/lab/automation/start')
    def automation_start(body: WorkflowRequest, request: Request):
        return submit_operation(request, 'workflow_automation_start', body)

    @app.post('/v1/lab/automation/stop')
    def automation_stop():
        return worker.coordinator.stop()

    @app.post('/v1/lab/cancel')
    def workflow_cancel(body: WorkflowID, request: Request):
        try:
            return worker.coordinator.cancel(body.workflow_id)
        except ValueError as exc:
            return error(request, 409, 'workflow_cancel_failed', str(exc))

    @app.get('/v1/lab/control')
    def workflow_control():
        return worker.coordinator.control() | worker.coordinator.lifecycle()

    @app.post('/v1/lab/reconcile')
    def workflow_reconcile(request: Request):
        if worker.coordinator.active:
            return error(request, 409, 'execution_active', 'wait for execution to finish')
        return worker.coordinator.reconcile()

    @app.post('/v1/lab/actions/{action_id}/rollback')
    def interrupted_rollback(action_id: Identifier, request: Request):
        try:
            return worker.coordinator.reconcile_action(action_id)
        except (ValueError, AgentUnavailable) as exc:
            return error(request, 409, 'reconciliation_required', str(exc))

    @app.get('/v1/lab/workflows/{workflow_id}')
    def workflow_get(workflow_id: Identifier, request: Request):
        try:
            return bounded_read(worker.coordinator.get(workflow_id))
        except ValueError as exc:
            return error(request, 404, 'workflow_not_found', str(exc))

    @app.get('/v1/lab/actions/{action_id}')
    def action_get(action_id: Identifier, request: Request):
        try:
            return bounded_read(worker.coordinator.action(action_id))
        except ValueError as exc:
            return error(request, 404, 'action_not_found', str(exc))

    from explainnet.dashboard_api import mount_dashboard
    mount_dashboard(app, settings, store, worker)
    return app


def app_from_path(config_path: Path) -> FastAPI:
    return create_app(load_settings(config_path))
