"""Bounded laboratory recipes; stdlib validation shared by the root agent."""

from explainnet.topology.spec import fields

KINDS = {"healthy", "saturation", "loss", "latency", "qos"}


def validate_scenario(s):
    fields(s, ["schema_version", "config_version", "kind", "severity", "warmup_s", "measurement_s",
               "bidirectional", "variation_ms", "high_utilization", "traffic_profile"],
           ["critical_bps", "bulk_protocol", "packet_size", "seed"])
    if type(s["schema_version"]) is not int or s["schema_version"] != 1 or s["config_version"] not in {"pilot_v1", "dataset_v1", "recovery_observation_v1"}:
        raise ValueError("unsupported scenario version")
    if s["kind"] not in KINDS or s["severity"] not in {"low", "medium", "high"}:
        raise ValueError("unsupported scenario or severity")
    for key, low, high in (("warmup_s", 1, 5), ("measurement_s", 4, 900 if s["config_version"] == "recovery_observation_v1" else 100 if s["config_version"] == "dataset_v1" else 20), ("variation_ms", 0, 10)):
        if type(s[key]) is not int or not low <= s[key] <= high:
            raise ValueError(f"invalid {key}")
    critical = s.get("critical_bps")
    if critical is not None and (type(critical) is not int or not 1_000_000 <= critical <= 8_000_000):
        raise ValueError("invalid critical demand")
    if s.get("bulk_protocol", "udp") not in {"tcp", "udp"}:
        raise ValueError("invalid bulk protocol")
    for key, default, low, high in (("packet_size", 1200, 600, 1400), ("seed", 20261007, 0, 2147483647)):
        value = s.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"invalid {key}")
    if s["config_version"] == "pilot_v1" and (critical is not None or s.get("bulk_protocol", "udp") != "udp"
            or s.get("packet_size", 1200) != 1200 or s.get("seed", 20261007) != 20261007):
        raise ValueError("workload overrides require dataset_v1")
    if s["traffic_profile"] == "qos_competing" and critical not in {None, 2_000_000}:
        raise ValueError("QoS critical workload remains the matched 2 Mbps control")
    for key in ("bidirectional", "high_utilization"):
        if type(s[key]) is not bool:
            raise ValueError(f"invalid {key}")
    if s["bidirectional"] and s["kind"] not in {"loss", "latency"}:
        raise ValueError("reverse impairment requires loss or latency")
    if s["variation_ms"] and s["kind"] != "latency":
        raise ValueError("variation requires latency")
    if s["high_utilization"] and s["kind"] != "healthy":
        raise ValueError("high utilization is a separate healthy control")
    if s["traffic_profile"] not in {"moderate", "shared", "qos_competing"}:
        raise ValueError("unsupported traffic profile")
    if s["kind"] == "qos" and s["traffic_profile"] != "qos_competing":
        raise ValueError("QoS requires the matched competing workload")
    if s["kind"] in {"loss", "latency"} and s["traffic_profile"] != "moderate":
        raise ValueError("loss/delay require moderate traffic")
    if s["kind"] == "saturation" and s["traffic_profile"] != "shared":
        raise ValueError("saturation requires shared traffic")
    if s["high_utilization"] and s["traffic_profile"] != "shared":
        raise ValueError("high utilization requires shared traffic")
    return s


def loss_percent(fraction):
    if isinstance(fraction, bool) or not 0 <= fraction <= 1:
        raise ValueError("loss must be a fraction")
    return f"{fraction * 100:.6f}%"


def recipe(s):
    validate_scenario(s)
    level = {"low": 0, "medium": 1, "high": 2}[s["severity"]]
    return {"loss_fraction": (0.03, 0.08, 0.15)[level] if s["kind"] == "loss" else 0,
            "added_delay_ms": (15, 35, 60)[level] if s["kind"] == "latency" else 0,
            "background_bps": (92_000_000, 97_000_000, 100_000_000)[level]
            if s["kind"] == "saturation" else 70_000_000 if s["high_utilization"] else 0,
            "critical_ceiling_bps": (800_000, 500_000, 300_000)[level] if s["kind"] == "qos" else 4_000_000}
