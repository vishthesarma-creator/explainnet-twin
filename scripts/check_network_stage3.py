#!/usr/bin/env python3
"""Bounded real Stage 3 scenario. OS Python/root; API runs as --app-uid.

Only this script's unique instances, agent, temporary storage and sentinel bridge
are cleaned. Real iperf JSON and OpenFlow evidence are preserved in artifacts.
"""

import argparse
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "stage3"


def checked(args, timeout=10, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout, **kwargs)


def save(name, data):
    (EVIDENCE / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")


def pair_counts(inspection, pair):
    route = next(r for r in inspection["routes"] if r["pair_id"] == pair)
    ip = inspection["hosts"][route["source_host"]]["ip"]
    target = inspection["hosts"][route["target_host"]]["ip"]
    counts = {}
    for switch, raw in inspection["forwarding"].items():
        lines = [line for line in raw.splitlines() if f"cookie={route['cookie']}" in line
                 and f"nw_src={ip}" in line and f"nw_dst={target}" in line]
        counts[switch] = sum(int(re.search(r"n_packets=(\d+)", line).group(1)) for line in lines)
    return counts


def pair_rules(inspection, pair):
    route = next(r for r in inspection["routes"] if r["pair_id"] == pair)
    return {s: sorted(line.split("priority=", 1)[1] for line in raw.splitlines()
                      if f"cookie={route['cookie']}" in line)
            for s, raw in inspection["forwarding"].items()}


def receiver_summary(run):
    result = {}
    for item in run["profiles"]:
        assert item["client_exit_code"] == item["server_exit_code"] == 0, item
        raw = item["server_json"]["end"]
        received = raw.get("sum_received", raw.get("sum", {}))
        assert received.get("bytes", 0) > 0, received
        result[item["parameters"]["profile_id"]] = received
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-uid", type=int, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or args.app_uid < 1:
        parser.error("run as root with ordinary application UID")
    app_gid = pwd.getpwuid(args.app_uid).pw_gid
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tag = uuid4().hex[:8]
    main_id, small_id = "pilot_" + tag, "isolation_" + tag
    guard = "guard" + tag
    socket_dir = Path("/run") / ("explainnet-test-" + tag)
    agent_socket = socket_dir / "agent.sock"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        api_port = reserve.getsockname()[1]
    base_url = f"http://127.0.0.1:{api_port}"
    before_bridges = checked(["ovs-vsctl", "list-br"]).stdout.splitlines()
    agent = service = None
    root_state = Path(tempfile.mkdtemp(prefix="explainnet-stage3-agent-"))
    app_temp = tempfile.TemporaryDirectory(prefix="explainnet-stage3-app-")
    app_dir = Path(app_temp.name)
    os.chown(app_dir, args.app_uid, app_gid)
    os.chmod(app_dir, 0o750)
    report = {"schema_version": 1, "checked_utc": datetime.now(UTC).isoformat(), "status": "partial",
              "checks": {}, "errors": [], "evidence_directory": "artifacts/stage3",
              "baseline": {"udp_offered_bps": 2000000, "tcp_offered_bps": 5000000,
                           "duration_s": 4, "primary_bottleneck_bps": 20000000,
                           "alternative_bottleneck_bps": 30000000}}
    report["runtime"] = {"logical_cpus": os.cpu_count(), "linux": "Ubuntu WSL2",
                         "iperf3": checked(["iperf3", "--version"]).stdout.splitlines()[0]}
    report["warnings"] = ["Mininet TCLink logs HTB quantum warnings; traffic and forwarding checks pass"]
    config = app_dir / "local.yaml"
    config.write_text(json.dumps({"schema_version": 1, "data_dir": str(app_dir / "data"),
        "runtime_dir": str(app_dir / "run"), "agent_socket": str(agent_socket), "host": "127.0.0.1", "port": api_port,
        "topology_file": str(ROOT / "config" / "topology.yaml"), "traffic_profiles_file": str(ROOT / "config" / "traffic.yaml")}))
    app_cmd = [str(ROOT / ".venv" / "bin" / "python"), "-m", "explainnet.cli", "--config", str(config)]
    agent_cmd = [sys.executable, "-m", "explainnet.agent_server", "--socket", str(agent_socket),
                 "--state-dir", str(root_state), "--allow-uid", str(args.app_uid)]
    log_agent = (EVIDENCE / "agent.log").open("w")
    log_service = (EVIDENCE / "api.log").open("w")

    def app_cli(*command):
        return checked([*app_cmd, *command], cwd=ROOT, timeout=20,
                       user=args.app_uid, group=app_gid, extra_groups=[])

    def http(path, data=None):
        request = urllib.request.Request(base_url + path, method="POST" if data is not None else "GET",
            data=json.dumps(data).encode() if data is not None else None, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def agent_call(operation, parameters=None):
        request = {"protocol_version": 1, "request_id": uuid4().hex, "operation": operation,
                   "parameters": parameters or {}}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(60)
            client.connect(str(agent_socket))
            client.sendall((json.dumps(request) + "\n").encode())
            data = bytearray()
            while not data.endswith(b"\n"):
                block = client.recv(4096)
                if not block:
                    raise RuntimeError("agent closed connection")
                data.extend(block)
        response = json.loads(data)
        if not response["ok"]:
            raise RuntimeError(response.get("error"))
        return response["data"]

    def await_job(submission, timeout=70):
        job_id = submission["job_id"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = http("/v1/jobs/" + job_id)
            if job["state"] in {"failed", "succeeded", "interrupted", "canceled"}:
                save("job_" + job_id, job)
                assert job["state"] == "succeeded", job
                return job["result"]
            time.sleep(0.1)
        raise TimeoutError("job deadline exceeded")

    def job(path, data):
        started = time.monotonic()
        submission = http(path, data)
        latency = (time.monotonic() - started) * 1000
        report.setdefault("submission_latency_ms", []).append(latency)
        assert latency < 1500, latency
        return await_job(submission)

    def wait_service():
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                if http("/v1/health")["status"] == "healthy":
                    return
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.1)
        raise TimeoutError("service did not become healthy")

    def launch_agent():
        proc = subprocess.Popen(agent_cmd, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                stdout=log_agent, stderr=log_agent)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                agent_call("health")
                return proc
            except (OSError, RuntimeError):
                if proc.poll() is not None:
                    raise RuntimeError("agent exited; see agent.log") from None
                time.sleep(0.1)
        raise TimeoutError("agent did not start")

    def launch_service():
        proc = subprocess.Popen([*app_cmd, "serve"], cwd=ROOT, user=args.app_uid, group=app_gid,
                                extra_groups=[], stdout=log_service, stderr=log_service)
        wait_service()
        return proc

    def wait_run(run_id, instance_id=main_id, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = http(f"/v1/traffic/{instance_id}/{run_id}")
            if run["state"] != "running":
                save("run_" + run_id, run)
                if run["state"] != "succeeded":
                    errors = [p.get("client_stderr", "")[:250] for p in run["profiles"]]
                    raise RuntimeError(f"traffic run {run_id} {run['state']}: {errors}")
                return run
            time.sleep(0.2)
        raise TimeoutError("traffic deadline exceeded")

    def stop_process(proc):
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    try:
        checked(["ovs-vsctl", "add-br", guard])
        checked(["ovs-vsctl", "set", "Bridge", guard, "external_ids:stage3_guard=" + tag])
        app_cli("init")
        agent = launch_agent()
        service = launch_service()
        caps = http("/v1/capabilities")
        save("capabilities", caps)
        submission = json.loads(app_cli("network-start", main_id).stdout)
        started = await_job(submission)
        assert started["state"] == "running" and started["live_verified"]
        initial = http("/v1/networks/" + main_id)
        save("initial", initial)
        assert len(initial["switches"]) == 5 and len(initial["hosts"]) == 6
        assert all(len(p["interface"]) <= 15 for p in initial["ports"])
        assert len({h["namespace"] for h in initial["hosts"].values()}) == 6
        report["checks"]["five_switch_start_and_mapping"] = True
        repeated = job("/v1/networks/start", {"instance_id": main_id})
        assert repeated["token"] == initial["token"]
        probes = job("/v1/networks/probe", {"instance_id": main_id})
        save("all_pairs_probe", probes)
        assert probes["passed"] and len(probes["probes"]) == 30, probes
        report["checks"]["all_pairs_arp_forward_reverse"] = True
        baseline_before = http("/v1/networks/" + main_id)
        run = job("/v1/traffic/start", {"instance_id": main_id, "profile_ids": ["critical", "bulk"]})
        healthy = wait_run(run["run_id"])
        assert healthy["workload_versions"] == ["healthy_v1"] and len(healthy["workload_hash"]) == 64
        summaries = receiver_summary(healthy)
        assert "jitter_ms" in summaries["critical"] and "lost_percent" in summaries["critical"]
        report["healthy_receivers"] = summaries
        report["checks"]["paced_tcp_udp_baseline"] = True
        primary = http("/v1/networks/" + main_id)
        save("primary", primary)
        before_counts, after_counts = pair_counts(baseline_before, "critical"), pair_counts(primary, "critical")
        delta = {s: after_counts[s] - before_counts[s] for s in after_counts}
        assert all(delta[s] > 0 for s in ("s1", "s2", "s3", "s5")) and delta["s4"] == 0, delta
        report["primary_critical_packet_delta"] = delta
        report["checks"]["primary_counter_evidence"] = True
        bulk_run = job("/v1/traffic/start", {"instance_id": main_id, "profile_ids": ["bulk"], "duration_s": 8})
        bulk_rules = pair_rules(primary, "bulk")
        changed = job("/v1/networks/path", {"instance_id": main_id, "pair_id": "critical", "path_name": "alternative"})
        assert changed["selected_paths"] == {"critical": "alternative", "bulk": "primary"}
        alternate_before = http("/v1/networks/" + main_id)
        assert pair_rules(alternate_before, "bulk") == bulk_rules
        probe = job("/v1/networks/probe", {"instance_id": main_id, "source_host": "h1", "target_host": "h3"})
        assert probe["passed"]
        alt_run = await_job(json.loads(app_cli("traffic-start", main_id, "--profiles", "critical", "--duration", "3",
                                            "--rate-bps", "2000000", "--packet-size", "1200").stdout))
        receiver_summary(wait_run(alt_run["run_id"]))
        receiver_summary(wait_run(bulk_run["run_id"]))
        alternative = http("/v1/networks/" + main_id)
        save("alternative", alternative)
        before_counts, after_counts = pair_counts(alternate_before, "critical"), pair_counts(alternative, "critical")
        delta = {s: after_counts[s] - before_counts[s] for s in after_counts}
        assert all(delta[s] > 0 for s in ("s1", "s4", "s5")) and delta["s2"] == delta["s3"] == 0, delta
        assert pair_rules(alternative, "bulk") == bulk_rules
        report["alternative_critical_packet_delta"] = delta
        report["checks"]["alternative_delivery_and_unrelated_bulk"] = True
        cancel = job("/v1/traffic/start", {"instance_id": main_id, "profile_ids": ["background"], "duration_s": 30})
        canceled = job("/v1/traffic/stop", {"instance_id": main_id, "run_id": cancel["run_id"]})
        assert canceled["state"] == "canceled"
        save("canceled_run", canceled)
        report["checks"]["owned_traffic_stop"] = True
        app_cli("stop")
        service.wait(timeout=12)
        assert service.returncode == 0
        service = launch_service()
        after_restart = http("/v1/networks/" + main_id)
        assert after_restart["token"] == initial["token"] and after_restart["live_verified"]
        report["checks"]["api_restart_live_reconciliation"] = True
        small = {"schema_version": 1, "config_version": "isolation_v1", "topology_id": "small", "address_pool": "10.80.0.0/16",
                 "switches": ["s1"], "hosts": [
                     {"host_id": "h1", "switch_id": "s1", "address_offset": 1, "role": "client", "access_bps": 100000000, "access_delay_ms": 0},
                     {"host_id": "h2", "switch_id": "s1", "address_offset": 2, "role": "receiver", "access_bps": 100000000, "access_delay_ms": 0}],
                 "links": [], "pairs": []}
        agent_call("network_start", {"schema_version": 1, "instance_id": small_id, "definition": small})
        small_inspect = agent_call("network_inspect", {"schema_version": 1, "instance_id": small_id})
        save("small_instance", small_inspect)
        assert initial["subnet"] != small_inspect["subnet"]
        assert agent_call("network_probe", {"schema_version": 1, "instance_id": small_id, "source_host": None, "target_host": None})["passed"]
        host = small_inspect["hosts"]["h1"]
        prefix = ["nsenter", "-t", str(host["pid"]), "-n"]
        checked([*prefix, "ip", "route", "add", initial["subnet"], "dev", host["name"] + "-eth0"])
        try:
            cross = subprocess.run([*prefix, "ping", "-c", "1", "-W", "1", initial["hosts"]["h1"]["ip"]],
                                   capture_output=True, text=True, timeout=4, check=False)
            assert cross.returncode != 0
            save("isolation_probe", {"exit_code": cross.returncode, "stdout": cross.stdout, "stderr": cross.stderr})
        finally:
            checked([*prefix, "ip", "route", "del", initial["subnet"]])
        report["checks"]["second_instance_isolated"] = True
        stop = job("/v1/networks/stop", {"instance_id": main_id})
        assert stop["state"] == "stopped"
        assert job("/v1/networks/stop", {"instance_id": main_id})["state"] == "stopped"
        assert agent_call("network_probe", {"schema_version": 1, "instance_id": small_id, "source_host": None, "target_host": None})["passed"]
        restarted = job("/v1/networks/start", {"instance_id": main_id})
        assert restarted["token"] != initial["token"]
        assert job("/v1/networks/probe", {"instance_id": main_id, "source_host": "h1", "target_host": "h3"})["passed"]
        report["checks"]["repeat_stop_start_preserves_other_instance"] = True
        agent.kill()
        agent.wait(timeout=3)
        agent = launch_agent()
        stale = http("/v1/networks/" + main_id)
        save("stale_after_agent_restart", stale)
        assert stale["state"] == "failed" and not stale["live_verified"]
        report["checks"]["agent_restart_does_not_claim_stale_live"] = True
        assert job("/v1/networks/cleanup", {"instance_id": main_id})["state"] == "stopped"
        assert job("/v1/networks/cleanup", {"instance_id": small_id})["state"] == "stopped"
        final_inventory = http("/v1/agent/inventory")
        save("final_inventory", final_inventory)
        assert not final_inventory["inventory"]["bridges"]
        current_bridges = checked(["ovs-vsctl", "list-br"]).stdout.splitlines()
        assert set(current_bridges) == set(before_bridges) | {guard}, current_bridges
        interfaces = json.loads(checked(["ip", "-j", "link", "show"]).stdout)
        all_names = {p["interface"] for inspection in (initial, small_inspect) for p in inspection["ports"]}
        assert not any(i["ifname"] in all_names for i in interfaces)
        report["checks"]["specific_cleanup_preserves_unrelated_resources"] = True
        app_cli("stop")
        service.wait(timeout=12)
        assert service.returncode == 0
        service = None
        stop_process(agent)
        assert agent.returncode == 0
        agent = None
        assert not agent_socket.exists()
        report["checks"]["clean_shutdown"] = True
        report["status"] = "complete"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        stop_process(service)
        stop_process(agent)
        cleanup_ok = True
        try:
            sys.path.insert(0, str(ROOT / "src"))
            from explainnet.network_runtime import NetworkManager
            cleanup = NetworkManager(root_state)
            try:
                cleanup.cleanup(main_id)
                cleanup.cleanup(small_id)
            finally:
                cleanup.shutdown()
        except Exception as exc:  # noqa: BLE001 - retain ownership evidence on cleanup failure
            cleanup_ok = False
            report["status"] = "partial"
            report["errors"].append(f"specific cleanup failed: {exc}")
        if root_state.exists():
            shutil.copytree(root_state, EVIDENCE / "ownership_and_raw", dirs_exist_ok=True)
        try:
            owner = checked(["ovs-vsctl", "get", "Bridge", guard, "external_ids:stage3_guard"]).stdout.strip().strip('"')
            if owner == tag:
                checked(["ovs-vsctl", "--if-exists", "del-br", guard])
        except subprocess.CalledProcessError:
            pass
        log_agent.close()
        log_service.close()
        if not cleanup_ok:
            report["retained_ownership_directory"] = str(root_state)
        (ROOT / "artifacts" / "network_smoke_report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        if not agent_socket.exists():
            socket_dir.rmdir()
        app_temp.cleanup()
        if cleanup_ok:
            shutil.rmtree(root_state)


if __name__ == "__main__":
    main()
