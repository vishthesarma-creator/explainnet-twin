#!/usr/bin/env python3
"""Bounded, isolated Linux networking smoke test for ExplainNet Twin Stage 1.

Run as root with the distribution Python, which can import apt's Mininet.
Only bridges, hosts, links, flows and QoS rows created here are removed.
"""

import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "network_smoke.json"


def run(*args, timeout=12, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def host_run(host, *args, timeout=12):
    proc = host.popen(list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f"{host.name}: {' '.join(args)} timed out")
    if proc.returncode:
        raise RuntimeError(f"{host.name}: {' '.join(args)}: {err.decode(errors='replace')}")
    return out.decode(errors="replace")


def make_net(prefix, subnet):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, build=False)
    a = net.addHost(prefix + "a", ip=f"10.77.{subnet}.1/24")
    b = net.addHost(prefix + "b", ip=f"10.77.{subnet}.2/24")
    sw = net.addSwitch(prefix + "s", failMode="secure")
    net.addLink(a, sw)
    net.addLink(b, sw)
    net.build()
    net.start()
    return net, a, b, sw


def main():
    results = {"at_utc": datetime.now(UTC).isoformat(), "checks": {}, "errors": []}
    nets = []
    qos_uuid = queue_uuid = None
    try:
        existing = [name for name in ("xt1s", "xt2s") if subprocess.run(
            ["ovs-vsctl", "br-exists", name], capture_output=True, timeout=5, check=False
        ).returncode == 0]
        if existing:
            raise RuntimeError(f"Refusing to touch existing OVS bridge(s): {existing}")
        net1, a, b, sw1 = make_net("xt1", 11)
        nets.append(net1)
        net2, c, d, sw2 = make_net("xt2", 12)
        nets.append(net2)
        out_port = run("ovs-vsctl", "get", "Interface", "xt1s-eth2", "ofport")
        in_port = run("ovs-vsctl", "get", "Interface", "xt1s-eth1", "ofport")
        reverse_in = run("ovs-vsctl", "get", "Interface", "xt1s-eth2", "ofport")
        reverse_out = run("ovs-vsctl", "get", "Interface", "xt1s-eth1", "ofport")
        run("ovs-ofctl", "add-flow", "xt1s", f"priority=100,in_port={in_port},actions=output:{out_port}")
        run("ovs-ofctl", "add-flow", "xt1s", f"priority=100,in_port={reverse_in},actions=output:{reverse_out}")
        run("ovs-ofctl", "add-flow", "xt2s", "priority=0,actions=NORMAL")

        ping = host_run(a, "ping", "-c", "3", "-W", "1", b.IP(), timeout=8)
        results["checks"]["host_connectivity_ovs"] = "0% packet loss" in ping
        counters = run("ovs-ofctl", "dump-ports", "xt1s")
        results["checks"]["counter_collection"] = "rx pkts=" in counters and "tx pkts=" in counters
        results["evidence_counters"] = counters[:1200]
        ping2 = host_run(c, "ping", "-c", "2", "-W", "1", d.IP(), timeout=6)
        host_run(c, "ip", "route", "add", "10.77.11.0/24", "dev", "xt2a-eth0")
        cross = c.popen(["ping", "-c", "1", "-W", "1", b.IP()], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cross_out, _ = cross.communicate(timeout=4)
        results["checks"]["coexisting_isolated_networks"] = (
            "0% packet loss" in ping2 and cross.returncode != 0 and
            b.name != d.name and sw1.name != sw2.name
        )
        results["evidence_isolation"] = cross_out.decode(errors="replace")[:400]

        server = b.popen(["iperf3", "-s", "-1", "-J"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.4)
        tcp = json.loads(host_run(a, "iperf3", "-c", b.IP(), "-b", "2M", "-t", "2", "-J", timeout=8))
        server.communicate(timeout=5)
        results["checks"]["iperf3_tcp"] = tcp["end"]["sum_received"]["bits_per_second"] > 0
        results["tcp_receiver_bps"] = tcp["end"]["sum_received"]["bits_per_second"]

        server = b.popen(["iperf3", "-s", "-1", "-J"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.4)
        udp = json.loads(host_run(a, "iperf3", "-c", b.IP(), "-u", "-b", "1M", "-t", "2", "-J", timeout=8))
        server.communicate(timeout=5)
        receiver = udp["end"]["sum"]
        results["checks"]["iperf3_udp_receiver"] = "lost_percent" in receiver and "jitter_ms" in receiver
        results["udp_receiver"] = {k: receiver.get(k) for k in ("bits_per_second", "lost_percent", "jitter_ms")}

        dev = "xt1a-eth0"
        host_run(a, "tc", "qdisc", "replace", "dev", dev, "root", "netem", "delay", "40ms", "loss", "35%")
        impaired = host_run(a, "ping", "-c", "12", "-i", "0.1", "-W", "1", b.IP(), timeout=16)
        host_run(a, "tc", "qdisc", "del", "dev", dev, "root")
        match = re.search(r"(\d+)% packet loss", impaired)
        rtts = re.search(r"rtt min/avg/max/mdev = [^/]+/([0-9.]+)/", impaired)
        results["checks"]["tc_delay_loss"] = bool(match and int(match.group(1)) > 0 and rtts and float(rtts.group(1)) >= 35)
        results["evidence_impairment"] = impaired[-550:]

        queue_uuid = run("ovs-vsctl", "create", "Queue", "other-config:max-rate=2000000")
        qos_uuid = run("ovs-vsctl", "create", "QoS", "type=linux-htb", "other-config:max-rate=10000000", f"queues:1={queue_uuid}")
        run("ovs-vsctl", "set", "Port", "xt1s-eth2", f"qos={qos_uuid}")
        run("ovs-ofctl", "del-flows", "xt1s")
        run("ovs-ofctl", "add-flow", "xt1s", f"priority=100,in_port={in_port},actions=set_queue:1,output:{out_port}")
        run("ovs-ofctl", "add-flow", "xt1s", f"priority=100,in_port={reverse_in},actions=output:{reverse_out}")
        server = b.popen(["iperf3", "-s", "-1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.4)
        host_run(a, "iperf3", "-c", b.IP(), "-b", "1M", "-t", "2", timeout=8)
        server.communicate(timeout=5)
        stats = run("ovs-ofctl", "queue-stats", "xt1s")
        flows = run("ovs-ofctl", "dump-flows", "xt1s")
        results["evidence_queue"] = stats[:1000]
        results["evidence_queue_flow"] = flows[:1000]
        results["checks"]["ovs_queue_traffic"] = bool(re.search(rf"port\s+{out_port}\s+queue\s+1:\s+bytes=[1-9]\d*,\s+pkts=[1-9]\d*", stats)) and "set_queue:1" in flows
    except Exception as exc:  # noqa: BLE001 - persist any smoke failure and clean up
        results["errors"].append(str(exc))
    finally:
        if qos_uuid:
            run("ovs-vsctl", "clear", "Port", "xt1s-eth2", "qos", check=False)
            run("ovs-vsctl", "destroy", "QoS", qos_uuid, check=False)
        if queue_uuid:
            run("ovs-vsctl", "destroy", "Queue", queue_uuid, check=False)
        for net in reversed(nets):
            net.stop()
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
    return 0 if results["checks"] and all(results["checks"].values()) and not results["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
