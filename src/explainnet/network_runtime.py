"""Persistent privileged owner of isolated Mininet instances and traffic.

Uses OS Python/Mininet. The only tc hierarchy owner is this component (TCLink).
"""

import fcntl
import ipaddress
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from explainnet.topology.spec import (
    definition_hash,
    host_routes,
    identifier,
    validate_definition,
    validate_profile,
)


def utc():
    return datetime.now(UTC).isoformat()


def command(*args, timeout=5, check=True):
    result = subprocess.run(list(args), text=True, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()
        return {"pid": pid, "start_ticks": stat[19], "namespace": os.readlink(f"/proc/{pid}/ns/net")}
    except (FileNotFoundError, ProcessLookupError):
        return None


def stop_owned_process(identity):
    def same_process():
        current = process_identity(identity["pid"])
        return current is not None and current["start_ticks"] == identity["start_ticks"]

    if identity and same_process():
        try:
            os.kill(identity["pid"], signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1
        while same_process() and time.monotonic() < deadline:
            time.sleep(0.02)
        if same_process():
            try:
                os.kill(identity["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass


def host_command(host, args, timeout=4, check=True):
    proc = host.popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise TimeoutError(f"host command timed out: {args[0]}") from None
    result = {"exit_code": proc.returncode, "stdout": out.decode(errors="replace"),
              "stderr": err.decode(errors="replace")}
    if check and proc.returncode:
        raise RuntimeError(f"host {host.name}: {args[0]} exited {proc.returncode}: {result['stderr']}")
    return result


class NetworkManager:
    def __init__(self, state_dir: Path, stream_receivers=False):
        self.stream_receivers = stream_receivers
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if state_dir.is_symlink() or state_dir.stat().st_uid != os.geteuid():
            raise ValueError("ownership directory must belong to the agent and not be a symlink")
        os.chmod(state_dir, 0o700)
        self._lockfile = (state_dir / "agent.lock").open("a+")
        fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock = threading.RLock()
        self.instances = {}
        self.records = {}
        self.sessions = {}
        self.observation_epoch = uuid4().hex
        from explainnet.scenario_runtime import ScenarioEngine
        self.scenarios = ScenarioEngine(self)
        from explainnet.twin_runtime import TwinEngine
        self.twins = TwinEngine(self)
        self.allow_lab_test_hooks = False
        from explainnet.lab_runtime import LabActionEngine
        self.lab_actions = LabActionEngine(self)
        self._stop = threading.Event()
        for path in state_dir.glob("instance_*.json"):
            record = json.loads(path.read_text())
            identifier(record["instance_id"])
            if record["state"] != "stopped":
                record["state"] = "failed"
                record["error"] = "agent ownership lost; explicit cleanup required before restart"
            self.records[record["instance_id"]] = record
            self._save(record)
        self.monitor = threading.Thread(target=self._monitor, name="traffic-deadlines", daemon=True)
        self.monitor.start()

    def _save(self, record):
        record["updated_utc"] = utc()
        path = self.state_dir / f"instance_{record['instance_id']}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, indent=2) + "\n")
        temp.replace(path)

    def _owned_bridge(self, name, record):
        return self._verified_bridges(record, [name])

    def _verified_bridges(self, record, names=None):
        """One coherent OVSDB transaction; no cached authorization or lost checks."""
        if not record.get('token') or not record.get('instance_id'):
            return False
        native = json.loads(command('ovs-vsctl', '--format=json', '--columns=name,external_ids', 'list', 'Bridge'))
        columns = native['headings']
        rows = {}
        for data in native['data']:
            values = dict(zip(columns, data, strict=True))
            ids = values['external_ids']
            if not isinstance(ids, list) or ids[0] != 'map':
                raise ValueError('invalid OVS ownership metadata')
            rows[values['name']] = dict(ids[1])
        return all(rows.get(name, {}).get('explainnet_instance') == record['instance_id']
            and rows[name].get('explainnet_token') == record['token'] for name in names or record['bridges'])

    def _summary(self, record):
        return {k: record.get(k) for k in ("instance_id", "state", "config_version", "config_hash", "token",
                                          "subnet", "selected_paths", "forwarding_version", "updated_utc", "error", "runs", "construction_elapsed_ms")} | {'role': record.get('role', 'original')}

    def inventory(self):
        with self.lock:
            bridges = command("ovs-vsctl", "list-br").splitlines()
            return {"instances": [self.inspect(r["instance_id"], detailed=False) for r in self.records.values()],
                    "bridges": [b for r in self.records.values() for b in r.get("bridges", [])
                                if b in bridges and self._owned_bridge(b, r)]}

    def start(self, instance_id, definition):
        construction_started = time.monotonic()
        identifier(instance_id)
        validate_definition(definition)
        config_hash = definition_hash(definition)
        with self.lock:
            if instance_id in self.instances:
                if self.records[instance_id]["config_hash"] != config_hash:
                    raise ValueError("instance is running with a different configuration")
                return self.inspect(instance_id, detailed=False)
            if instance_id in self.records and self.records[instance_id]["state"] != "stopped":
                raise ValueError("stale instance requires specific cleanup before restart")
            if len(self.instances) >= 4:
                raise ValueError("maximum four owned instances")
            used = {r["subnet"] for r in self.records.values() if r["state"] != "stopped"}
            pool = ipaddress.ip_network(definition["address_pool"])
            subnet = next((str(s) for s in list(pool.subnets(new_prefix=24))[1:255] if str(s) not in used), None)
            if subnet is None:
                raise ValueError("address pool exhausted")
            token = uuid4().hex[:6]
            from explainnet.topology.spec import runtime_switch_name
            names = {s: runtime_switch_name(token, s) for s in definition["switches"]}
            host_names = {h["host_id"]: f"en{token}{h['host_id']}" for h in definition["hosts"]}
            existing = set(command("ovs-vsctl", "list-br").splitlines())
            root_links = json.loads(command("ip", "-j", "link", "show"))
            if existing.intersection(names.values()) or any(i["ifname"].startswith(f"en{token}") for i in root_links):
                raise ValueError("generated bridge name collision")
            record = {"schema_version": 1, "instance_id": instance_id, "state": "starting", "token": token,
                      "subnet": subnet, "config_hash": config_hash, "config_version": definition["config_version"],
                      "definition": definition, "bridges": list(names.values()), "host_processes": [],
                      "root_interfaces": [], "traffic_processes": [], "runs": [], "created_utc": utc(),
                      "selected_paths": {p["pair_id"]: p["default_path"] for p in definition["pairs"]},
                      "forwarding_version": 1}
            self.records[instance_id] = record
            self._save(record)
            from mininet.link import TCLink
            from mininet.net import Mininet
            from mininet.node import OVSSwitch

            manager = self
            class OwnedSwitch(OVSSwitch):
                def start(self, controllers):
                    super().start(controllers)
                    command("ovs-vsctl", "set", "Bridge", self.name,
                            f"external_ids:explainnet_instance={instance_id}",
                            f"external_ids:explainnet_token={token}", f"external_ids:config_hash={config_hash}")
                    manager._save(record)

            net = Mininet(controller=None, switch=OwnedSwitch, link=TCLink, build=False, autoSetMacs=False)
            live = {"net": net, "hosts": {}, "switches": {}, "ports": {}, "record": record}
            self.instances[instance_id] = live
            try:
                for index, switch_id in enumerate(definition["switches"], start=1):
                    live["switches"][switch_id] = net.addSwitch(names[switch_id], failMode="secure",
                        protocols="OpenFlow13", dpid=f"e17e{token}{index:06x}")
                address_net = ipaddress.ip_network(subnet)
                host_metadata = {}
                for host in definition["hosts"]:
                    alias, offset = host["host_id"], host["address_offset"]
                    ip = str(address_net.network_address + offset)
                    mac = f"02:{token[:2]}:{token[2:4]}:{token[4:]}:00:{offset:02x}"
                    node = net.addHost(host_names[alias], ip=f"{ip}/24", mac=mac)
                    live["hosts"][alias] = node
                    record["host_processes"].append(process_identity(node.pid))
                    host_metadata[alias] = {"ip": ip, "mac": mac, "name": node.name, "pid": node.pid,
                                            "switch_id": host["switch_id"], "namespace": process_identity(node.pid)["namespace"]}
                    self._save(record)
                    switch = live["switches"][host["switch_id"]]
                    params = {"bw": host["access_bps"] / 1000000, "delay": f"{host['access_delay_ms']}ms"}
                    link = net.addLink(node, switch, params1=params, params2=params)
                    live["ports"][(host["switch_id"], alias)] = switch.ports[link.intf2]
                    self._track_interface(record, link.intf2.name)
                for link_spec in definition["links"]:
                    source, target = link_spec["source"], link_spec["target"]
                    a, b = live["switches"][source], live["switches"][target]
                    link = net.addLink(a, b,
                        params1={"bw": link_spec["forward_bps"] / 1000000, "delay": f"{link_spec['forward_delay_ms']}ms"},
                        params2={"bw": link_spec["reverse_bps"] / 1000000, "delay": f"{link_spec['reverse_delay_ms']}ms"})
                    live["ports"][(source, target)] = a.ports[link.intf1]
                    live["ports"][(target, source)] = b.ports[link.intf2]
                    self._track_interface(record, link.intf1.name)
                    self._track_interface(record, link.intf2.name)
                record["hosts"] = host_metadata
                record["switches"] = {s: {"name": node.name, "dpid": node.dpid} for s, node in live["switches"].items()}
                record["ports"] = [{"switch": s, "neighbor": n, "ofport": p,
                                    "interface": f"{names[s]}-eth{p}"} for (s, n), p in live["ports"].items()]
                self._save(record)
                net.build()
                net.start()
                for alias, host in live["hosts"].items():
                    for other_alias, metadata in host_metadata.items():
                        if alias != other_alias:
                            host_command(host, ["ip", "neigh", "replace", metadata["ip"], "lladdr", metadata["mac"],
                                                "nud", "permanent", "dev", f"{host.name}-eth0"])
                self._install_routes(live, host_routes(definition, record["selected_paths"]))
                record["state"] = "running"
                record['construction_elapsed_ms'] = (time.monotonic()-construction_started)*1000
                record.pop("error", None)
                self._save(record)
                return self.inspect(instance_id, detailed=False)
            except Exception as exc:
                record["state"] = "failed"
                record['construction_elapsed_ms'] = (time.monotonic()-construction_started)*1000
                record["error"] = str(exc)
                try:
                    net.stop()
                finally:
                    self.instances.pop(instance_id, None)
                    self._save(record)
                raise

    def _track_interface(self, record, name):
        details = json.loads(command("ip", "-j", "link", "show", "dev", name))[0]
        record["root_interfaces"].append({"name": name, "ifindex": details["ifindex"]})
        self._save(record)

    def _cookie(self, record, index):
        return f"0xe17e{record['token']}{index:06x}"

    def _install_routes(self, live, routes, switch_callback=None):
        record = live["record"]
        rules = {s: [] for s in live["switches"]}
        for route in routes:
            a, b = route["source_host"], route["target_host"]
            for source, target, path in ((a, b, route["switches"]), (b, a, list(reversed(route["switches"])))):
                source_ip, target_ip = record["hosts"][source]["ip"], record["hosts"][target]["ip"]
                for i, switch in enumerate(path):
                    previous = source if i == 0 else path[i - 1]
                    next_node = target if i == len(path) - 1 else path[i + 1]
                    incoming = live["ports"][(switch, previous)]
                    outgoing = live["ports"][(switch, next_node)]
                    prefix = f"cookie={self._cookie(record, route['cookie_index'])},priority=200,in_port={incoming}"
                    rules[switch].extend([
                        f"{prefix},ip,nw_src={source_ip},nw_dst={target_ip},actions=output:{outgoing}",
                        f"{prefix},arp,arp_spa={source_ip},arp_tpa={target_ip},actions=output:{outgoing}",
                    ])
        for switch, entries in rules.items():
            if not entries:
                continue
            with tempfile.NamedTemporaryFile(mode="w", dir=self.state_dir, delete=False) as output:
                output.write("\n".join(entries) + "\n")
                path = Path(output.name)
            try:
                command("ovs-ofctl", "-O", "OpenFlow13", "--bundle", "add-flows", live["switches"][switch].name, str(path))
                if switch_callback:
                    switch_callback(switch)
            finally:
                path.unlink()

    def inspect(self, instance_id, detailed=True):
        identifier(instance_id)
        if not self.lock.acquire(blocking=False):
            record = self.records.get(instance_id)
            if record and record["state"] in {"starting", "stopping"}:
                return self._summary(record) | {"live_verified": False}
        else:
            self.lock.release()
        with self.lock:
            record = self.records.get(instance_id)
            if record is None:
                return {"instance_id": instance_id, "state": "stopped", "live_verified": True}
            live = self.instances.get(instance_id)
            verified = live is not None and self._verified_bridges(record)
            if record["state"] == "running" and not verified:
                record = record | {'state': 'failed', 'error': 'live resources no longer match ownership'}
            result = self._summary(record) | {"live_verified": verified if record["state"] != "stopped" else True}
            if detailed:
                result |= {"hosts": record.get("hosts", {}), "switches": record.get("switches", {}),
                           "definition": record.get('definition'),
                           "ports": record.get("ports", []), "traffic_runs": record.get("runs", []),
                           "tc_owner": "NetworkManager/TCLink",
                           "reserved_egress": {"qos": "s3->s5", "impairment": "s2->s3"}}
                result["routes"] = ([{**r, "cookie": self._cookie(record, r["cookie_index"])}
                                     for r in host_routes(record["definition"], record["selected_paths"])]
                                    if record.get("definition") else [])
                if verified:
                    result["forwarding"] = {s: command("ovs-ofctl", "-O", "OpenFlow13", "dump-flows", node.name)
                                            for s, node in live["switches"].items()}
                    result["port_counters"] = {s: command("ovs-ofctl", "-O", "OpenFlow13", "dump-ports", node.name)
                                               for s, node in live["switches"].items()}
            return result

    def select_path(self, instance_id, pair_id, path_name, _recovery=False, _switch_callback=None):
        with self.lock:
            live = self._running(instance_id)
            record = live["record"]
            if not _recovery:
                self.lab_actions.guard(instance_id)
            if not _recovery and record.get("scenario", {}).get("state") in {"active", "applying", "restore_failed"}:
                raise ValueError("reset laboratory scenario before changing forwarding")
            pair = next((p for p in record["definition"]["pairs"] if p["pair_id"] == pair_id), None)
            if pair is None or path_name not in pair["paths"]:
                raise ValueError("pair or path is not configured")
            if record["selected_paths"][pair_id] == path_name:
                return self.inspect(instance_id, detailed=False)
            previous = dict(record["selected_paths"])
            record["selected_paths"][pair_id] = path_name
            route = next(r for r in host_routes(record["definition"], record["selected_paths"]) if r["pair_id"] == pair_id)
            try:
                for node in live["switches"].values():
                    command("ovs-ofctl", "-O", "OpenFlow13", "--bundle", "del-flows", node.name,
                            f"cookie={self._cookie(record, route['cookie_index'])}/-1")
                self._install_routes(live, [route], _switch_callback)
            except Exception:
                record["selected_paths"] = previous
                for node in live["switches"].values():
                    command("ovs-ofctl", "-O", "OpenFlow13", "--bundle", "del-flows", node.name,
                            f"cookie={self._cookie(record, route['cookie_index'])}/-1")
                old = next(r for r in host_routes(record["definition"], previous) if r["pair_id"] == pair_id)
                self._install_routes(live, [old])
                raise
            record["forwarding_version"] += 1
            self._save(record)
            return self.inspect(instance_id, detailed=False)

    def _running(self, instance_id):
        identifier(instance_id)
        if instance_id not in self.instances or self.records[instance_id]["state"] != "running":
            raise ValueError("network is not running under this agent")
        record = self.records[instance_id]
        if not record.get('bridges') or not self._verified_bridges(record):
            raise ValueError('live resources no longer match ownership')
        return self.instances[instance_id]

    def probe(self, instance_id, source_host=None, target_host=None):
        with self.lock:
            live = self._running(instance_id)
            hosts = live["hosts"]
            if (source_host is None) != (target_host is None):
                raise ValueError("provide both probe endpoints")
            if source_host is not None and (source_host not in hosts or target_host not in hosts or source_host == target_host):
                raise ValueError("invalid probe endpoints")
            pairs = [(source_host, target_host)] if source_host else [(a, b) for a in sorted(hosts) for b in sorted(hosts) if a != b]
            results = []
            deadline = time.monotonic() + 30
            for a, b in pairs:
                if time.monotonic() >= deadline:
                    break
                host = hosts[a]
                target_ip = live["record"]["hosts"][b]["ip"]
                host_command(host, ["ip", "neigh", "del", target_ip, "dev", f"{host.name}-eth0"], check=False)
                measured = host_command(host, ["ping", "-n", "-c", "1", "-W", "1", "-w", "2", target_ip], timeout=3, check=False)
                results.append({"source_host": a, "target_host": b, **measured})
            return {"instance_id": instance_id, "at_utc": utc(),
                    "passed": len(results) == len(pairs) and all(r["exit_code"] == 0 for r in results),
                    "expected_probes": len(pairs), "completed_probes": len(results), "probes": results}

    def traffic_start(self, instance_id, profiles):
        with self.lock:
            if self.stream_receivers:
                profiles = [p | {'stream_receiver': p.get('stream_receiver', True)} for p in profiles]
            live = self._running(instance_id)
            if live["record"].get("scenario", {}).get("state") in {"active", "restore_failed"}:
                raise ValueError("scenario owns the controlled workload; reset before extra traffic")
            if not isinstance(profiles, list) or not 1 <= len(profiles) <= 3:
                raise ValueError("expected 1..3 traffic profiles")
            for profile in profiles:
                validate_profile(profile, live["record"]["definition"])
            if len({p["profile_id"] for p in profiles}) != len(profiles):
                raise ValueError("duplicate traffic profile IDs")
            if sum(s["instance_id"] == instance_id for s in self.sessions.values()) >= 4:
                raise ValueError("maximum four active traffic runs per instance")
            run_id = "r" + uuid4().hex
            directory = self.state_dir / "runs" / run_id
            directory.mkdir(parents=True)
            run = {"schema_version": 1, "run_id": run_id, "instance_id": instance_id, "state": "running",
                   "created_utc": utc(), "config_hash": live["record"]["config_hash"],
                   "config_version": live["record"]["config_version"], "forwarding_version": live["record"]["forwarding_version"],
                   "workload_versions": sorted({p["config_version"] for p in profiles}),
                   "workload_hash": definition_hash(profiles),
                   "selected_paths": dict(live["record"]["selected_paths"]), "profiles": [], "agent_owner": os.getpid()}
            session = {"instance_id": instance_id, "run": run, "processes": [], "files": [],
                       "deadline": time.monotonic() + max(p["duration_s"] + p.get("warmup_s", 0) for p in profiles) + 8,
                       "started": time.monotonic(), "directory": directory}
            self.sessions[run_id] = session
            try:
                for profile in profiles:
                    port = live.setdefault("next_server_port", 5201)
                    live["next_server_port"] = port + 1
                    if port > 65000:
                        raise ValueError("server port allocation exhausted")
                    source, target = profile["source_host"], profile["target_host"]
                    target_ip = live["record"]["hosts"][target]["ip"]
                    server_cmd = ["iperf3", "-s", "-1", "-J", "-p", str(port), "--idle-timeout", str(profile["duration_s"] + profile.get("warmup_s", 0) + 5)]
                    if profile.get('stream_receiver'):
                        server_cmd.extend(['--json-stream', '--forceflush'])
                    client_cmd = ["iperf3", "-c", target_ip, "-p", str(port), "-J", "--get-server-output",
                                  "-b", str(profile["offered_bps"]), "-t", str(profile["duration_s"]),
                                  "--connect-timeout", "2000"]
                    if profile.get("warmup_s", 0):
                        client_cmd.extend(["-O", str(profile["warmup_s"])])
                    if profile["protocol"] == "udp":
                        client_cmd.append("-u")
                        if profile["packet_size"] is not None:
                            client_cmd.extend(["-l", str(profile["packet_size"])])
                    item = {"parameters": profile, "server_port": port,
                            "source": live["record"]["hosts"][source], "target": live["record"]["hosts"][target],
                            "server_command": server_cmd, "client_command": client_cmd}
                    run["profiles"].append(item)
                    for side, node, args in (("server", live["hosts"][target], server_cmd),
                                             ("client", live["hosts"][source], client_cmd)):
                        path = directory / f"{profile['profile_id']}_{side}.json"
                        stderr_path = path.with_suffix(".stderr")
                        stdout, stderr = path.open("wb"), stderr_path.open("wb")
                        session["files"].extend([stdout, stderr])
                        launch_clock = {"utc_epoch_s": time.time(), "monotonic_s": time.monotonic()}
                        proc = node.popen(args, stdout=stdout, stderr=stderr)
                        item[side + "_launch_clock"] = launch_clock
                        session["processes"].append({"proc": proc, "item": item, "side": side,
                                                     "path": path, "stderr_path": stderr_path})
                        identity = process_identity(proc.pid)
                        live["record"]["traffic_processes"].append(identity)
                        self._save(live["record"])
                        if side == "server":
                            time.sleep(0.15)
                live["record"]["runs"].append(run_id)
                self._save(live["record"])
                self._write_run(session)
                return run
            except Exception:
                self._finish_run(run_id, "failed")
                raise

    def _write_run(self, session):
        (session["directory"] / "result.json").write_text(json.dumps(session["run"], indent=2) + "\n")

    def _finish_run(self, run_id, requested_state=None):
        session = self.sessions[run_id]
        for item in session["processes"]:
            proc = item["proc"]
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        for output in session["files"]:
            output.close()
        ok = True
        for proc_item in session["processes"]:
            data = proc_item["item"]
            side = proc_item["side"]
            data[side + "_exit_code"] = proc_item["proc"].returncode
            data[side + "_stderr"] = proc_item["stderr_path"].read_text()
            try:
                from explainnet.receiver_stream import native_receiver
                data[side + "_json"] = native_receiver(proc_item["path"].read_text())
            except (ValueError, FileNotFoundError):
                data[side + "_json"] = None
            native = data[side + "_json"]
            ok = ok and proc_item["proc"].returncode == 0 and native is not None and not native.get("error") and bool(native.get("end"))
        run = session["run"]
        run["state"] = requested_state or ("succeeded" if ok else "failed")
        run["ended_utc"] = utc()
        run["elapsed_ms"] = (time.monotonic() - session["started"]) * 1000
        self._write_run(session)
        record = self.records[session["instance_id"]]
        finished_pids = {p["proc"].pid for p in session["processes"]}
        record["traffic_processes"] = [p for p in record["traffic_processes"] if p and p["pid"] not in finished_pids]
        self._save(record)
        del self.sessions[run_id]
        return run

    def _monitor(self):
        while not self._stop.wait(0.2):
            with self.lock:
                for instance_id, deadline in list(self.scenarios.deadlines.items()):
                    if time.monotonic() >= deadline:
                        try:
                            self.scenarios.reset(instance_id)
                        except Exception as exc:  # noqa: BLE001 - persist monitor restoration failure
                            self.records[instance_id]["scenario"]["restore_error"] = str(exc)
                            self._save(self.records[instance_id])
                for run_id, session in list(self.sessions.items()):
                    if time.monotonic() >= session["deadline"]:
                        self._finish_run(run_id, "failed")
                    elif all(item["proc"].poll() is not None for item in session["processes"]):
                        self._finish_run(run_id)

    def traffic_status(self, instance_id, run_id):
        identifier(instance_id)
        identifier(run_id)
        with self.lock:
            path = self.state_dir / "runs" / run_id / "result.json"
            if not path.exists():
                raise ValueError("traffic run does not exist")
            run = json.loads(path.read_text())
            if run["instance_id"] != instance_id:
                raise ValueError("traffic run belongs to another instance")
            if run_id not in self.sessions and run["state"] == "running":
                run["state"] = "interrupted"
                run["error"] = "agent restarted; traffic was not replayed"
            return run

    def traffic_stop(self, instance_id, run_id):
        with self.lock:
            self.traffic_status(instance_id, run_id)
            return self._finish_run(run_id, "canceled") if run_id in self.sessions else self.traffic_status(instance_id, run_id)

    def stop(self, instance_id):
        identifier(instance_id)
        with self.lock:
            if instance_id not in self.instances:
                return self.cleanup(instance_id)
            record = self.records[instance_id]
            if record.get("scenario", {}).get("state") in {"active", "applying", "restore_failed"}:
                try:
                    self.scenarios.reset(instance_id)
                except RuntimeError as exc:
                    record["scenario"]["teardown_error"] = str(exc)
            existing_bridges = command("ovs-vsctl", "list-br").splitlines()
            for bridge in record["bridges"]:
                if bridge in existing_bridges and not self._owned_bridge(bridge, record):
                    raise ValueError("refusing stop after bridge ownership mismatch")
            for interface in record["root_interfaces"]:
                raw = command("ip", "-j", "link", "show", "dev", interface["name"], check=False)
                if raw and json.loads(raw)[0]["ifindex"] != interface["ifindex"]:
                    raise ValueError("refusing stop after interface ownership mismatch")
            record["state"] = "stopping"
            self._save(record)
            for run_id, session in list(self.sessions.items()):
                if session["instance_id"] == instance_id:
                    self._finish_run(run_id, "canceled")
            live = self.instances[instance_id]
            try:
                live["net"].stop()
                if record.get("scenario", {}).get("state") == "restore_failed":
                    record["scenario"].update(state="terminated", deactivated_utc=utc())
                    self.scenarios._save_journal(live)
                record["state"] = "stopped"
                record["host_processes"] = []
                record["traffic_processes"] = []
                record.pop("error", None)
                del self.instances[instance_id]
            except Exception as exc:
                record["state"] = "failed"
                record["error"] = str(exc)
                raise
            finally:
                self._save(record)
            return self.inspect(instance_id, detailed=False)

    def cleanup(self, instance_id):
        identifier(instance_id)
        with self.lock:
            if instance_id in self.instances:
                return self.stop(instance_id)
            record = self.records.get(instance_id)
            if record is None:
                return {"instance_id": instance_id, "state": "stopped", "live_verified": True}
            conflicts = []
            bridges = command("ovs-vsctl", "list-br").splitlines()
            for bridge in record.get("bridges", []):
                if bridge in bridges:
                    if self._owned_bridge(bridge, record):
                        command("ovs-vsctl", "--if-exists", "del-br", bridge)
                    else:
                        conflicts.append(bridge)
            for identity in record.get("traffic_processes", []) + record.get("host_processes", []):
                stop_owned_process(identity)
            for interface in record.get("root_interfaces", []):
                raw = command("ip", "-j", "link", "show", "dev", interface["name"], check=False)
                if raw:
                    current = json.loads(raw)[0]
                    if current["ifindex"] == interface["ifindex"]:
                        command("ip", "link", "del", "dev", interface["name"])
                    else:
                        conflicts.append(interface["name"])
            record["state"] = "failed" if conflicts else "stopped"
            record["error"] = "ownership mismatch: " + ", ".join(conflicts) if conflicts else None
            record["host_processes"] = []
            record["traffic_processes"] = []
            self._save(record)
            if conflicts:
                raise ValueError(record["error"])
            return self.inspect(instance_id, detailed=False)

    def shutdown(self):
        self._stop.set()
        self.monitor.join(timeout=3)
        for instance_id in list(self.instances):
            self.stop(instance_id)
        fcntl.flock(self._lockfile, fcntl.LOCK_UN)
        self._lockfile.close()
