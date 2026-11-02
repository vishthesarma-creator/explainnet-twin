"""Typed client for restricted privileged local laboratory operations."""

import base64
import hashlib
import json
import socket
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from explainnet.agent_protocol import OPERATIONS, validate_parameters
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    PathRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
)
from explainnet.response_evidence import FRAME_LIMIT, HYDRATE_LIMIT
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.telemetry_contracts import ObserveRequest


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[1, 2] = 2
    request_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def restricted_operation(self):
        if self.operation not in OPERATIONS:
            raise ValueError("unsupported operation")
        validate_parameters(self.operation, self.parameters)
        return self


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[1, 2]
    request_id: str
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1]
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    bytes: int = Field(ge=0)
    encoding: Literal['json']
    chunk_bytes: Literal[49152]
    retention: str | None = None


class ControlAcknowledgement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ack_version: Literal[2]
    operation: str
    outcome: Literal['completed']
    result: dict[str, Any]
    evidence: EvidenceReference


class AgentUnavailable(RuntimeError):
    pass


# Finished 900-second runs contain full native sender/receiver interval evidence.
# Keep other replies at 2 MiB; permit bounded larger evidence only for run reads/stops.
DEFAULT_RESPONSE_LIMIT = 2 * 1024 * 1024
TRAFFIC_RESPONSE_LIMIT = 8 * 1024 * 1024
RPC_CONTEXT = ContextVar('explainnet_rpc_job', default=None)


class AgentClient:
    def __init__(self, socket_path: Path, timeout_s: float = 2.0, protocol_version=None):
        self.socket_path = socket_path
        self.timeout_s = timeout_s
        self.protocol_version = protocol_version
        self._negotiation_lock = threading.RLock()

    def call(self, operation: str, parameters: dict[str, Any] | None = None,
             timeout_s: float | None = None, *, hydrate=True) -> dict[str, Any]:
        with self._negotiation_lock:
            if self.protocol_version is None:
                # Negotiate with a read only. Never retry a mutation in another version.
                self.protocol_version = 1
                try:
                    available = self.call('health')
                    self.protocol_version = 2 if 2 in available.get('protocol_versions', []) else 1
                except Exception:
                    self.protocol_version = None
                    raise
        request = AgentRequest(operation=operation, parameters=parameters or {}, protocol_version=self.protocol_version)
        if RPC_CONTEXT.get():
            from explainnet.response_evidence import READ_OPERATIONS
            if operation not in READ_OPERATIONS | {'evidence_read', 'telemetry_observe'}:
                request.request_id = hashlib.sha256(json.dumps([RPC_CONTEXT.get(), operation, parameters], sort_keys=True).encode()).hexdigest()[:32]
        response_limit = (FRAME_LIMIT if self.protocol_version == 2 else
            TRAFFIC_RESPONSE_LIMIT if operation in {'traffic_status', 'traffic_stop'} else DEFAULT_RESPONSE_LIMIT)
        outgoing = (request.model_dump_json() + '\n').encode()
        if len(outgoing) > 262144:
            raise AgentUnavailable('request exceeds bounded frame; no mutation submitted')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(timeout_s or self.timeout_s)
                client.connect(str(self.socket_path))
                client.sendall(outgoing)
                chunks = bytearray()
                while b'\n' not in chunks:
                    block = client.recv(4096)
                    if not block:
                        raise AgentUnavailable('incomplete agent response: newline terminator missing')
                    if len(chunks) + len(block) > response_limit:
                        raise AgentUnavailable(f'oversized agent response: limit {response_limit} bytes')
                    chunks.extend(block)
                if not chunks.endswith(b'\n') or chunks.count(b'\n') != 1:
                    raise AgentUnavailable('malformed agent frame: trailing data')
            response = AgentResponse.model_validate_json(bytes(chunks))
            if response.protocol_version != request.protocol_version or response.request_id != request.request_id or not response.ok:
                raise AgentUnavailable(response.error or "agent response mismatch")
            data = response.data or {}
            if self.protocol_version == 2 and operation != 'evidence_read':
                ack = ControlAcknowledgement.model_validate(data)
                if ack.operation != operation:
                    raise AgentUnavailable('invalid typed acknowledgement; inspect owned state before retry')
                if hydrate:
                    return self.read_evidence(data['evidence'])
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AgentUnavailable(str(exc)) from exc

    def read_evidence(self, reference):
        """Explicit, bounded chunk retrieval; validate every offset and final digest."""
        size, sha = reference['bytes'], reference['sha256']
        if type(size) is not int or not 0 <= size <= HYDRATE_LIMIT:
            raise AgentUnavailable('evidence exceeds hydration budget; use paged evidence_read, mutation outcome unknown')
        raw = bytearray()
        while len(raw) < size:
            page = self.call('evidence_read', {'sha256': sha, 'offset': len(raw)}, hydrate=False)
            block = base64.b64decode(page['base64'], validate=True)
            if (page['sha256'] != sha or page['offset'] != len(raw) or page['total_bytes'] != size
                    or not block or len(block) > 48 * 1024 or page['next_offset'] != len(raw) + len(block)
                    or len(raw) + len(block) > size or page['complete'] != (len(raw) + len(block) == size)):
                raise AgentUnavailable('evidence chunk identity/size mismatch')
            raw.extend(block)
        if hashlib.sha256(raw).hexdigest() != sha:
            raise AgentUnavailable('evidence integrity mismatch')
        return json.loads(raw)

    def health(self) -> dict[str, Any]:
        return self.call("health")

    def capabilities(self) -> dict[str, Any]:
        return self.call("capabilities")

    def inventory(self) -> dict[str, Any]:
        return self.call("inventory", timeout_s=15)

    def network_start(self, request: NetworkStartRequest) -> dict[str, Any]:
        return self.call("network_start", request.model_dump(), timeout_s=60)

    def network_inspect(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("network_inspect", request.model_dump(), timeout_s=15)

    def network_stop(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("network_stop", request.model_dump(), timeout_s=40)

    def network_cleanup(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("network_cleanup", request.model_dump(), timeout_s=40)

    def path_select(self, request: PathRequest) -> dict[str, Any]:
        return self.call("path_select", request.model_dump(), timeout_s=15)

    def network_probe(self, request: ProbeRequest) -> dict[str, Any]:
        return self.call("network_probe", request.model_dump(), timeout_s=90)

    def traffic_start(self, request: TrafficStartRequest) -> dict[str, Any]:
        return self.call("traffic_start", request.model_dump(), timeout_s=15)

    def traffic_status(self, request: TrafficRunRequest) -> dict[str, Any]:
        return self.call("traffic_status", request.model_dump(), timeout_s=10)

    def traffic_stop(self, request: TrafficRunRequest) -> dict[str, Any]:
        return self.call("traffic_stop", request.model_dump(), timeout_s=15)

    def scenario_start(self, request: ScenarioStartRequest) -> dict[str, Any]:
        return self.call("scenario_start", request.model_dump(), timeout_s=30)

    def scenario_inspect(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("scenario_inspect", request.model_dump(), timeout_s=15)

    def scenario_stop(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("scenario_stop", request.model_dump(), timeout_s=30)

    def scenario_reset(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call("scenario_reset", request.model_dump(), timeout_s=30)

    def telemetry_observe(self, request: ObserveRequest) -> dict[str, Any]:
        return self.call("telemetry_observe", request.model_dump(), timeout_s=15)

    def twin_view(self, request: InstanceRequest) -> dict[str, Any]:
        return self.call('twin_view', request.model_dump(), timeout_s=20)

    def twin_capture(self, request) -> dict[str, Any]:
        from explainnet.twin_contracts import CaptureRequest
        return self.call('twin_capture', CaptureRequest.model_validate(request.model_dump()).model_dump(), timeout_s=50)

    def twin_construct(self, request) -> dict[str, Any]:
        from explainnet.twin_contracts import AgentConstructRequest
        return self.call('twin_construct', AgentConstructRequest.model_validate(request.model_dump()).model_dump(), timeout_s=90)

    def twin_status(self, request) -> dict[str, Any]:
        return self.call('twin_status', request.model_dump(), timeout_s=20)

    def twin_reset(self, request) -> dict[str, Any]:
        return self.call('twin_reset', request.model_dump(exclude={'request_key'}), timeout_s=90)

    def twin_destroy(self, request) -> dict[str, Any]:
        return self.call('twin_destroy', request.model_dump(), timeout_s=40)

    def twin_cancel(self, request) -> dict[str, Any]:
        return self.call('twin_cancel', request.model_dump(), timeout_s=5)

    def twin_apply_candidate(self, request):
        from explainnet.recovery_contracts import AgentRecoveryAction
        return self.call('twin_apply_candidate', AgentRecoveryAction.model_validate(request.model_dump()).model_dump(), timeout_s=25)

    def lab_prepare(self, request):
        return self.call('lab_prepare', request.model_dump(), timeout_s=25)

    def lab_apply(self, request):
        return self.call('lab_apply', request.model_dump(), timeout_s=60)

    def lab_status(self, request):
        return self.call('lab_status', request.model_dump(), timeout_s=25)

    def lab_finish(self, request):
        return self.call('lab_finish', request.model_dump(), timeout_s=25)

    def lab_rollback(self, request):
        return self.call('lab_rollback', request.model_dump(), timeout_s=60)

    def lab_test_stimulus(self, request):
        return self.call('lab_test_stimulus', request.model_dump(), timeout_s=15)
