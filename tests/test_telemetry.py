"""Deliberate fixtures/doubles for arithmetic and failure cases, not measured network data."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from explainnet.contracts import ServiceObjective
from explainnet.storage import Store
from explainnet.telemetry_contracts import FEATURES, TelemetrySettings
from explainnet.telemetry_math import aggregate_windows, delta_rate, receiver_records
from explainnet.telemetry_monitor import evaluate, rules
from explainnet.telemetry_service import TelemetryService
from explainnet.telemetry_storage import TelemetryRepository

BASE = datetime(2026, 10, 7, tzinfo=UTC)


def snapshot(t):
    return {"source": "network_agent", "run_id": "t1", "sample_id": f"o{t}", "instance_id": "lab1",
        "config_version": "v1", "agent_epoch": "epoch1", "config_hash": "config", "observed_config_hash": "observed",
        "forwarding_version": 1, "selected_paths": {"critical": "primary"}, "active_flows": [],
        "at_utc": (BASE + timedelta(seconds=t)).isoformat(), "monotonic_s": t, "completed_runs": [],
        "probe": {"valid": True, "start_monotonic_s": t, "end_monotonic_s": t + 0.2,
            "transmitted": 3, "received": 3, "rtt_values_ms": [5, 6, 7]},
        "resources": {"cpu_total_ticks": 100 + t * 100, "cpu_idle_ticks": 50 + t * 90, "memory_used_fraction": 0.2},
        "links": {d: {"identity": "interface1", "monotonic_s": t, "capacity_bps": 100_000_000,
            "counters": {"bytes": t * 1_250_000}, "classes": {}, "queues": {}}
            for d in ("s2->s3", "s3->s5")}}


def session():
    return {"run_id": "t1", "instance_id": "lab1", "started_utc": BASE.isoformat(), "started_monotonic_s": 0}


def interval(index, size, duration, packets, lost, jitter):
    return {"source": "iperf_receiver_interval", "sample_id": f"i{index}", "source_host": "h1", "target_host": "h3",
        "protocol": "udp", "valid": True, "start_monotonic_s": index, "end_monotonic_s": index + duration,
        "duration_s": duration, "bytes": size, "packets": packets, "lost_packets": lost, "jitter_ms": jitter}


def test_units_counter_resets_and_no_clipping():
    assert delta_rate(0, 1_250_000, 1, 100_000_000) == (0.1, None)
    assert delta_rate(0, 1_250_000, 1) == (10_000_000, None)
    assert delta_rate(9, 1, 1)[1] == "counter reset"
    assert delta_rate(None, 1, 1)[0] is None
    value, error = delta_rate(0, 20_000_000, 1, 100_000_000)
    assert value == 1.6 and error is not None


def test_inconsistent_optional_counter_is_unavailable_without_clipping_or_discarding_required_evidence():
    records = [snapshot(t) for t in range(11)]
    records[5]["links"]["s3->s5"]["counters"]["bytes"] = 30_000_000
    window = aggregate_windows(records, session(), TelemetrySettings(), 10)[0]
    assert window["inference_ready"]
    assert window["features"]["qos_utilization_fraction"] is None
    assert any(i["value"] > 1 for i in window["directional"]["s3->s5"]["invalid_intervals"] if i["value"] is not None)
    assert "qos_utilization_fraction" in window["data_quality"]["missing_metric_reasons"]


def test_weighted_receiver_counts_rates_and_distinct_jitter():
    records = [snapshot(t) for t in range(21)]
    records += [interval(1, 1000, 1, 100, 10, 2), interval(2, 9000, 3, 900, 0, 9)]
    windows = aggregate_windows(records, session(), TelemetrySettings(), 20)
    f = windows[0]["features"]
    assert f["critical_goodput_bps"] == 20_000  # 8*10,000 bytes / four seconds, not mean interval rates.
    assert f["udp_loss_fraction"] == 0.01  # 10/1,000, not mean percentages.
    assert f["udp_jitter_ms"] == 9  # Last native receiver estimator.
    assert f["rtt_variability_ms"] == pytest.approx((2 / 3) ** 0.5)
    assert f["rtt_variability_ms"] != f["udp_jitter_ms"]
    assert windows[0]["inference_ready"]
    assert windows[0]["end_monotonic_s"] == windows[1]["start_monotonic_s"]
    assert set(f) == FEATURES


@pytest.mark.parametrize("kind", ["reset", "epoch", "interface", "config", "path", "run", "missing", "pressure"])
def test_invalid_windows_and_transitions(kind):
    records = [snapshot(t) for t in range(11)]
    if kind == "reset":
        records[5]["links"]["s2->s3"]["counters"]["bytes"] = 0
    elif kind == "epoch":
        records[5]["agent_epoch"] = "restart"
    elif kind == "interface":
        records[5]["links"]["s2->s3"]["identity"] = "new interface"
    elif kind == "config":
        records[5]["observed_config_hash"] = "changed"
    elif kind == "path":
        records[5]["selected_paths"]["critical"] = "alternative"
    elif kind == "run":
        records[5]["active_flows"] = [{"traffic_run_id": "r2", "source_host": "h1", "target_host": "h3",
            "protocol": "udp", "offered_bps": 2_000_000}]
    elif kind == "missing":
        for r in records:
            r["probe"].update(valid=False, transmitted=None, received=None, rtt_values_ms=[])
    else:
        records[5]["resources"]["memory_used_fraction"] = 0.99
    w = aggregate_windows(records, session(), TelemetrySettings(), 10)[0]
    assert not w["inference_ready"] and w["data_quality"]["reasons"]
    if kind == "missing":
        assert w["features"]["rtt_mean_ms"] is None and w["features"]["ping_loss_fraction"] is None


def test_all_lost_probes_are_loss_not_zero_rtt_and_partial_windows():
    records = [snapshot(t) for t in range(6)]
    for r in records:
        r["probe"].update(received=0, rtt_values_ms=[])
    w = aggregate_windows(records, session(), TelemetrySettings(), 5)[0]
    assert w["features"]["ping_loss_fraction"] == 1
    assert w["features"]["rtt_mean_ms"] is None
    assert not w["complete"] and not w["inference_ready"]


def test_native_receiver_intervals_omit_warmup_do_not_use_sender_or_end_summary():
    s = snapshot(20)
    native = {"start": {"timestamp": {"timemillisecs": int(BASE.timestamp() * 1000)}},
        "intervals": [{"sum": {"start": 0, "end": 2, "seconds": 2, "bytes": 100, "omitted": True, "sender": False}},
            {"sum": {"start": 0, "end": 1, "seconds": 1, "bytes": 1000, "packets": 10,
                     "lost_packets": 1, "jitter_ms": 7, "omitted": False, "sender": False}}],
        "end": {"sum_received": {"bytes": 999999}}}
    s["completed_runs"] = [{"run_id": "r1", "state": "succeeded", "profiles": [{"parameters": {
        "profile_id": "critical", "source_host": "h1", "target_host": "h3", "protocol": "udp"}, "server_json": native}]}]
    rows = receiver_records(s, "t1")
    assert len(rows) == 1 and rows[0]["bytes"] == 1000
    assert rows[0]["start_monotonic_s"] == pytest.approx(2)
    assert rows[0]["available_utc"] == s["at_utc"]
    assert receiver_records(s, "t1")[0]["sample_id"] == rows[0]["sample_id"]


def test_jsonl_dedup_partial_tail_recovery_and_truth_exclusion(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    store.insert_record("runs", "t1", {}, config_hash="hash")
    repo = TelemetryRepository(store)
    row = snapshot(1)
    assert repo.ingest(row)
    assert not repo.ingest(row)
    with pytest.raises(ValueError, match="different contents"):
        repo.ingest(row | {"monotonic_s": 2})
    with pytest.raises(ValueError, match="ground truth"):
        repo.ingest(row | {"extra": {"fault_label": "loss"}})
    path = repo.directory / "t1.jsonl"
    orphan = snapshot(2)
    with path.open("ab") as out:
        out.write(json.dumps(orphan).encode() + b"\n" + b'{"partial":')
    recovered = repo.recover("t1")
    assert recovered == {"recovered": 1, "partial_tail_bytes": 11}
    assert len(repo.samples("t1")) == 2 and path.read_bytes().endswith(b"\n")
    assert path.with_suffix(".partial").exists()


def monitor_window(index, loss=0):
    window = aggregate_windows([snapshot(t) for t in range(11)], session(), TelemetrySettings(), 10)[0]
    window.update(window_id=f"w{index}", start_monotonic_s=index * 10, end_monotonic_s=(index + 1) * 10)
    window["features"]["udp_loss_fraction"] = loss
    return window


def test_baseline_persistence_hysteresis_low_demand_and_stale(tmp_path):
    settings = TelemetrySettings()
    objective = ServiceObjective(max_loss_fraction=0.02, max_rtt_ms=100)
    windows = [monitor_window(0, 0.1), monitor_window(1, 0.1), monitor_window(2, 0.019),
               monitor_window(3, 0), monitor_window(4, 0)]
    assert [a["status"] for a in evaluate(windows, settings, objective)] == ["healthy", "alert", "alert", "alert", "healthy"]
    low = monitor_window(0)
    low["features"].update(critical_offered_bps=1000, critical_goodput_bps=10)
    assert not rules(low, settings, objective)
    high = deepcopy(low)
    high["features"]["critical_offered_bps"] = 2_000_000
    assert any(r["rule"] == "delivered_demand" for r in rules(high, settings, objective))
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    service = TelemetryService(store, SimpleNamespace(), settings, objective)
    assert service.status("lab1")["live"] is False
    assert service.alerts("lab1")["latest"]["status"] == "stale"


def test_saved_windows_reconstruct_and_ready_view_has_only_allowlisted_features(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    store.insert_record("runs", "t1", {}, config_hash="hash")
    repo = TelemetryRepository(store)
    records = [snapshot(t) for t in range(11)]
    for record in records:
        repo.ingest(record)
    settings = TelemetrySettings()
    windows = aggregate_windows(repo.samples("t1"), session(), settings, 10)
    alerts = evaluate(windows, settings, ServiceObjective(max_rtt_ms=100, max_loss_fraction=0.02))
    repo.save_windows(windows, alerts)
    assert aggregate_windows(records, session(), settings, 10)[0]["features"] == windows[0]["features"]
    with store.connection() as db:
        features = json.loads(db.execute("SELECT features_json FROM inference_ready_windows").fetchone()[0])
        assert set(features) == FEATURES
        assert not {"run_id", "at_utc", "label", "severity"} & set(features)
