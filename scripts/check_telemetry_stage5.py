#!/usr/bin/env python3
"""Bounded real telemetry pilot; root supervisor, ordinary-user API, no synthetic data."""

import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/stage5"


def main():
    uid = int(sys.argv[1])
    gid = pwd.getpwuid(uid).pw_gid
    OUT.mkdir(parents=True, exist_ok=True)
    tag = uuid4().hex[:8]
    base = Path(tempfile.mkdtemp(prefix="explainnet-stage5-"))
    os.chmod(base, 0o755)
    app_dir = base / "app"
    app_dir.mkdir()
    os.chown(app_dir, uid, gid)
    socket_dir = Path("/run") / ("explainnet-stage5-" + tag)
    config = app_dir / "config.json"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    config.write_text(json.dumps({"schema_version": 1, "data_dir": str(app_dir / "data"),
        "runtime_dir": str(app_dir / "run"), "agent_socket": str(socket_dir / "agent.sock"), "host": "127.0.0.1", "port": port,
        "topology_file": str(ROOT / "config/topology.yaml"), "traffic_profiles_file": str(ROOT / "config/traffic.yaml"),
        "objective": {"max_rtt_ms": 100, "max_loss_fraction": 0.02},
        "telemetry": {"sample_interval_s": 1, "window_s": 10, "consecutive_windows": 1, "recovery_windows": 1}}))
    cli = [str(ROOT / ".venv/bin/explainnet"), "--config", str(config)]
    report = {"schema_version": 1, "status": "partial", "checks": {}, "cases": {}, "errors": [],
        "limitations": ["Receiver intervals arrive only at run completion; completed windows are revised from late raw intervals.",
            "Real bounded pilots use one valid-window persistence/recovery; default two-window hysteresis is tested separately.",
            "Only Linux WSL VM resource pressure is measured, not the outer Windows host.",
            "Interval absolute timestamps use native receiver millisecond start and actual omitted duration; no submillisecond alignment claim."]}
    agent = service = None
    instance = "telemetry_" + tag
    logs = [(OUT / "agent.log").open("w"), (OUT / "api.log").open("w")]
    before = subprocess.run(["ovs-vsctl", "list-br"], text=True, capture_output=True, check=True).stdout.splitlines()

    def checkpoint():
        (ROOT / "artifacts/telemetry_smoke_report.json").write_text(json.dumps(report, indent=2) + "\n")

    def app_cli(*args):
        result = subprocess.run([*cli, *args], cwd=ROOT, user=uid, group=gid, extra_groups=[],
            capture_output=True, text=True, timeout=25, check=True)
        return json.loads(result.stdout)

    def request(path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
            data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)

    def job(path, body):
        started = time.monotonic()
        submission = request(path, body)
        submission_ms = (time.monotonic() - started) * 1000
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            result = request("/v1/jobs/" + submission["job_id"])
            if result["state"] in {"succeeded", "failed"}:
                assert result["state"] == "succeeded", result
                return result["result"], submission_ms
            time.sleep(0.1)
        raise TimeoutError("job exceeded bounded deadline")

    def collector_start(duration=80):
        result, latency = job("/v1/telemetry/start", {"instance_id": instance, "duration_s": duration})
        repeated, _ = job("/v1/telemetry/start", {"instance_id": instance, "duration_s": duration})
        assert result["session"]["run_id"] == repeated["session"]["run_id"]
        report["checks"].setdefault("collector_submission_ms", []).append(latency)
        return result["session"]["run_id"]

    def wait_traffic(run_id):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            result = request(f"/v1/traffic/{instance}/{run_id}")
            if result["state"] != "running":
                assert result["state"] == "succeeded", result
                return result
            time.sleep(0.3)
        raise TimeoutError("traffic did not finish")

    def wait_ready(collection_id, traffic_run_id, timeout=12):
        deadline = time.monotonic() + timeout
        latest = None
        while time.monotonic() < deadline:
            latest = request(f"/v1/telemetry/{instance}/windows?limit=100")
            suitable = [w for w in latest["windows"] if w["run_id"] == collection_id and w["inference_ready"]
                        and traffic_run_id in w["context"]["traffic_run_ids"]]
            if suitable:
                return suitable[0], latest
            time.sleep(0.3)
        raise AssertionError("no suitable real window: " + json.dumps(latest))

    def ordinary_traffic(rate=2_000_000):
        # Use the existing profile loader and engine. Override only the critical rate in a separate run.
        if rate == 2_000_000:
            result, _ = job("/v1/traffic/start", {"instance_id": instance, "profile_ids": ["critical", "bulk"], "duration_s": 24})
        else:
            result, _ = job("/v1/traffic/start", {"instance_id": instance, "profile_ids": ["critical"],
                "offered_bps": rate, "duration_s": 24})
        return result["run_id"]

    try:
        assert json.loads((ROOT / "artifacts/network_smoke_report.json").read_text())["status"] == "complete"
        assert json.loads((ROOT / "artifacts/fault_smoke_report.json").read_text())["status"] == "complete"
        app_cli("init")
        agent = subprocess.Popen([sys.executable, "-m", "explainnet.agent_server", "--socket", str(socket_dir / "agent.sock"),
            "--state-dir", str(base / "root"), "--allow-uid", str(uid)], cwd=ROOT, stdout=logs[0], stderr=logs[0])
        deadline = time.monotonic() + 10
        while not (socket_dir / "agent.sock").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        service = subprocess.Popen([*cli, "serve"], cwd=ROOT, user=uid, group=gid, extra_groups=[], stdout=logs[1], stderr=logs[1])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if request("/v1/health")["status"] == "healthy":
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        network, _ = job("/v1/networks/start", {"instance_id": instance})
        report["checks"]["verified_network"] = network
        initial = request(f"/v1/networks/{instance}")
        collection = collector_start(45)
        run_id = ordinary_traffic()
        healthy_run = wait_traffic(run_id)
        healthy, views = wait_ready(collection, run_id)
        assert healthy["features"]["udp_loss_fraction"] < 0.02 and healthy["features"]["critical_goodput_bps"] > 1_800_000
        assert healthy["per_flow"]["h2->h4:tcp"]["delivered_bps"] > 4_000_000
        reference, _ = job("/v1/telemetry/reference", {"window_id": healthy["window_id"]})
        report["cases"]["healthy"] = {"window": healthy, "windows": views, "traffic_run": healthy_run,
            "reference": reference, "baseline": request(f"/v1/telemetry/{instance}/alerts")}
        job("/v1/telemetry/stop", {"instance_id": instance})
        assert request(f"/v1/telemetry/{instance}/alerts")["latest"]["status"] == "stale"
        report["checks"]["stopped_history_is_stale"] = True
        checkpoint()
        selected = sys.argv[2:] or ["saturation", "loss", "latency", "qos"]
        if set(selected) - {"saturation", "loss", "latency", "qos"}:
            raise ValueError("unknown bounded fault trial")
        for kind in selected:
            collection = collector_start(80)
            scenario = {"schema_version": 1, "config_version": "pilot_v1", "kind": kind, "severity": "high",
                "warmup_s": 2, "measurement_s": 20, "bidirectional": False, "variation_ms": 0,
                "high_utilization": False, "traffic_profile": "qos_competing" if kind == "qos" else
                "shared" if kind == "saturation" else "moderate"}
            started, _ = job("/v1/laboratory/scenarios/start", {"instance_id": instance, "scenario": scenario})
            fault_run_id = started["traffic_runs"][0]["run_id"]
            fault_run = wait_traffic(fault_run_id)
            fault, views = wait_ready(collection, fault_run_id)
            alerts = request(f"/v1/telemetry/{instance}/alerts")
            matching_alert = next(a for a in alerts["history"] if a["window_id"] == fault["window_id"])
            assert matching_alert["status"] == "alert", matching_alert
            f = fault["features"]
            if kind in {"saturation", "loss"}:
                assert f["udp_loss_fraction"] > (0.05 if kind == "loss" else 0.1)
            if kind == "saturation":
                assert f["shared_utilization_fraction"] > 0.85
            if kind == "latency":
                assert f["rtt_mean_ms"] > healthy["features"]["rtt_mean_ms"] + 45
            if kind == "qos":
                assert f["critical_goodput_bps"] < 800_000 and f["critical_class_rate_bps"] < 800_000
            reset, _ = job("/v1/laboratory/scenarios/reset", {"instance_id": instance})
            if kind == "qos":
                restored, _ = job("/v1/laboratory/scenarios/start", {"instance_id": instance,
                    "scenario": scenario | {"kind": "healthy"}})
                restored_run_id = restored["traffic_runs"][0]["run_id"]
            else:
                restored_run_id = ordinary_traffic(8_000_000)
            restored_run = wait_traffic(restored_run_id)
            recovered, recovery_views = wait_ready(collection, restored_run_id)
            assert recovered["features"]["udp_loss_fraction"] < 0.02
            assert recovered["features"]["critical_goodput_bps"] > (1_800_000 if kind == "qos" else 7_000_000)
            recovered_alerts = request(f"/v1/telemetry/{instance}/alerts")
            recovery_alert = next(a for a in recovered_alerts["history"] if a["window_id"] == recovered["window_id"])
            assert recovery_alert["status"] == "healthy", recovery_alert
            if kind == "qos":
                job("/v1/laboratory/scenarios/reset", {"instance_id": instance})
            report["cases"][kind] = {"window": fault, "windows": views, "traffic_run": fault_run,
                "baseline": matching_alert, "reset": reset, "restored_window": recovered,
                "restored_windows": recovery_views, "restored_traffic_run": restored_run, "restored_baseline": recovery_alert}
            job("/v1/telemetry/stop", {"instance_id": instance})
            checkpoint()
        final = request(f"/v1/networks/{instance}")
        def rules(raw):
            return sorted(line.split(" priority=", 1)[1] for line in raw.splitlines() if " priority=" in line)
        assert all(rules(raw) == rules(final["forwarding"][key]) for key, raw in initial["forwarding"].items())
        report["checks"]["forwarding_preserved"] = True
        report["checks"]["cli_status"] = app_cli("telemetry-status", instance)
        report["checks"]["cli_windows"] = app_cli("telemetry-windows", instance)
        report["checks"]["cli_alerts"] = app_cli("telemetry-alerts", instance)
        job("/v1/networks/stop", {"instance_id": instance})
        app_cli("stop")
        service.wait(timeout=20)
        agent.terminate()
        agent.wait(timeout=20)
        report["status"] = "complete"
    except Exception:  # noqa: BLE001 - preserve actual packet-level verification failures
        report["errors"].append(traceback.format_exc())
    finally:
        for process in (service, agent):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in logs:
            log.close()
        shutil.copytree(base, OUT / ("raw_and_storage_" + tag))
        assert base.resolve().parent == Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(base)
        if socket_dir.exists() and not list(socket_dir.iterdir()):
            socket_dir.rmdir()
        after = subprocess.run(["ovs-vsctl", "list-br"], text=True, capture_output=True, check=True).stdout.splitlines()
        report["checks"]["bridge_cleanup_preserved"] = before == after
        checkpoint()
    print(json.dumps({"status": report["status"], "errors": report["errors"]}))
    return int(report["status"] != "complete")


if __name__ == "__main__":
    raise SystemExit(main())
