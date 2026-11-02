#!/usr/bin/env python3
"""Bounded real packets, using the persistent Stage 3 owner and traffic engine."""

import json
import re
import shutil
import subprocess
import tempfile
import time
import traceback
from pathlib import Path
from uuid import uuid4

from explainnet.network_runtime import NetworkManager, command, host_command, utc
from explainnet.scenario_spec import recipe

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "stage4"


def scenario(kind, **overrides):
    return {"schema_version": 1, "config_version": "pilot_v1", "kind": kind, "severity": "high",
            "warmup_s": 2, "measurement_s": 8, "bidirectional": False, "variation_ms": 0,
            "high_utilization": False, "traffic_profile": "qos_competing" if kind == "qos" else
            "shared" if kind == "saturation" else "moderate", **overrides}


def ping(manager, instance):
    live = manager.instances[instance]
    result = host_command(live["hosts"]["h1"], ["ping", "-n", "-c", "20", "-i", "0.1", "-W", "1",
        "-w", "5", live["record"]["hosts"]["h3"]["ip"]], timeout=6, check=False)
    match = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", result["stdout"])
    result["rtt_avg_ms"] = float(match[2]) if match else None
    result["rtt_mdev_ms"] = float(match[4]) if match else None
    return result


def trial(manager, instance, config, name):
    initial = manager.scenarios.start(instance, config)
    run_id = initial["traffic_runs"][0]["run_id"]
    repeated = manager.scenarios.start(instance, config)
    assert repeated["traffic_runs"][0]["run_id"] == run_id
    assert len(manager.sessions) == 1
    try:
        manager.scenarios.start(instance, config | {"severity": "low"})
        raise AssertionError("overlap accepted")
    except ValueError as exc:
        overlap = str(exc)
    before = manager.scenarios.evidence(manager.instances[instance])
    started = time.monotonic()
    probes = ping(manager, instance)
    deadline = time.monotonic() + config["measurement_s"] + 8
    while time.monotonic() < deadline:
        run = manager.traffic_status(instance, run_id)
        if run["state"] != "running":
            break
        time.sleep(0.1)
    assert run["state"] == "succeeded", run
    after = manager.scenarios.inspect(instance)
    elapsed = time.monotonic() - started
    receivers = {}
    for item in run["profiles"]:
        end = item["server_json"]["end"]
        summary = end.get("sum_received", end.get("sum"))
        receivers[item["parameters"]["profile_id"]] = summary
    def root_bytes(evidence):
        return next(c["stats"]["bytes"] for c in evidence["s2->s3"]["class_counters"] if c["handle"] == "5:1")
    utilization = (root_bytes(after["observed_tc"]) - root_bytes(before)) * 8 / elapsed / 100_000_000
    result = {"parameters": config, "recipe": recipe(config), "receivers": receivers, "ping": probes,
              "measurement_elapsed_s": elapsed, "s2_s3_utilization_fraction": utilization,
              "measurement_counters_before": before, "active": after, "idempotent": True,
              "overlap_error": overlap}
    result["observed_summary"] = {"critical_goodput_bps": receivers["critical"]["bits_per_second"],
        "critical_loss_fraction": receivers["critical"]["lost_percent"] / 100,
        "rtt_avg_ms": probes["rtt_avg_ms"], "shared_utilization_fraction": utilization}
    # JSON copy prevents the mutable owner journal from rewriting the active evidence after reset.
    result = json.loads(json.dumps(result))
    result["reset"] = manager.scenarios.reset(instance)
    again = manager.scenarios.reset(instance)
    assert again["laboratory_journal"]["state"] == "stopped"
    (OUT / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state = Path(tempfile.mkdtemp(prefix="explainnet-stage4-"))
    manager = NetworkManager(state)
    tag = uuid4().hex[:8]
    instance, guard = "fault_" + tag, "guard" + tag
    report = {"schema_version": 1, "checked_utc": utc(), "status": "partial", "trials": {},
              "errors": [], "limitations": ["Netem seed is used only when the live qdisc reports kernel/tool support; scheduling prevents exact packet-sequence reproducibility.",
                  "Pilot results are WSL scheduling dependent; no full dataset or telemetry collector.",
                  "Linux HTB/flower owns queues; no OVS QoS/Queue rows are created."]}
    before_bridges = command("ovs-vsctl", "list-br").splitlines()
    try:
        definition = json.loads(subprocess.run([str(ROOT / ".venv/bin/python"), "-c",
            "import yaml,json;print(json.dumps(yaml.safe_load(open('config/topology.yaml'))))"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        command("ovs-vsctl", "add-br", guard, "--", "set", "Bridge", guard, f"external_ids:stage4_guard={tag}")
        manager.start(instance, definition)
        report["network_before"] = manager.inspect(instance)
        assert manager.probe(instance)["passed"]
        for kind in ("saturation", "loss", "latency", "qos"):
            control = scenario("healthy", traffic_profile="qos_competing" if kind == "qos" else "moderate")
            baseline = trial(manager, instance, control, kind + "_baseline")
            fault = trial(manager, instance, scenario(kind), kind + "_fault")
            restored = trial(manager, instance, control, kind + "_restored")
            report["trials"][kind] = {"baseline": baseline, "fault": fault, "restored": restored}
            b, f, r = [x["receivers"]["critical"] for x in (baseline, fault, restored)]
            if kind in {"saturation", "loss"}:
                assert f["lost_percent"] > b["lost_percent"] + (1 if kind == "saturation" else 5), (b, f)
                assert r["lost_percent"] < 2, r
            if kind == "saturation":
                assert fault["s2_s3_utilization_fraction"] > 0.85
            if kind in {"loss", "latency"}:
                assert fault["s2_s3_utilization_fraction"] < 0.3
                assert fault["active"]["observed_tc"]["s3->s2"]["qdisc_raw"] == baseline["active"]["observed_tc"]["s3->s2"]["qdisc_raw"]
            if kind == "latency":
                assert fault["ping"]["rtt_avg_ms"] > baseline["ping"]["rtt_avg_ms"] + 45
                assert abs(restored["ping"]["rtt_avg_ms"] - baseline["ping"]["rtt_avg_ms"]) < 15
            if kind == "qos":
                assert b["bits_per_second"] > 1_800_000 and b["lost_percent"] < 2
                assert f["bits_per_second"] < 900_000 and f["lost_percent"] > 50
                assert r["bits_per_second"] > 1_800_000 and r["lost_percent"] < 2
                for sample in (baseline, fault, restored):
                    classes = sample["active"]["observed_tc"]["s3->s5"]["class_counters"]
                    assert all(next(c["stats"]["bytes"] for c in classes if c["handle"] == handle) > 0 for handle in ("5:10", "5:20"))
            assert command("ovs-vsctl", "get", "Bridge", guard, "external_ids:stage4_guard").strip('"') == tag
        report["healthy_high_utilization"] = trial(manager, instance,
            scenario("healthy", traffic_profile="shared", high_utilization=True), "healthy_high_utilization")
        high = report["healthy_high_utilization"]
        assert high["s2_s3_utilization_fraction"] > 0.7
        assert high["receivers"]["critical"]["lost_percent"] < 2
        assert high["ping"]["rtt_avg_ms"] < 100
        report["network_after"] = manager.inspect(instance)
        def rules(raw):
            return sorted(line.split(" priority=", 1)[-1] for line in raw.splitlines() if " priority=" in line)
        assert all(rules(raw) == rules(report["network_after"]["forwarding"][switch])
                   for switch, raw in report["network_before"]["forwarding"].items())
        report["forwarding_preserved"] = True
        report["status"] = "complete"
    except Exception:  # noqa: BLE001 - preserve actual integration failure
        report["errors"].append(traceback.format_exc())
    finally:
        try:
            manager.shutdown()
        except Exception:  # noqa: BLE001 - report owned cleanup failure
            report["errors"].append(traceback.format_exc())
        if guard in command("ovs-vsctl", "list-br").splitlines() and command("ovs-vsctl", "get", "Bridge", guard,
                "external_ids:stage4_guard").strip('"') == tag:
            command("ovs-vsctl", "del-br", guard)
        shutil.copytree(state, OUT / ("ownership_" + tag))
        assert state.resolve().parent == Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(state)
        report["cleanup_preserved_bridges"] = command("ovs-vsctl", "list-br").splitlines() == before_bridges
        report["remaining_sessions"] = len(manager.sessions)
        (ROOT / "artifacts/fault_smoke_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "errors": report["errors"]}))
    return 0 if report["status"] == "complete" and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
