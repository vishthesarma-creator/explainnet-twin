"""Read-only stdlib namespace/counter observations. Never reads injector journals."""

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4


def observe(manager, instance_id, source_host, target_host, probe_count, completed_run_ids, since_utc, live_receivers=False):
    from explainnet.network_runtime import command, host_command, utc
    requested = time.monotonic()
    with manager.lock:
        acquired = time.monotonic()
        live = manager._running(instance_id)
        ownership_checked = time.monotonic()
        record = live["record"]
        active_receivers = manager.twins._live_receivers(instance_id) if live_receivers else None
        if source_host not in live["hosts"] or target_host not in live["hosts"] or source_host == target_host:
            raise ValueError("invalid telemetry probe endpoints")
        # _running verified every bridge's actual owner/token in this same lock.
        start = time.monotonic()
        result = {"schema_version": 1, "sample_id": "o" + uuid4().hex, "source": "network_agent",
                  "instance_id": instance_id, "agent_epoch": manager.observation_epoch,
                  "config_version": record["config_version"], "config_hash": record["config_hash"],
                  "forwarding_version": record["forwarding_version"], "selected_paths": record["selected_paths"].copy(),
                  "capabilities": {}, "links": {}, "completed_runs": [], "active_flows": [], "errors": []}
        if active_receivers is not None:
            result['active_receiver_runs'] = active_receivers
        probe_start = time.monotonic()
        probe_utc = utc()
        try:
            native = host_command(live["hosts"][source_host], ["ping", "-n", "-c", str(probe_count),
                "-i", "0.1", "-s", "32", "-W", "0.3", record["hosts"][target_host]["ip"]],
                timeout=2, check=False)
            summary = re.search(r"(\d+) packets transmitted, (\d+) received", native["stdout"])
            values = [float(v) for v in re.findall(r"time[=<]([\d.]+) ms", native["stdout"])]
            result["probe"] = {"source_host": source_host, "target_host": target_host,
                "start_monotonic_s": probe_start, "end_monotonic_s": time.monotonic(), "start_utc": probe_utc,
                "transmitted": int(summary[1]) if summary else None, "received": int(summary[2]) if summary else None,
                "rtt_values_ms": values, "valid": summary is not None,
                "reason": None if summary else "probe timeout or unparseable summary", "native": native}
            result["capabilities"]["ping"] = {"available": True}
        except (RuntimeError, OSError, TimeoutError) as exc:
            result["probe"] = {"valid": False, "reason": str(exc), "transmitted": None,
                "received": None, "rtt_values_ms": [], "source_host": source_host, "target_host": target_host}
            result["capabilities"]["ping"] = {"available": False, "reason": str(exc)}
        root_links = {i["ifname"]: i for i in json.loads(command("ip", "-j", "-s", "link", "show"))}
        interface_monotonic = time.monotonic()
        ovs = {}
        for switch, node in live["switches"].items():
            try:
                raw = command("ovs-ofctl", "-O", "OpenFlow13", "dump-ports", node.name)
                for block in re.split(r"\n\s*port\s+", raw)[1:]:
                    number = re.match(r"(\d+):", block)
                    tx = re.search(r"tx pkts=(\d+), bytes=(\d+)", block)
                    if number and tx:
                        ovs[(switch, int(number[1]))] = {"tx_packets": int(tx[1]), "tx_bytes": int(tx[2])}
                result["capabilities"]["ovs_ports"] = {"available": True}
            except (RuntimeError, OSError) as exc:
                result["capabilities"]["ovs_ports"] = {"available": False, "reason": str(exc)}
        configuration = []
        for link in record["definition"]["links"]:
            for a, b, prefix in ((link["source"], link["target"], "forward"),
                                 (link["target"], link["source"], "reverse")):
                port = next(p for p in record["ports"] if p["switch"] == a and p["neighbor"] == b)
                dev = port["interface"]
                actual = root_links.get(dev)
                owned = next(i for i in record["root_interfaces"] if i["name"] == dev)
                item = {"interface": dev, "capacity_bps": link[f"{prefix}_bps"], "identity": None,
                        "monotonic_s": interface_monotonic, "counters": None,
                        "ovs": ovs.get((a, port["ofport"])), "queues": {}, "classes": {}}
                if item["ovs"] is None:
                    item["ovs_reason"] = "OVS counters unavailable or unsupported for this port"
                if actual and actual["ifindex"] == owned["ifindex"]:
                    item["identity"] = f"{manager.observation_epoch}:{actual['ifindex']}"
                    stats = actual.get("stats64", actual.get("stats"))
                    item["counters"] = stats["tx"] if stats else None
                else:
                    item["reason"] = "interface missing or ownership index changed"
                try:
                    classes = json.loads(command("tc", "-j", "-s", "class", "show", "dev", dev))
                    queues = json.loads(command("tc", "-j", "-s", "qdisc", "show", "dev", dev))
                    for kind, entries in (("classes", classes), ("queues", queues)):
                        for entry in entries:
                            stats = entry.get("stats", entry)
                            item[kind][entry["handle"]] = {key: stats.get(key) for key in
                                ("bytes", "packets", "drops", "backlog", "qlen", "overlimits")}
                    # Only a digest crosses the observation boundary; injector settings are not feature values.
                    configuration.append({"direction": f"{a}->{b}", "classes": [{key: c.get(key) for key in
                        ("handle", "rate", "ceil")} for c in classes], "queues": [{"kind": q["kind"],
                        "handle": q["handle"], "options": {k: v for k, v in q.get("options", {}).items()
                        if k not in {"seed", "direct_packets_stat"}}} for q in queues]})
                    result["capabilities"]["linux_tc"] = {"available": True}
                except (RuntimeError, OSError, ValueError) as exc:
                    item["tc_reason"] = str(exc)
                    result["capabilities"]["linux_tc"] = {"available": False, "reason": str(exc)}
                result["links"][f"{a}->{b}"] = item
        result["observed_config_hash"] = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
        for session in manager.sessions.values():
            if session["instance_id"] == instance_id:
                for profile in session["run"]["profiles"]:
                    p = profile["parameters"]
                    result["active_flows"].append({"traffic_run_id": session["run"]["run_id"],
                        **{k: p[k] for k in ("profile_id", "source_host", "target_host", "protocol", "offered_bps")}})
        for run_id in record["runs"][-256:]:
            if run_id in completed_run_ids:
                continue
            run = manager.traffic_status(instance_id, run_id)
            if run.get("ended_utc", run["created_utc"]) < since_utc or run["state"] == "running":
                continue
            result["completed_runs"].append({"run_id": run_id, "state": run["state"], "created_utc": run["created_utc"],
                "forwarding_version": run["forwarding_version"], "profiles": [{"parameters": p["parameters"],
                "server_json": p.get("server_json"), "receiver_clock_anchor": p.get("client_launch_clock"), "server_exit_code": p.get("server_exit_code"),
                "server_stderr": p.get("server_stderr")} for p in run["profiles"]]})
            if len(result["completed_runs"]) == 4:
                break
        result["capabilities"]["receiver_intervals"] = {"available": True,
            "reason": "native receiver intervals become available only after traffic-run finalization"}
        try:
            cpu = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            memory = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
            result["resources"] = {"cpu_total_ticks": sum(cpu), "cpu_idle_ticks": cpu[3] + cpu[4],
                "memory_used_fraction": 1 - memory["MemAvailable"] / memory["MemTotal"]}
            result["capabilities"]["host_resources"] = {"available": True}
        except (OSError, KeyError, ValueError) as exc:
            result["resources"] = {}
            result["capabilities"]["host_resources"] = {"available": False, "reason": str(exc)}
        result.update(at_utc=utc(), monotonic_s=time.monotonic(), collection_started_monotonic_s=start,
                      lock_wait_ms=(acquired-requested)*1000, ownership_check_ms=(ownership_checked-acquired)*1000,
                      total_observation_ms=(time.monotonic()-requested)*1000,
                      collection_duration_ms=(time.monotonic() - start) * 1000)
        result["units"] = {"bytes": "bytes", "packets": "packets", "rtt": "ms", "capacity": "bps",
                           "monotonic": "s", "memory_used": "fraction"}
        return result
