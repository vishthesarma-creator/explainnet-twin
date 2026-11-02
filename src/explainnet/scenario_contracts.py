"""Typed laboratory controls, separate from diagnostic contracts."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from explainnet.contracts import GroundTruth, Record
from explainnet.network_contracts import InstanceRequest
from explainnet.scenario_spec import validate_scenario


class Scenario(Record):
    model_config = ConfigDict(strict=True)
    config_version: Literal["pilot_v1", "dataset_v1", "recovery_observation_v1"] = "pilot_v1"
    kind: Literal["healthy", "saturation", "loss", "latency", "qos"]
    severity: Literal["low", "medium", "high"] = "medium"
    warmup_s: int = Field(default=2, ge=1, le=5)
    measurement_s: int = Field(default=8, ge=4, le=900)
    bidirectional: bool = False
    variation_ms: int = Field(default=0, ge=0, le=10)
    high_utilization: bool = False
    traffic_profile: Literal["moderate", "shared", "qos_competing"] = "moderate"
    critical_bps: int | None = Field(default=None, ge=1000000, le=8000000)
    bulk_protocol: Literal["tcp", "udp"] = "udp"
    packet_size: int = Field(default=1200, ge=600, le=1400)
    seed: int = Field(default=20261007, ge=0, le=2147483647)

    @model_validator(mode="after")
    def valid_recipe(self):
        validate_scenario(self.model_dump())
        return self


class ScenarioStartRequest(InstanceRequest):
    scenario: Scenario


class ExperimentGroundTruth(GroundTruth):
    """Extends the foundation truth contract; never part of observed run payloads."""

    configuration: Scenario
    intended_location: Literal["s2->s3", "s3->s5"] | None
    activated_utc: datetime | None
    deactivated_utc: datetime | None
    activated_monotonic_s: float | None = Field(default=None, ge=0)
    deactivated_monotonic_s: float | None = Field(default=None, ge=0)
    state: Literal["applying", "active", "stopped", "restore_failed", "terminated"]
    affected_directions: list[list[str]] = Field(default_factory=list)
    restore_errors: list[str] = Field(default_factory=list)

    @field_validator("activated_utc", "deactivated_utc")
    @classmethod
    def actual_utc(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)):
            raise ValueError("activation/deactivation must be timezone-aware UTC")
        return value
