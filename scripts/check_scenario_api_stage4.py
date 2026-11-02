#!/usr/bin/env python3
"""Real unprivileged API/jobs/CLI to privileged agent round trip, isolated storage."""

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
OUT = ROOT / "artifacts/stage4"


def main():
    uid = int(sys.argv[1])
    gid = pwd.getpwuid(uid).pw_gid
    tag = uuid4().hex[:8]
    base = Path(tempfile.mkdtemp(prefix="explainnet-stage4-api-"))
    app_dir = base / "app"
    app_dir.mkdir()
    os.chmod(base, 0o755)
    os.chown(app_dir, uid, gid)
    socket_dir = Path("/run") / ("explainnet-stage4-" + tag)
    sock = socket_dir / "agent.sock"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    config = app_dir / "config.json"
    config.write_text(json.dumps({"schema_version": 1, "data_dir": str(app_dir / "data"),
        "runtime_dir": str(app_dir / "run"), "agent_socket": str(sock), "host": "127.0.0.1", "port": port,
        "topology_file": str(ROOT / "config/topology.yaml"), "traffic_profiles_file": str(ROOT / "config/traffic.yaml")}))
    cli = [str(ROOT / ".venv/bin/explainnet"), "--config", str(config)]
    def app_cli(*args):
        result = subprocess.run([*cli, *args], cwd=ROOT, user=uid, group=gid, extra_groups=[], capture_output=True,
            text=True, timeout=20, check=True)
        return json.loads(result.stdout)
    def request(path, payload=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    def job(submission, expected="succeeded"):
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            result = request("/v1/jobs/" + submission["job_id"])
            if result["state"] in {"succeeded", "failed"}:
                assert result["state"] == expected, result
                return result
            time.sleep(0.1)
        raise TimeoutError("API job deadline")
    agent = service = None
    report = {"status": "partial", "checks": {}, "errors": []}
    logs = [(OUT / "api_roundtrip_agent.log").open("w"), (OUT / "api_roundtrip_service.log").open("w")]
    instance = "api_" + tag
    try:
        app_cli("init")
        agent = subprocess.Popen([sys.executable, "-m", "explainnet.agent_server", "--socket", str(sock),
            "--state-dir", str(base / "root"), "--allow-uid", str(uid)], cwd=ROOT, stdout=logs[0], stderr=logs[0])
        deadline = time.monotonic() + 10
        while not sock.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        service = subprocess.Popen([*cli, "serve"], cwd=ROOT, user=uid, group=gid, extra_groups=[], stdout=logs[1], stderr=logs[1])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if request("/v1/health")["status"] == "healthy":
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        report["checks"]["network_start"] = job(app_cli("network-start", instance))
        recipe = {"schema_version": 1, "config_version": "pilot_v1", "kind": "latency", "severity": "low",
            "warmup_s": 1, "measurement_s": 15, "bidirectional": True, "variation_ms": 5,
            "high_utilization": False, "traffic_profile": "moderate"}
        recipe_file = app_dir / "scenario.json"
        recipe_file.write_text(json.dumps(recipe))
        report["checks"]["cli_scenario_start"] = job(app_cli("scenario-start", instance, str(recipe_file)))
        active = app_cli("scenario-status", instance)
        assert "delay 16ms  5ms" in active["observed_tc"]["s2->s3"]["qdisc_raw"]
        assert "delay 16ms  5ms" in active["observed_tc"]["s3->s2"]["qdisc_raw"]
        report["checks"]["bidirectional_variation_observed"] = active
        repeated = job(app_cli("scenario-start", instance, str(recipe_file)))
        assert repeated["result"]["traffic_runs"][0]["run_id"] == active["traffic_runs"][0]["run_id"]
        report["checks"]["idempotent_job"] = repeated
        report["checks"]["overlap_rejected"] = job(request("/v1/laboratory/scenarios/start",
            {"instance_id": instance, "scenario": recipe | {"kind": "loss", "variation_ms": 0}}), expected="failed")
        for path, body, status in (("/v1/laboratory/scenarios/start", {"instance_id": instance,
            "scenario": recipe | {"measurement_s": 999}}, 422), ("/v1/jobs/repair", {}, 501)):
            try:
                request(path, body)
                raise AssertionError("invalid operation accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == status
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ended = app_cli("scenario-status", instance)
            if ended["laboratory_journal"]["state"] == "stopped":
                break
            time.sleep(0.2)
        assert ended["laboratory_journal"]["state"] == "stopped"
        report["checks"]["deadline_auto_reset"] = ended
        report["checks"]["cli_reset"] = job(app_cli("scenario-reset", instance))
        report["checks"]["cli_stop"] = job(app_cli("scenario-stop", instance))
        # Read SQLite through the ordinary app Python, preserving the production DB.
        query = subprocess.run([str(ROOT / ".venv/bin/python"), "-c",
            "import sqlite3,json,sys;d=sqlite3.connect(sys.argv[1]);print(json.dumps({'runs':[json.loads(r[0]) for r in d.execute('select payload_json from runs')],'truth':[json.loads(r[0]) for r in d.execute('select payload_json from ground_truth')]}))",
            str(app_dir / "data/explainnet.sqlite3")], user=uid, group=gid, extra_groups=[], text=True, capture_output=True, check=True)
        records = json.loads(query.stdout)
        assert len(records["runs"]) == len(records["truth"]) == 1
        assert "fault_label" not in records["runs"][0]
        assert records["truth"][0]["fault_label"] == "latency"
        assert records["truth"][0]["deactivated_utc"]
        report["checks"]["separate_persisted_ground_truth"] = records
        report["checks"]["network_stop"] = job(app_cli("network-stop", instance))
        app_cli("stop")
        service.wait(timeout=10)
        agent.terminate()
        agent.wait(timeout=15)
        report["status"] = "complete"
    except Exception:  # noqa: BLE001 - save actual API integration failures
        report["errors"].append(traceback.format_exc())
    finally:
        for proc in (service, agent):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for log in logs:
            log.close()
        shutil.copytree(base, OUT / ("api_roundtrip_" + tag))
        assert base.resolve().parent == Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(base)
        if socket_dir.exists() and not list(socket_dir.iterdir()):
            socket_dir.rmdir()
        (OUT / "api_roundtrip_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "errors": report["errors"]}))
    return int(report["status"] != "complete")


if __name__ == "__main__":
    raise SystemExit(main())
