"""Fault extension of NetworkManager's Linux HTB hierarchy; no second owner."""

import json
import re
import time

from explainnet.scenario_spec import loss_percent, recipe
from explainnet.topology.spec import host_routes


class ScenarioEngine:
    @staticmethod
    def configuration_text(raw):
        # HTB reports this monotonically changing packet counter in `qdisc show`.
        # It is evidence, not installed configuration; retain the raw readback.
        return re.sub(r'\bdirect_packets_stat \d+', 'direct_packets_stat <counter>', raw)

    def __init__(self, manager):
        self.manager = manager
        self.deadlines = {}

    def _save_journal(self, live):
        journal = live["record"]["scenario"]
        self.manager._save(live["record"])
        for run_id in journal["owned_runs"]:
            path = self.manager.state_dir / "runs" / run_id / "laboratory_ground_truth.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(journal, indent=2) + "\n")
            temp.replace(path)

    def _port(self, live, source, target):
        record = live["record"]
        port = next(p for p in record["ports"] if p["switch"] == source and p["neighbor"] == target)
        from explainnet.network_runtime import command
        actual = json.loads(command("ip", "-j", "link", "show", "dev", port["interface"]))[0]
        owned = next(i for i in record["root_interfaces"] if i["name"] == port["interface"])
        if actual["ifindex"] != owned["ifindex"] or not self.manager._owned_bridge(record["switches"][source]["name"], record):
            raise ValueError("scenario interface ownership mismatch")
        return port["interface"]

    def tc(self, dev, *args):
        from explainnet.network_runtime import command
        return command("tc", *args[:2], "dev", dev, *args[2:])

    def evidence(self, live):
        result = {}
        for a, b in (("s2", "s3"), ("s3", "s2"), ("s3", "s5")):
            dev = self._port(live, a, b)
            result[f"{a}->{b}"] = {"interface": dev,
                "qdisc_raw": self.tc(dev, "qdisc", "show"),
                "class_raw": self.tc(dev, "class", "show"),
                "class_counters": self._stats(dev, "class"), "qdisc_counters": self._stats(dev, "qdisc"),
                "filters": self.tc(dev, "filter", "show")}
        return result

    @staticmethod
    def _stats(dev, kind):
        from explainnet.network_runtime import command
        return json.loads(command("tc", "-j", "-s", kind, "show", "dev", dev))

    def _base(self, live, a, b):
        link = next(l for l in live["record"]["definition"]["links"] if {l["source"], l["target"]} == {a, b})
        prefix = "forward" if link["source"] == a else "reverse"
        return link[f"{prefix}_bps"], link[f"{prefix}_delay_ms"]

    def _netem(self, dev, delay, loss=0, variation=0, seed=None):
        args = ["qdisc", "replace", "parent", "5:1", "handle", "10:", "netem", "delay", f"{delay}ms"]
        if variation:
            args.append(f"{variation}ms")
        args.extend(["loss", loss_percent(loss), "limit", "1000"])
        if seed is not None:
            args.extend(["seed", str(seed)])
        self.tc(dev, *args)

    def _qos(self, live, ceiling, journal):
        dev = self._port(live, "s3", "s5")
        capacity, delay = self._base(live, "s3", "s5")
        if capacity != 20_000_000:
            raise ValueError("pilot QoS requires configured 20 Mbps capacity")
        journal["qos_modified"] = True
        self.manager._save(live["record"])
        self.tc(dev, "qdisc", "del", "parent", "5:1", "handle", "10:")
        for cls, rate, cap in (("10", min(3_000_000, ceiling), ceiling), ("20", 16_000_000, 20_000_000)):
            self.tc(dev, "class", "add", "parent", "5:1", "classid", f"5:{cls}", "htb",
                    "rate", str(rate), "ceil", str(cap), "burst", "15k", "quantum", "1500")
            self.tc(dev, "qdisc", "add", "parent", f"5:{cls}", "handle", f"{cls}:", "netem",
                    "delay", f"{delay}ms", "limit", "100")
        hosts = live["record"]["hosts"]
        self.tc(dev, "filter", "add", "parent", "5:", "protocol", "ip", "pref", "10", "flower",
                "src_ip", hosts["h1"]["ip"], "dst_ip", hosts["h3"]["ip"], "classid", "5:10")
        self.tc(dev, "filter", "add", "parent", "5:", "protocol", "all", "pref", "100",
                "matchall", "classid", "5:20")

    def start(self, instance_id, scenario):
        from explainnet.network_runtime import utc
        parameters = recipe(scenario)
        m = self.manager
        with m.lock:
            live = m._running(instance_id)
            record = live["record"]
            old = record.get("scenario")
            if old and old["state"] in {"active", "applying", "restore_failed"}:
                if old["state"] == "active" and old["configuration"] == scenario:
                    return self.inspect(instance_id)
                raise ValueError("overlapping scenario rejected; reset first")
            if any(s["instance_id"] == instance_id for s in m.sessions.values()):
                raise ValueError("scenario requires no existing traffic runs")
            routes = host_routes(record["definition"], record["selected_paths"])
            for source, target in (("h1", "h3"), ("h2", "h4"), ("h5", "h6")):
                r = next((r for r in routes if r["source_host"] == source and r["target_host"] == target), None)
                if not r or ("s2", "s3") not in list(zip(r["switches"], r["switches"][1:])):
                    raise ValueError("scenario traffic does not cross s2->s3")
            before = self.evidence(live)
            for direction, v in before.items():
                if ("htb 5:" not in v["qdisc_raw"] or "netem 10:" not in v["qdisc_raw"] or v["filters"]
                        or len(v["class_counters"]) != 1 or len(v["qdisc_counters"]) != 2
                        or "loss" in v["qdisc_raw"]):
                    raise ValueError("unexpected qdisc hierarchy; refusing to overwrite")
                a, b = direction.split("->")
                capacity, delay = self._base(live, a, b)
                cls = v["class_counters"][0]
                netem = next(q for q in v["qdisc_counters"] if q["kind"] == "netem")
                options = netem["options"]
                if (cls["handle"] != "5:1" or cls["rate"] * 8 != capacity or cls["ceil"] * 8 != capacity
                        or options["limit"] != 1000 or options["delay"]["delay"] * 1000 != delay
                        or options["delay"]["jitter"] != 0):
                    raise ValueError("live shaping differs from approved base configuration")
                from explainnet.network_runtime import command
                if command("ovs-vsctl", "get", "Port", v["interface"], "qos") != "[]":
                    raise ValueError("another QoS owner is attached to the scenario port")
            journal = {"state": "applying", "configuration": scenario, "parameters": parameters,
                       "before": before, "selected_paths": dict(record["selected_paths"]),
                       "forwarding_before": m.inspect(instance_id)["forwarding"], "owned_runs": [],
                       "modified_directions": [], "qos_modified": False, "activated_utc": None,
                       "deactivated_utc": None}
            record["scenario"] = journal
            m._save(record)
            try:
                if scenario["traffic_profile"] == "qos_competing":
                    self._qos(live, parameters["critical_ceiling_bps"], journal)
                journal["activated_utc"] = utc()
                journal['activated_monotonic_s'] = time.monotonic()
                profiles = self.profiles(scenario, parameters)
                journal["traffic_configuration"] = profiles
                journal["capacity_bps"] = self._base(live, "s2", "s3")[0]
                journal["qos_capacity_bps"] = self._base(live, "s3", "s5")[0]
                journal["offered_demand_bps"] = sum(p["offered_bps"] for p in profiles)
                if scenario["kind"] == "saturation" and journal["offered_demand_bps"] <= journal["capacity_bps"]:
                    raise ValueError("offered demand does not exceed fixed capacity")
                run = m.traffic_start(instance_id, profiles)
                journal["owned_runs"].append(run["run_id"])
                self._save_journal(live)
                # Establish iperf's TCP control channels before introducing stochastic loss.
                # Native -O excludes this warmup from receiver summaries.
                time.sleep(scenario["warmup_s"])
                if scenario["kind"] in {"loss", "latency"}:
                    directions = [("s2", "s3")] + ([("s3", "s2")] if scenario["bidirectional"] else [])
                    for a, b in directions:
                        journal["modified_directions"].append([a, b])
                        m._save(record)
                        self._netem(self._port(live, a, b), self._base(live, a, b)[1] + parameters["added_delay_ms"],
                                    parameters["loss_fraction"], scenario["variation_ms"],
                                    scenario.get("seed", 20261007) if " seed " in before[f"{a}->{b}"]["qdisc_raw"] else None)
                    parameters["netem_seed"] = scenario.get("seed", 20261007) if " seed " in before["s2->s3"]["qdisc_raw"] else None
                    journal["activated_utc"] = utc()
                    journal['activated_monotonic_s'] = time.monotonic()
                journal["state"] = "active"
                self.deadlines[instance_id] = m.sessions[run["run_id"]]["deadline"]
                self._save_journal(live)
                return self.inspect(instance_id)
            except Exception as exc:
                journal["apply_error"] = str(exc)
                try:
                    self.reset(instance_id)
                except Exception as restore:  # noqa: BLE001 - retain partial restoration failure
                    journal["restore_error"] = str(restore)
                m._save(record)
                raise

    @staticmethod
    def profiles(s, parameters):
        duration = s["measurement_s"]
        qos = s["traffic_profile"] == "qos_competing"
        values = [("critical", "h1", "h3", s.get("critical_bps") or (2_000_000 if qos else 8_000_000)),
                  ("bulk", "h2", "h4", 30_000_000 if qos else 5_000_000)]
        if parameters["background_bps"]:
            values.append(("background", "h5", "h6", parameters["background_bps"]))
        return [{"schema_version": 1, "config_version": "recovery_observation_v1" if s["config_version"] == "recovery_observation_v1" else "scenario_workload_v1", "profile_id": name,
                 "source_host": a, "target_host": b, "protocol": s.get("bulk_protocol", "udp") if name == "bulk" else "udp", "offered_bps": rate,
                 "duration_s": duration, "warmup_s": s["warmup_s"],
                 "packet_size": None if name == "bulk" and s.get("bulk_protocol", "udp") == "tcp" else s.get("packet_size", 1200)}
                for name, a, b, rate in values]

    def inspect(self, instance_id):
        with self.manager.lock:
            live = self.manager._running(instance_id)
            journal = live["record"].get("scenario")
            return {"instance_id": instance_id, "laboratory_journal": journal,
                    "observed_tc": self.evidence(live),
                    "traffic_runs": [self.manager.traffic_status(instance_id, r) for r in journal["owned_runs"]]
                    if journal else []}

    def reset(self, instance_id):
        from explainnet.network_runtime import command, utc
        m = self.manager
        with m.lock:
            live = m._running(instance_id)
            journal = live["record"].get("scenario")
            if not journal or journal["state"] == "stopped":
                return self.inspect(instance_id)
            errors = []
            for run in journal["owned_runs"]:
                try:
                    m.traffic_stop(instance_id, run)
                except Exception as exc:  # noqa: BLE001 - collect per-run restoration errors
                    errors.append(str(exc))
            try:
                if journal["qos_modified"]:
                    dev = self._port(live, "s3", "s5")
                    # Only classes/filter priorities created by this journal; retry tolerates partial restore.
                    for pref in ("10", "100"):
                        command("tc", "filter", "del", "dev", dev, "parent", "5:", "pref", pref, check=False)
                    for cls in ("10", "20"):
                        command("tc", "class", "del", "dev", dev, "classid", f"5:{cls}", check=False)
                    seed = re.search(r"seed (\d+)", journal["before"]["s3->s5"]["qdisc_raw"])
                    self._netem(dev, self._base(live, "s3", "s5")[1], seed=int(seed[1]) if seed else None)
                for a, b in journal["modified_directions"]:
                    seed = re.search(r"seed (\d+)", journal["before"][f"{a}->{b}"]["qdisc_raw"])
                    self._netem(self._port(live, a, b), self._base(live, a, b)[1], seed=int(seed[1]) if seed else None)
                observed = self.evidence(live)
                for direction, original in journal["before"].items():
                    if (self.configuration_text(observed[direction]["qdisc_raw"]) != self.configuration_text(original["qdisc_raw"])
                            or observed[direction]["class_raw"] != original["class_raw"] or observed[direction]["filters"] != original["filters"]):
                        raise RuntimeError(f"restoration mismatch: {direction}")
                journal["connectivity"] = m.probe(instance_id, "h1", "h3")
                if not journal["connectivity"]["passed"]:
                    raise RuntimeError("restored connectivity failed")
            except Exception as exc:  # noqa: BLE001 - persist partial restoration and allow retry
                errors.append(str(exc))
            journal["state"] = "restore_failed" if errors else "stopped"
            journal["restore_errors"] = errors
            journal["deactivated_utc"] = utc() if not errors else None
            journal['deactivated_monotonic_s'] = time.monotonic() if not errors else None
            self.deadlines.pop(instance_id, None)
            self._save_journal(live)
            if errors:
                raise RuntimeError("partial scenario restore: " + "; ".join(errors))
            return self.inspect(instance_id)
