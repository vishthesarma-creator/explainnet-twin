#!/usr/bin/env python3
"""Persistent root supervisor; ordinary-user API owns the durable dataset runner."""

import argparse
import fcntl
import json
import os
import pwd
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(config, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{config['port']}" + path,
        data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def job(config, path, body):
    submission = request(config, path, body)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = request(config, "/v1/jobs/" + submission["job_id"])
        if state["state"] in {"succeeded", "failed"}:
            if state["state"] == "failed":
                raise RuntimeError(state["error"])
            return state["result"], submission["job_id"]
        time.sleep(0.2)
    raise TimeoutError("supervisor submission exceeded bounded deadline")


def supervise(args):
    declared = json.loads(args.schedule.read_text())
    if declared["purpose"] == "main":
        pilot = json.loads((ROOT / "artifacts/stage6/pilot_report.json").read_text())
        if pilot["status"] != "complete" or not pilot["quality"]["structural_checks_passed"] or pilot["quality"]["shortfalls"]:
            raise ValueError("main collection requires a completed, audited five-class pilot")
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    gid = pwd.getpwuid(args.uid).pw_gid
    config_path = runtime / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        config = {"schema_version": 1, "data_dir": str(runtime / "app/data"),
            "runtime_dir": str(runtime / "app/run"), "agent_socket": f"/run/explainnet-stage6-{port}/agent.sock",
            "host": "127.0.0.1", "port": port, "topology_file": str(ROOT / "config/topology.yaml"),
            "traffic_profiles_file": str(ROOT / "config/traffic.yaml"),
            "objective": {"max_rtt_ms": 100, "max_loss_fraction": 0.02},
            "dataset_artifact_dir": str(ROOT / "artifacts"), "telemetry": {"sample_interval_s": 1, "window_s": 10}}
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    app_dir = runtime / "app"
    app_dir.mkdir(exist_ok=True)
    os.chown(app_dir, args.uid, gid)
    os.chmod(runtime, 0o755)
    cli = [str(ROOT / ".venv/bin/explainnet"), "--config", str(config_path)]
    report = {"schema_version": 1, "state": "starting", "supervisor_pid": os.getpid(),
              "config": str(config_path), "schedule": str(args.schedule.resolve()), "errors": [],
              "root_state_dir": f"/var/lib/explainnet-stage6-{config['port']}"}

    def checkpoint():
        temp = runtime / "supervisor.json.tmp"
        temp.write_text(json.dumps(report, indent=2) + "\n")
        temp.replace(runtime / "supervisor.json")

    agent = api = None
    before = subprocess.run(["ovs-vsctl", "list-br"], text=True, capture_output=True, check=True).stdout.splitlines()
    with (runtime / "supervisor.lock").open("a+") as lock, (runtime / "agent.log").open("a") as agent_log, (runtime / "api.log").open("a") as api_log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            subprocess.run([*cli, "init"], cwd=ROOT, user=args.uid, group=gid, extra_groups=[], check=True, timeout=30)
            agent = subprocess.Popen([sys.executable, "-m", "explainnet.agent_server", "--socket", config["agent_socket"],
                "--state-dir", report["root_state_dir"], "--allow-uid", str(args.uid)], cwd=ROOT, stdout=agent_log, stderr=agent_log)
            deadline = time.monotonic() + 20
            while not Path(config["agent_socket"]).exists() and time.monotonic() < deadline:
                if agent.poll() is not None:
                    raise RuntimeError("agent startup failed; see agent.log")
                time.sleep(0.1)
            api = subprocess.Popen([*cli, "serve"], cwd=ROOT, user=args.uid, group=gid, extra_groups=[], stdout=api_log, stderr=api_log)
            report.update(agent_pid=agent.pid, api_pid=api.pid)
            for _ in range(300):
                try:
                    if request(config, "/v1/health")["status"] == "healthy":
                        break
                except OSError:
                    if api.poll() is not None:
                        raise RuntimeError("API exited during startup; see api.log")
                    time.sleep(0.2)
            else:
                raise RuntimeError("API startup failed; see api.log")
            if args.resume:
                batch_id = args.resume
                started, start_job = job(config, "/v1/datasets/resume", {"batch_id": batch_id})
            else:
                planned, plan_job = job(config, "/v1/datasets/plan", {"schedule": declared})
                batch_id = planned["batch_id"]
                report["plan_job_id"] = plan_job
                started, start_job = job(config, "/v1/datasets/start", {"batch_id": batch_id})
            report.update(batch_id=batch_id, start_job_id=start_job, state="running", runner_pid=started["runner_pid"])
            checkpoint()
            stopping = False

            def stop(_signal, _frame):
                nonlocal stopping
                stopping = True

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            while True:
                if stopping:
                    job(config, "/v1/datasets/cancel", {"batch_id": batch_id})
                    stopping = False
                if api.poll() is not None or agent.poll() is not None:
                    raise RuntimeError("owned service exited during collection")
                status = request(config, "/v1/datasets/" + batch_id)
                if status['batch']['state'] == 'running' and not status['live']:
                    raise RuntimeError('dataset thread is no longer alive; explicit resume required')
                report.update(state=status["batch"]["state"], completed_episodes=status["completed_episodes"],
                    accepted_windows=status["accepted_windows"], current_episode=status["batch"].get("current_episode"),
                    manifest_path=status["manifest_path"], error=status["batch"].get("error"))
                checkpoint()
                if report["state"] in {"completed", "failed", "canceled", "interrupted"}:
                    break
                time.sleep(10)
        except Exception as exc:  # noqa: BLE001 - durable supervisor diagnostics
            report.update(state="failed")
            report["errors"].append(str(exc))
        finally:
            if api and api.poll() is None:
                try:
                    request(config, "/v1/control/stop", {})
                    api.wait(timeout=130)
                except (OSError, subprocess.TimeoutExpired):
                    api.terminate()
                    api.wait(timeout=130)
            if agent and agent.poll() is None:
                agent.terminate()
                agent.wait(timeout=60)
            after = subprocess.run(["ovs-vsctl", "list-br"], text=True, capture_output=True, check=True).stdout.splitlines()
            report["cleanup_preserved_bridges"] = before == after
            report["agent_socket_present"] = Path(config["agent_socket"]).exists()
            root_state = Path(report["root_state_dir"])
            if root_state.exists():
                # A single streamed archive avoids thousands of slow DrvFS
                # metadata writes while retaining all native/source journals.
                archive = runtime / ("root_archive_" + report.get("batch_id", 'startup') + '_' + str(os.getpid()) + '.tar.gz')
                with tarfile.open(archive, 'x:gz') as output:
                    output.add(root_state, arcname='root_state', recursive=True)
                report["root_archive_tar"] = str(archive)
            checkpoint()
    return 0 if report["state"] == "completed" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--uid", type=int, default=1000)
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    if args.detach:
        args.runtime.mkdir(parents=True, exist_ok=True)
        pid = os.fork()
        if pid:
            print(json.dumps({"supervisor_pid": pid, "status_file": str(args.runtime / "supervisor.json")}))
            return 0
        os.setsid()
        fd = os.open(args.runtime / "supervisor.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        os.close(fd)
        os.dup2(os.open("/dev/null", os.O_RDONLY), 0)
    return supervise(args)


if __name__ == "__main__":
    raise SystemExit(main())
