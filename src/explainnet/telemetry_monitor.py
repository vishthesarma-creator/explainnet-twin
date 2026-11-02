"""Transparent rule baseline with valid-window persistence and recovery hysteresis."""
from explainnet.service_requirements import VERSION
from explainnet.service_requirements import evaluate as service_evaluate


def rules(window, settings, objective, reference=None, recovering=False):
    f = window['features']
    violations = service_evaluate(window, objective, reference, settings, recovering)['violations']
    factor = settings.recovery_fraction if recovering else 1
    def upper(name, limit, unit, affected):
        value = f.get(name)
        if value is not None and limit is not None and value > limit * factor:
            violations.append({"rule": name, "actual": value, "threshold": limit * factor, "unit": unit, "affected": affected})
    upper("shared_utilization_fraction", settings.max_utilization_fraction, "fraction", "s2->s3")
    return violations


def evaluate(windows, settings, objective, reference=None):
    bad, good, active, previous_end = 0, 0, False, None
    results = []
    for w in windows:
        contiguous = previous_end is None or abs(w["start_monotonic_s"] - previous_end) < 0.001
        if not contiguous:
            bad, good = 0, 0
        previous_end = w["end_monotonic_s"]
        violations = rules(w, settings, objective, reference)
        limitations = w["data_quality"]["reasons"]
        if not w["inference_ready"]:
            status, bad, good = "insufficient-data", 0, 0
        elif violations:
            bad += 1
            good = 0
            active = active or bad >= settings.consecutive_windows
            status = "alert" if active else "healthy"
        else:
            bad = 0
            if active:
                good = good + 1 if not rules(w, settings, objective, reference, recovering=True) else 0
                active = good < settings.recovery_windows
            status = "alert" if active else "healthy"
        results.append({"window_id": w["window_id"], "instance_id": w["instance_id"], "status": status,
            'service_contract_version': VERSION, 'service_evidence': service_evaluate(w, objective, reference, settings),
            "method": "rule-based monitoring", "observation_utc": w["at_utc"], "violations": violations,
            "pending_violation_windows": bad, "recovery_windows": good, "alert_latched": active,
            "limitations": limitations + w["data_quality"]["warnings"], "reference_window_id": reference.get("window_id") if reference else None})
    return results
