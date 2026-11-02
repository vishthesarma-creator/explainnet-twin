"""Auditable interval aggregation. IDs/configuration are metadata, never feature columns."""

import hashlib
import math
import statistics
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from explainnet.telemetry_contracts import FEATURES


def delta_rate(before, after, elapsed_s, capacity_bps=None):
    if before is None or after is None or elapsed_s <= 0:
        return None, "missing counter or nonpositive elapsed time"
    if after < before:
        return None, "counter reset"
    rate = 8 * (after - before) / elapsed_s
    value = rate / capacity_bps if capacity_bps is not None else rate
    return value, "utilization outside [0,1]" if capacity_bps is not None and not 0 <= value <= 1 else None


def receiver_records(snapshot, collection_run_id):
    """One native receiver interval per record, available only after completed-run ingestion."""
    records = []
    for run in snapshot["completed_runs"] + snapshot.get('active_receiver_runs', []):
        for profile in run["profiles"]:
            p, native = profile["parameters"], profile.get("server_json")
            supported = run['state'] == 'succeeded' or (run['state'] == 'running' and p.get('stream_receiver') is True)
            if not supported or not native or native.get("error"):
                continue
            timestamp = native.get("start", {}).get("timestamp", {})
            millis = timestamp.get("timemillisecs")
            epoch = millis / 1000 if millis is not None else None
            omitted_end = max((i["sum"]["end"] for i in native.get("intervals", [])
                               if i.get("sum", {}).get("omitted")), default=0)
            anchor = profile.get('receiver_clock_anchor')
            if anchor and epoch is not None:
                connection_offset = epoch - anchor['utc_epoch_s']
                origin = anchor['monotonic_s'] + connection_offset + omitted_end if 0 <= connection_offset <= 3 else None
            else:
                origin = None if epoch is None else snapshot["monotonic_s"] + epoch - datetime.fromisoformat(snapshot["at_utc"]).timestamp() + omitted_end
            for index, interval in enumerate(native.get("intervals", [])):
                s = interval.get("sum", {})
                if s.get("omitted") or s.get("sender") is not False:
                    continue
                duration = s.get("seconds")
                loss, packets = s.get("lost_packets"), s.get("packets")
                valid = origin is not None and duration is not None and duration > 0 and s.get("bytes") is not None
                if p["protocol"] == "udp" and (packets is None or loss is None or not 0 <= loss <= packets):
                    valid = False
                key = f"{collection_run_id}:{run['run_id']}:{p['profile_id']}:{s['start']}:{s['end']}"
                records.append({"schema_version": 1, "sample_id": "i" + hashlib.sha256(key.encode()).hexdigest()[:32],
                    "run_id": collection_run_id, "traffic_run_id": run["run_id"], "source": "iperf_receiver_interval",
                    "instance_id": snapshot["instance_id"], "config_version": snapshot["config_version"],
                    "at_utc": snapshot["at_utc"], "available_utc": snapshot["at_utc"],
                    "measurement_start_utc": datetime.fromtimestamp(epoch + omitted_end + s["start"], UTC).isoformat() if epoch is not None else None,
                    "measurement_end_utc": datetime.fromtimestamp(epoch + omitted_end + s["end"], UTC).isoformat() if epoch is not None else None,
                    "start_monotonic_s": origin + s["start"] if origin is not None else None,
                    "end_monotonic_s": origin + s["end"] if origin is not None else None,
                    "duration_s": duration, "source_host": p["source_host"], "target_host": p["target_host"],
                    "protocol": p["protocol"], "bytes": s.get("bytes"), "packets": packets,
                    "lost_packets": loss, "jitter_ms": s.get("jitter_ms") if p["protocol"] == "udp" else None,
                    "valid": valid, "reason": None if valid else "missing receiver timing/counts or inconsistent loss",
                    "units": {"bytes": "bytes", "packets": "packets", "jitter": "ms", "duration": "s"},
                    "native_interval": interval, "time_source": "iperf receiver timestamp plus measured omitted duration; owned launch UTC/monotonic anchor when available"})
    return records


def configuration_key(s):
    flows = sorted((f["traffic_run_id"], f["source_host"], f["target_host"], f["protocol"], f["offered_bps"])
                   for f in s.get("active_flows", []))
    return (s.get("agent_epoch"), s.get("config_hash"), s.get("forwarding_version"), tuple(sorted(s.get("selected_paths", {}).items())),
            s.get("observed_config_hash"), tuple((d, link.get("identity")) for d, link in sorted(s.get("links", {}).items())), tuple(flows))


def aggregate_windows(records, session, settings, now_monotonic_s, final=False):
    snapshots = sorted((r for r in records if r["source"] == "network_agent"), key=lambda r: r["monotonic_s"])
    intervals = [r for r in records if r["source"] == "iperf_receiver_interval"]
    if not snapshots:
        return []
    anchor, width = session["started_monotonic_s"], settings.window_s
    end_time = min(now_monotonic_s, session.get("ended_monotonic_s") or now_monotonic_s)
    count = max(1, math.ceil((end_time - anchor) / width))
    windows = []
    for index in range(count):
        start, end = anchor + index * width, anchor + (index + 1) * width
        points = [s for s in snapshots if start <= s["monotonic_s"] < end]
        if not points:
            continue
        reasons, warnings = [], []
        complete = end <= end_time
        if not complete:
            reasons.append("incomplete window")
        if len({configuration_key(s) for s in points}) != 1:
            reasons.append("configuration, process epoch, traffic run or experiment transition")
        offsets = [datetime.fromisoformat(s["at_utc"]).timestamp() - s["monotonic_s"] for s in points]
        if max(offsets) - min(offsets) > 0.25:
            reasons.append("wall-clock discontinuity")
        features = {name: None for name in sorted(FEATURES)}
        rtts, transmitted, received = [], 0, 0
        successful_probes, failed_probes = 0, 0
        for point in points:
            probe = point.get("probe", {})
            if probe.get("valid") and start <= probe.get("start_monotonic_s", -1) and probe.get("end_monotonic_s", end + 1) <= end:
                transmitted += probe["transmitted"]
                received += probe["received"]
                rtts.extend(probe["rtt_values_ms"])
                successful_probes += probe["received"]
            elif not probe.get("valid"):
                failed_probes += 1
        if transmitted:
            features["ping_loss_fraction"] = 1 - received / transmitted
        if rtts:
            features.update(rtt_mean_ms=statistics.mean(rtts), rtt_p95_ms=sorted(rtts)[math.ceil(0.95 * len(rtts)) - 1],
                            rtt_variability_ms=statistics.pstdev(rtts))
        else:
            warnings.append("no successful RTT probes; RTT metrics unavailable")
        directional, class_totals, drop_totals = {}, {}, {}
        covered, cpu_values, cpu_totals = 0.0, [], [0, 0]
        used_snapshot_ids = {p["sample_id"] for p in points}
        for previous, current in pairwise(snapshots):
            a, b = previous["monotonic_s"], current["monotonic_s"]
            if not start <= a < b <= end:
                continue  # No interpolation or prorating across a window boundary.
            if configuration_key(previous) != configuration_key(current):
                reasons.append("configuration or run transition interval")
                continue
            elapsed = b - a
            if elapsed > settings.sample_interval_s * 2.5:
                warnings.append("sampling overrun")
                continue
            covered += elapsed
            used_snapshot_ids.update([previous["sample_id"], current["sample_id"]])
            for direction, new in current["links"].items():
                old = previous["links"].get(direction)
                if not old or not new["identity"] or old["identity"] != new["identity"]:
                    warnings.append("interface identity changed: " + direction)
                    continue
                old_counter, new_counter = old.get("counters"), new.get("counters")
                dt = new["monotonic_s"] - old["monotonic_s"]
                value, error = delta_rate(old_counter.get("bytes") if old_counter else None,
                                         new_counter.get("bytes") if new_counter else None, dt, new["capacity_bps"])
                if value is not None:
                    totals = directional.setdefault(direction, {"weighted_utilization": 0, "duration_s": 0, "invalid_intervals": []})
                    totals["weighted_utilization"] += value * dt
                    totals["duration_s"] += dt
                if error:
                    warnings.append(f"{direction}: {error}")
                    if direction in directional:
                        directional[direction]["invalid_intervals"].append({"value": value, "elapsed_s": dt, "reason": error,
                            "before_sample_id": previous["sample_id"], "after_sample_id": current["sample_id"]})
                    if direction == "s2->s3":
                        reasons.append(f"invalid counter interval: {direction}: {error}")
                for handle, cls in new.get("classes", {}).items():
                    prior = old.get("classes", {}).get(handle)
                    rate, error = delta_rate(prior.get("bytes") if prior else None, cls.get("bytes"), elapsed)
                    if rate is not None and not error:
                        totals = class_totals.setdefault((direction, handle), [0, 0])
                        totals[0] += rate * elapsed
                        totals[1] += elapsed
                    elif error:
                        warnings.append(f"class {direction}/{handle}: {error}")
                for handle, queue in new.get("queues", {}).items():
                    prior = old.get("queues", {}).get(handle)
                    old_drop, new_drop = prior.get("drops") if prior else None, queue.get("drops")
                    if old_drop is not None and new_drop is not None and new_drop >= old_drop:
                        totals = drop_totals.setdefault((direction, handle), [0, 0])
                        totals[0] += new_drop - old_drop
                        totals[1] += elapsed
            old_cpu, new_cpu = previous.get("resources", {}), current.get("resources", {})
            total = new_cpu.get("cpu_total_ticks", 0) - old_cpu.get("cpu_total_ticks", 0)
            idle = new_cpu.get("cpu_idle_ticks", 0) - old_cpu.get("cpu_idle_ticks", 0)
            if total > 0 and 0 <= idle <= total:
                cpu_values.append(1 - idle / total)
                cpu_totals[0] += total
                cpu_totals[1] += idle
        for direction, name in (("s2->s3", "shared_utilization_fraction"), ("s3->s5", "qos_utilization_fraction")):
            totals = directional.get(direction)
            if totals and totals["duration_s"]:
                features[name] = totals["weighted_utilization"] / totals["duration_s"] if not totals["invalid_intervals"] or direction == "s2->s3" else None
        for handle, name in (("5:10", "critical_class_rate_bps"), ("5:20", "bulk_class_rate_bps")):
            totals = class_totals.get(("s3->s5", handle))
            if totals and totals[1]:
                features[name] = totals[0] / totals[1]
        drops = drop_totals.get(("s2->s3", "10:"))
        if drops and drops[1]:
            features["shared_drop_rate_pps"] = drops[0] / drops[1]
        for handle, name, class_id in (("10:", "critical_drop_rate_pps", "5:10"), ("20:", "bulk_drop_rate_pps", "5:20")):
            totals = drop_totals.get(("s3->s5", handle))
            if class_id in points[-1]["links"].get("s3->s5", {}).get("classes", {}) and totals and totals[1]:
                features[name] = totals[0] / totals[1]
        backlog = [q["backlog"] for q in points[-1]["links"].get("s3->s5", {}).get("queues", {}).values()
                   if q.get("backlog") is not None]
        # Root+leaf backlog may refer to the same bytes: maximum, never a double-counted sum.
        features["queue_backlog_bytes"] = max(backlog) if backlog else None
        features["cpu_busy_fraction"] = 1 - cpu_totals[1] / cpu_totals[0] if cpu_totals[0] else None
        memory = [p.get("resources", {}).get("memory_used_fraction") for p in points]
        memory = [m for m in memory if m is not None]
        features["memory_used_fraction"] = statistics.mean(memory) if memory else None
        if (cpu_values and max(cpu_values) > settings.max_cpu_busy_fraction) or (memory and max(memory) > settings.max_memory_used_fraction):
            reasons.append("host resource contamination")
        demand = [sum(f["offered_bps"] for f in p["active_flows"]) for p in points]
        critical_demand = [sum(f["offered_bps"] for f in p["active_flows"]
                               if f["source_host"] == "h1" and f["target_host"] == "h3") for p in points]
        features.update(offered_demand_bps=statistics.mean(demand), critical_offered_bps=statistics.mean(critical_demand),
            active_flow_count=statistics.mean(len(p["active_flows"]) for p in points),
            primary_path_fraction=statistics.mean(p["selected_paths"].get("critical") == "primary" for p in points))
        receiver = sorted((i for i in intervals if i["valid"] and i["source_host"] == "h1" and i["target_host"] == "h3"
            and start <= i["start_monotonic_s"] < i["end_monotonic_s"] <= end), key=lambda i: i["end_monotonic_s"])
        duration = sum(i["duration_s"] for i in receiver)
        if duration:
            features["critical_goodput_bps"] = 8 * sum(i["bytes"] for i in receiver) / duration
        udp = [i for i in receiver if i["protocol"] == "udp"]
        packets = sum(i["packets"] for i in udp)
        if packets:
            features["udp_loss_fraction"] = sum(i["lost_packets"] for i in udp) / packets
            # Receiver jitter is its end-of-interval estimator, not an average of packet RTTs.
            features["udp_jitter_ms"] = udp[-1]["jitter_ms"]
        coverage = covered / width
        if coverage < settings.min_coverage_fraction:
            reasons.append("insufficient sample coverage")
        if features["ping_loss_fraction"] is None or transmitted < 6:
            reasons.append("missing bounded-probe counts")
        if features["shared_utilization_fraction"] is None:
            reasons.append("missing required directional utilization")
        if features["critical_offered_bps"] >= settings.demand_floor_bps and duration / width < settings.min_coverage_fraction:
            reasons.append("receiver intervals pending or insufficient receiver coverage")
        flows = {}
        for i in intervals:
            if i["valid"] and start <= i["start_monotonic_s"] < i["end_monotonic_s"] <= end:
                key = f"{i['source_host']}->{i['target_host']}:{i['protocol']}"
                flow = flows.setdefault(key, {"bytes": 0, "duration_s": 0, "packets": 0, "lost_packets": 0})
                flow["bytes"] += i["bytes"]
                flow["duration_s"] += i["duration_s"]
                if i["packets"] is not None:
                    flow["packets"] += i["packets"]
                    flow["lost_packets"] += i["lost_packets"]
        for flow in flows.values():
            flow["delivered_bps"] = 8 * flow["bytes"] / flow["duration_s"]
            flow["loss_fraction"] = flow["lost_packets"] / flow["packets"] if flow["packets"] else None
        base_utc = datetime.fromisoformat(session["started_utc"])
        window_id = "w" + hashlib.sha256(f"{session['run_id']}:{index}".encode()).hexdigest()[:32]
        missing = sorted(name for name, value in features.items() if value is None)
        missing_reasons = {name: "optional capability or compatible observation unavailable" for name in missing}
        for name in ("rtt_mean_ms", "rtt_p95_ms", "rtt_variability_ms"):
            if name in missing:
                missing_reasons[name] = "no received bounded probes; missing RTT is not zero RTT"
        if "qos_utilization_fraction" in missing and directional.get("s3->s5", {}).get("invalid_intervals"):
            missing_reasons["qos_utilization_fraction"] = "inconsistent optional counter intervals; raw values preserved, not clipped"
        for name in ("critical_goodput_bps", "udp_loss_fraction", "udp_jitter_ms"):
            if name in missing:
                missing_reasons[name] = "compatible finalized receiver intervals unavailable in this window"
        reasons = sorted(set(reasons))
        windows.append({"schema_version": 1, "window_id": window_id, "run_id": session["run_id"],
            "feature_schema_version": 1,
            "feature_schema_hash": hashlib.sha256(",".join(sorted(FEATURES)).encode()).hexdigest(),
            "instance_id": session["instance_id"], "at_utc": (base_utc + timedelta(seconds=(index + 1) * width)).astimezone(UTC).isoformat(),
            "start_monotonic_s": start, "end_monotonic_s": end, "duration_s": width, "complete": complete,
            "features": features, "per_flow": flows, "directional": directional,
            "quality": "valid" if not reasons else "partial", "inference_ready": complete and not reasons,
            "data_quality": {"reasons": reasons, "warnings": sorted(set(warnings)), "coverage_fraction": coverage,
                "sample_count": len(points), "transmitted_probes": transmitted, "successful_probe_count": successful_probes,
                "probe_timeouts": transmitted - received, "failed_probe_batches": failed_probes,
                "receiver_duration_s": duration, "missing_metrics": missing, "missing_metric_reasons": missing_reasons,
                "counter_resets": sum("counter reset" in warning for warning in warnings),
                "stale_age_s": max(0, now_monotonic_s - points[-1]["monotonic_s"])},
            "sample_ids": sorted(used_snapshot_ids) + [i["sample_id"] for i in receiver],
            "context": {"agent_epoch": points[-1].get('agent_epoch'), "config_hash":points[-1].get('config_hash'), "config_version": points[-1]["config_version"], "forwarding_version": points[-1]["forwarding_version"],
                "selected_paths": points[-1]["selected_paths"], "traffic_run_ids": sorted({f["traffic_run_id"] for p in points for f in p["active_flows"]})}})
    return windows
