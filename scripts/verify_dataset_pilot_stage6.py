"""Audit measured pilot and gate the compact batch; reads only the pilot partition."""

import json
import statistics
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json, export_dataset
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store
from explainnet.telemetry_storage import TelemetryRepository

runtime = Path("artifacts/stage6/runtime")
supervisor = json.loads((runtime / "supervisor.json").read_text())
store = Store(load_settings(runtime / "config.json").database_path)
batch_id = supervisor["batch_id"]
batch = DatasetRepository(store).batch(batch_id)
assert batch["schedule"]["purpose"] == "pilot" and batch["state"] == "completed"
exported = export_dataset(store, batch_id)
quality = exported["quality"]
assert quality["structural_checks_passed"] and not quality["shortfalls"], quality
assert quality["accepted_windows"] == 10 and quality["completed_episodes"] == 5
assert supervisor["cleanup_preserved_bridges"] and not supervisor["agent_socket_present"]
cases = {}
episodes = {e["episode_id"]: e for e in batch["schedule"]["episodes"]}
for attempt in DatasetRepository(store).attempts(batch_id):
    assert attempt["state"] == "completed" and attempt["restoration_verified"] and attempt["cleanup_verified"]
    kind = episodes[attempt["episode_id"]]["scenario"]["kind"]
    with store.connection() as db:
        windows = [json.loads(db.execute("SELECT payload_json FROM telemetry_windows WHERE window_id=?", (window_id,)).fetchone()[0])
                   for window_id in attempt["accepted_window_ids"]]
    baseline_run = attempt["baseline_traffic"]["run_id"]
    records = TelemetryRepository(store).samples(attempt["collector_run_id"])
    rtts = [rtt for r in records if r["source"] == "network_agent" and any(f["traffic_run_id"] == baseline_run for f in r["active_flows"])
            for rtt in r["probe"].get("rtt_values_ms", [])]
    mean = {name: statistics.mean(w["features"][name] for w in windows) if all(w["features"][name] is not None for w in windows) else None
            for name in ("critical_goodput_bps", "udp_loss_fraction", "rtt_mean_ms", "shared_utilization_fraction", "critical_class_rate_bps", "cpu_busy_fraction", "memory_used_fraction")}
    baseline_rtt = statistics.mean(rtts) if rtts else None
    if kind == "healthy":
        assert mean["udp_loss_fraction"] < 0.02 and mean["critical_goodput_bps"] > 7_000_000
    elif kind == "saturation":
        assert mean["shared_utilization_fraction"] > 0.85 and mean["udp_loss_fraction"] > 0.05
    elif kind == "loss":
        assert mean["udp_loss_fraction"] > 0.05 and mean["shared_utilization_fraction"] < 0.3
    elif kind == "latency":
        assert baseline_rtt is not None and mean["rtt_mean_ms"] > baseline_rtt + 30
    elif kind == "qos":
        assert mean["critical_goodput_bps"] < 900_000 and mean["critical_class_rate_bps"] < 900_000
    cases[kind] = {"window_ids": attempt["accepted_window_ids"], "measured_means": mean,
        "baseline_mean_rtt_ms": baseline_rtt, "baseline_service": attempt["baseline_service"],
        "recovery_service": attempt["recovery_service"], "elapsed_s": attempt["elapsed_s"],
        "coverage_fractions": [w["data_quality"]["coverage_fraction"] for w in windows],
        "restoration_verified": True, "cleanup_verified": True}
report = {"schema_version": 1, "status": "complete", "batch_id": batch_id, "cases": cases,
          "quality": quality, "runtime_total_s": sum(v["elapsed_s"] for v in cases.values()),
          "projected_main_minutes": sum(v["elapsed_s"] + 85 - 38 for v in cases.values()) / 5 * 60 / 60,
          "main_schedule": "config/datasets/main_v1.json", "split_changes_after_pilot": [],
          "limits": ["Pilot is disjoint from main test data", "All five pilot fault recipes use high severity and forward direction",
                     "Lower severities and reverse/TCP variants are declared in main; episode failures remain explicit shortfalls"]}
atomic_json(Path("artifacts/stage6/pilot_report.json"), report)
print(json.dumps({"status": report["status"], "windows": quality["accepted_windows"],
                  "episodes": quality["completed_episodes"], "runtime_total_s": report["runtime_total_s"],
                  "projected_main_minutes": report["projected_main_minutes"], "cases": cases}, indent=2))
