"""Versioned YAML configuration with explicit local paths."""

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from explainnet.contracts import LaboratoryPolicy, ServiceObjective
from explainnet.network_contracts import NetworkDefinition, WorkloadProfile
from explainnet.telemetry_contracts import TelemetrySettings


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    data_dir: Path
    runtime_dir: Path
    agent_socket: Path
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    objective: ServiceObjective = ServiceObjective()
    laboratory_policy: LaboratoryPolicy = LaboratoryPolicy()
    topology_file: Path | None = None
    traffic_profiles_file: Path | None = None
    lab_test_hooks: bool = False
    telemetry: TelemetrySettings = TelemetrySettings()
    dataset_artifact_dir: Path | None = None

    @field_validator("data_dir", "runtime_dir", "agent_socket")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "explainnet.sqlite3"

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_settings(path: Path) -> Settings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("configuration must be a YAML mapping")
    for name in ("topology_file", "traffic_profiles_file"):
        if raw.get(name) is not None:
            configured = Path(raw[name])
            raw[name] = configured if configured.is_absolute() else (path.resolve().parent / configured)
    return Settings.model_validate(raw)


def load_network(path: Path | None) -> NetworkDefinition:
    if path is None:
        raise ValueError("topology_file is not configured")
    return NetworkDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_profiles(path: Path | None) -> dict[str, WorkloadProfile]:
    if path is None:
        raise ValueError("traffic_profiles_file is not configured")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        raise ValueError("unsupported workload configuration")
    if set(raw) - {"schema_version", "config_version", "profiles", "optional_background"}:
        raise ValueError("unknown workload configuration fields")
    profiles = [*raw["profiles"]]
    if raw.get("optional_background"):
        profiles.append(raw["optional_background"])
    validated = [WorkloadProfile.model_validate(p | {"config_version": raw["config_version"]}) for p in profiles]
    if len({p.profile_id for p in validated}) != len(validated):
        raise ValueError("duplicate profile IDs")
    return {p.profile_id: p for p in validated}
