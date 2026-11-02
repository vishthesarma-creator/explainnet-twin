"""Stage 5 controls and explicit inference feature boundary."""

from pydantic import ConfigDict, Field

from explainnet.contracts import Identifier, Record
from explainnet.network_contracts import InstanceRequest

FEATURES = frozenset({"rtt_mean_ms", "rtt_p95_ms", "rtt_variability_ms", "ping_loss_fraction",
    "udp_loss_fraction", "critical_goodput_bps", "udp_jitter_ms", "shared_utilization_fraction",
    "qos_utilization_fraction", "shared_drop_rate_pps", "critical_class_rate_bps",
    "bulk_class_rate_bps", "queue_backlog_bytes", "offered_demand_bps", "critical_offered_bps",
    "active_flow_count", "primary_path_fraction", "cpu_busy_fraction", "memory_used_fraction",
    "critical_drop_rate_pps", "bulk_drop_rate_pps"})


class TelemetrySettings(Record):
    sample_interval_s: float = Field(default=1, ge=1, le=5)
    window_s: int = Field(default=10, ge=5, le=30)
    min_coverage_fraction: float = Field(default=0.65, ge=0.5, le=1)
    stale_after_s: float = Field(default=30, ge=5, le=120)
    consecutive_windows: int = Field(default=2, ge=1, le=5)
    recovery_windows: int = Field(default=2, ge=1, le=5)
    recovery_fraction: float = Field(default=0.9, ge=0.5, lt=1)
    max_utilization_fraction: float = Field(default=0.9, gt=0, le=1)
    min_delivered_demand_fraction: float = Field(default=0.8, gt=0, le=1)
    demand_floor_bps: int = Field(default=100000, ge=1000)
    reference_rtt_margin_ms: float = Field(default=15, ge=1, le=100)
    max_cpu_busy_fraction: float = Field(default=0.95, gt=0, le=1)
    max_memory_used_fraction: float = Field(default=0.95, gt=0, le=1)


class CollectorStartRequest(InstanceRequest):
    model_config = ConfigDict(strict=True)
    duration_s: int = Field(default=180, ge=25, le=1200)


class ObserveRequest(InstanceRequest):
    live_receivers: bool = False
    source_host: Identifier = "h1"
    target_host: Identifier = "h3"
    probe_count: int = Field(default=3, ge=1, le=5)
    completed_run_ids: list[Identifier] = Field(default_factory=list, max_length=256)
    since_utc: str


class ReferenceRequest(Record):
    window_id: Identifier
