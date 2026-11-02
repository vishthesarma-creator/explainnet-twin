"""Typed Stage 3 API and agent operation contracts."""

from typing import Any, Literal

from pydantic import Field, model_validator

from explainnet.contracts import Identifier, Record
from explainnet.topology.spec import validate_definition


class NetworkDefinition(Record):
    config_version: Identifier
    topology_id: Identifier
    address_pool: str
    switches: list[str]
    hosts: list[dict[str, Any]]
    links: list[dict[str, Any]]
    pairs: list[dict[str, Any]]

    @model_validator(mode="after")
    def validate_topology(self):
        validate_definition(self.model_dump())
        return self


class InstanceRequest(Record):
    instance_id: Identifier


class NetworkLaunchRequest(InstanceRequest):
    switches: Literal[5,10,15] = 5


class NetworkStartRequest(InstanceRequest):
    definition: NetworkDefinition


class PathRequest(InstanceRequest):
    pair_id: Identifier
    path_name: Identifier


class WorkloadProfile(Record):
    stream_receiver: bool = False
    config_version: Identifier = "v1"
    profile_id: Identifier
    source_host: Identifier
    target_host: Identifier
    protocol: Literal["tcp", "udp"]
    offered_bps: int = Field(ge=1000, le=100000000)
    duration_s: int = Field(ge=1, le=2400)
    warmup_s: int = Field(default=0, ge=0, le=5)
    packet_size: int | None = Field(default=None, ge=64, le=1400)

    @model_validator(mode="after")
    def udp_packet_size(self):
        if self.duration_s > (2400 if self.config_version == "workflow_observation_v1" else 900 if self.config_version == "recovery_observation_v1" else 100):
            raise ValueError("traffic duration exceeds configuration bound")
        if self.protocol == "tcp" and self.packet_size is not None:
            raise ValueError("packet_size applies to UDP only")
        return self


class TrafficStartRequest(InstanceRequest):
    profiles: list[WorkloadProfile] = Field(min_length=1, max_length=3)


class TrafficRunRequest(InstanceRequest):
    run_id: Identifier


class ProbeRequest(InstanceRequest):
    source_host: Identifier | None = None
    target_host: Identifier | None = None


class TrafficSubmission(InstanceRequest):
    stream_receiver: bool | None = None
    profile_ids: list[Identifier] = Field(default_factory=lambda: ["critical", "bulk"], min_length=1, max_length=3)
    duration_s: int | None = Field(default=None, ge=1, le=100)
    offered_bps: int | None = Field(default=None, ge=1000, le=100000000)
    packet_size: int | None = Field(default=None, ge=64, le=1400)
