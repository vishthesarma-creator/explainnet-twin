"""Versioned, unit-explicit records shared by later stages."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Fraction = Annotated[float, Field(ge=0, le=1)]
Nonnegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version")
    @classmethod
    def version_one(cls, value: int) -> int:
        return value


class StampedRecord(Record):
    at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("at_utc")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timestamp must be timezone-aware UTC")
        return value


class DirectionalLink(Record):
    link_id: Identifier
    source: Identifier
    target: Identifier
    capacity_bps: Positive


class Host(Record):
    host_id: Identifier
    switch_id: Identifier
    ip_address: str


class Topology(Record):
    topology_id: Identifier
    switches: list[Identifier]
    links: list[DirectionalLink]
    hosts: list[Host]


class TrafficProfile(Record):
    profile_id: Identifier
    source_host: Identifier
    target_host: Identifier
    protocol: Literal["tcp", "udp"]
    target_bps: Positive
    duration_s: Positive


class ServiceObjective(Record):
    max_rtt_ms: Positive | None = None
    max_loss_fraction: Fraction | None = None
    min_goodput_bps: Nonnegative | None = None
    max_jitter_ms: Nonnegative | None = None


class LaboratoryPolicy(Record):
    permitted_actions: list[Literal["reroute", "rate_limit", "qos_adjust", "revert"]] = []
    auto_repair_enabled: bool = False


class DataQuality(StrEnum):
    valid = "valid"
    partial = "partial"
    invalid = "invalid"


class Measurement(StampedRecord):
    run_id: Identifier
    link_id: Identifier | None = None
    rtt_ms: Nonnegative | None = None
    jitter_ms: Nonnegative | None = None
    loss_fraction: Fraction | None = None
    throughput_bps: Nonnegative | None = None
    goodput_bps: Nonnegative | None = None
    utilization_fraction: Fraction | None = None
    queue_packets: Annotated[int, Field(ge=0)] | None = None
    quality: DataQuality


class FeatureWindow(StampedRecord):
    run_id: Identifier
    duration_s: Positive
    features: dict[str, float | None]
    quality: DataQuality


class GroundTruth(StampedRecord):
    run_id: Identifier
    fault_label: Identifier | None = None
    injected_parameters: dict[str, Any] = {}


class ModelVersion(Record):
    model_id: Identifier
    artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Explanation(Record):
    summary: str
    feature_contributions: dict[str, float] = {}
    model: ModelVersion | None = None


class Diagnosis(Record):
    label: Identifier
    confidence: Fraction
    explanation: Explanation | None = None


class Incident(StampedRecord):
    incident_id: Identifier
    run_id: Identifier
    status: Literal["open", "resolved"] = "open"
    diagnosis: Diagnosis | None = None


class TwinSnapshot(StampedRecord):
    snapshot_id: Identifier
    run_id: Identifier
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fidelity: Fraction | None = None


class CandidateResult(StampedRecord):
    candidate_id: Identifier
    snapshot_id: Identifier
    proposed_action: Identifier
    predicted_rtt_ms: Nonnegative | None = None
    predicted_loss_fraction: Fraction | None = None


class ProposedAction(StampedRecord):
    action_id: Identifier
    incident_id: Identifier
    action_type: Literal["reroute", "rate_limit", "qos_adjust", "revert"]
    approved: bool = False


class Verification(StampedRecord):
    action_id: Identifier
    passed: bool
    observed: Measurement | None = None


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"
    interrupted = "interrupted"


class Job(StampedRecord):
    job_id: Identifier
    job_type: Identifier
    state: JobState
    result: dict[str, Any] | None = None
    error: str | None = None
    elapsed_ms: Nonnegative | None = None


class ServiceHealth(StampedRecord):
    status: Literal["healthy", "degraded", "unavailable"]
    database: Literal["available", "unavailable"]
    agent: Literal["available", "unavailable"]
