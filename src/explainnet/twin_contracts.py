"""Typed public twin operations; snapshots are validated again by the root owner."""
from typing import Any

from pydantic import Field

from explainnet.contracts import Identifier, Record
from explainnet.network_contracts import InstanceRequest


class SnapshotRequest(InstanceRequest):
    request_key: Identifier
    baseline: dict[str, Any]
    policy: dict[str, Any]
    duration_s: int = Field(default=15, ge=10, le=20)
    expiry_s: int = Field(default=180, ge=10, le=900)


class TwinRequest(Record):
    twin_id: Identifier


class ConstructRequest(TwinRequest):
    snapshot_id: Identifier
    hypothesis_id: Identifier = 'h0'


class TwinMeasureRequest(TwinRequest):
    trial_id: Identifier
    duration_s: int = Field(default=15, ge=10, le=20)


class TwinResetRequest(TwinRequest):
    hypothesis_id: Identifier | None = None
    request_key: Identifier | None = None


class CalibrationRequest(TwinRequest):
    operation_id: Identifier
    max_trials: int = Field(default=2, ge=1, le=3)
    duration_s: int = Field(default=15, ge=10, le=20)


class CaptureRequest(InstanceRequest):
    duration_s: int = Field(default=15, ge=10, le=20)
    twin_id: Identifier | None = None


class AgentConstructRequest(TwinRequest):
    snapshot: dict[str, Any]
    hypothesis_id: Identifier = 'h0'
