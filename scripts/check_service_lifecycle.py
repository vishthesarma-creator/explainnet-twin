#!/usr/bin/env python3
"""Real local agent/API/job/restart check; run as WSL root with --app-uid."""

import argparse
import json
import os
import pwd
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_SOCKET = Path("/run/explainnet/agent.sock")
BASE = "http://127.0.0.1:8765"


def http(path: str, method: str = "GET") -> tuple[int, dict]:
    request = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as response:
        return response.code, json.load(response)


def wait_http(timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            http("/v1/health")
            return
        except urllib.error.URLError:
            time.sleep(0.1)
    raise TimeoutError("API did not start")


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-uid", type=int, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or args.app_uid < 1:
        parser.error("run as root and pass a non-root app UID")
    if AGENT_SOCKET.exists():
        parser.error("agent socket exists; refusing to interfere with another agent")
    venv = ROOT / ".venv" / "bin" / "python"
    config = ROOT / "config" / "example.yaml"
    app_gid = pwd.getpwuid(args.app_uid).pw_gid

    app_cmd = [str(venv), "-m", "explainnet.cli", "--config", str(config)]
    subprocess.run([*app_cmd, "init"], cwd=ROOT, check=True, timeout=15,
                   user=args.app_uid, group=app_gid, extra_groups=[],
                   capture_output=True, text=True)
    agent = service = None
    result = {"agent": False, "service": False, "job": False, "restart_persistence": False,
              "clean_shutdown": False}
    try:
        agent = subprocess.Popen([sys.executable, str(ROOT / "src" / "explainnet" / "agent_server.py"),
                                  "--allow-uid", str(args.app_uid)], cwd=ROOT,
                                 env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while not AGENT_SOCKET.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not AGENT_SOCKET.exists():
            raise RuntimeError("agent socket not created")
        service = subprocess.Popen([*app_cmd, "serve"], cwd=ROOT,
                                   user=args.app_uid, group=app_gid, extra_groups=[],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        wait_http()
        status, health = http("/v1/health")
        assert status == 200 and health["status"] == "healthy", health
        status, capabilities = http("/v1/capabilities")
        assert status == 200 and capabilities["agent"]["mininet_python"] is True
        assert "repair" in capabilities["agent"]["unsupported"]
        status, inventory = http("/v1/agent/inventory")
        assert status == 200 and inventory["inventory"]["bridges"] == []
        cli_status = subprocess.run([*app_cmd, "status"], cwd=ROOT,
                                    user=args.app_uid, group=app_gid, extra_groups=[],
                                    capture_output=True, text=True, check=True, timeout=5)
        assert json.loads(cli_status.stdout)["status"] == "healthy"
        result["agent"] = result["service"] = True
        status, submission = http("/v1/jobs/environment-check", "POST")
        assert status == 202, submission
        job_id = submission["job_id"]
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            _, job = http(f"/v1/jobs/{job_id}")
            if job["state"] in ("succeeded", "failed"):
                break
            time.sleep(0.1)
        assert job["state"] == "succeeded" and job["result"]["status"] == "healthy", job
        result["job"] = True
        cli_stop = subprocess.run([*app_cmd, "stop"], cwd=ROOT,
                                  user=args.app_uid, group=app_gid, extra_groups=[],
                                  capture_output=True, text=True, check=True, timeout=5)
        assert json.loads(cli_stop.stdout)["stopping"] is True
        service.wait(timeout=8)
        assert service.returncode == 0
        service = subprocess.Popen([*app_cmd, "serve"], cwd=ROOT,
                                   user=args.app_uid, group=app_gid, extra_groups=[],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        wait_http()
        _, persisted = http(f"/v1/jobs/{job_id}")
        assert persisted["state"] == "succeeded" and persisted["result"]["status"] == "healthy"
        result["restart_persistence"] = True
        status, _ = http("/v1/control/stop", "POST")
        assert status == 200
        service.wait(timeout=8)
        assert service.returncode == 0
        service = None
        stop_process(agent)
        agent = None
        result["clean_shutdown"] = not AGENT_SOCKET.exists()
    finally:
        stop_process(service)
        stop_process(agent)
        print(json.dumps(result, indent=2))
        output = ROOT / "artifacts" / "service_lifecycle.json"
        output.write_text(json.dumps(result, indent=2) + "\n")
    if not all(result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
