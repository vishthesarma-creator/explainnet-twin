"""Structural dataset audits and atomic exports; never exploratory test-set analysis."""

import csv
import fcntl
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from explainnet.dataset_contracts import CLASSES, Schedule, digest
from explainnet.dataset_repository import DatasetRepository
from explainnet.telemetry_contracts import FEATURES, TelemetrySettings
from explainnet.telemetry_math import aggregate_windows
from explainnet.telemetry_storage import reject_ground_truth
from explainnet.topology.spec import identifier


def phase_for_window(window, receipt, traffic, settling_s=5):
    """Require wholly steady bounds inside successful actual activation/deactivation."""
    journal = receipt.get("laboratory_journal") or {}
    if journal.get("state") != "stopped" or journal.get("restore_errors") or not journal.get("activated_utc") or not journal.get("deactivated_utc"):
        return "unverified"
    if traffic.get("state") != "succeeded":
        return "unverified"
    end = datetime.fromisoformat(window["at_utc"])
    start = end - timedelta(seconds=window["duration_s"])
    active = datetime.fromisoformat(journal["activated_utc"])
    traffic_start = datetime.fromisoformat(traffic["created_utc"])
    warmup = journal["configuration"]["warmup_s"]
    begin = max(active, traffic_start + timedelta(seconds=warmup)) + timedelta(seconds=settling_s)
    finish = min(datetime.fromisoformat(journal["deactivated_utc"]), datetime.fromisoformat(traffic["ended_utc"]))
    if start < begin or end > finish:
        return "transition_or_warmup"
    if window["context"]["traffic_run_ids"] != [traffic["run_id"]]:
        return "mixed_traffic"
    return "steady" if window["inference_ready"] and window["complete"] else "quality_rejected"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def write_lines(path, rows):
    temp = path.with_suffix(".tmp")
    with temp.open('w') as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    temp.replace(path)


def valid_window_duration(window):
    return math.isclose(window["end_monotonic_s"] - window["start_monotonic_s"], 10,
                        rel_tol=0, abs_tol=1e-8)


def export_dataset(store, batch_id):
    identifier(batch_id)
    directory = store.path.parent / "datasets" / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "export.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _export_dataset(store, batch_id)


def _export_dataset(store, batch_id):
    repository = DatasetRepository(store)
    batch = repository.batch(batch_id)
    if not batch:
        raise ValueError("unknown batch")
    schedule = Schedule.model_validate(batch["schedule"])
    assert digest(schedule.model_dump()) == batch["schedule_hash"], "schedule hash mismatch"
    episodes = {e.episode_id: e for e in schedule.episodes}
    attempts = repository.audit_summaries(batch_id)
    current_attempt_id, attempt = None, None
    members = repository.members(batch_id)
    output = store.path.parent / "datasets" / batch_id
    output.mkdir(parents=True, exist_ok=True)
    features, labels, provenance = [], [], []
    errors, raw_files, sample_maps, reconstructed = [], {}, {}, {}
    class_counts, episode_counts, split_counts, missing = Counter(), Counter(), Counter(), Counter()
    duplicate_ranges, seen_samples = {}, {}
    families = {}
    episode_partitions = {}
    for member in members:
        episode = episodes[member['episode_id']]
        if member['attempt_id'] != current_attempt_id:
            attempt = repository.attempt(member['attempt_id'])
            current_attempt_id = member['attempt_id']
            # Members are grouped by episode; do not retain hundreds of parsed
            # native runs. Cross-partition provenance checks below remain global.
            sample_maps.clear()
            reconstructed.clear()
        with store.connection() as db:
            row = db.execute("SELECT payload_json FROM telemetry_windows WHERE window_id=?", (member["window_id"],)).fetchone()
        if not row:
            errors.append("missing stored window: " + member["window_id"])
            continue
        window = json.loads(row[0])
        try:
            if digest(window) != member["window_hash"]:
                raise ValueError("accepted window changed after finalization")
            reject_ground_truth(window)
            if set(window["features"]) != FEATURES or window["feature_schema_version"] != 1 or window["duration_s"] != 10:
                raise ValueError("unexpected feature schema or duration")
            if window["feature_schema_hash"] != hashlib.sha256(",".join(sorted(FEATURES)).encode()).hexdigest():
                raise ValueError("feature allowlist hash mismatch")
            if any(value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)) for value in window["features"].values()):
                raise ValueError("nonfinite or nonnumeric feature")
            if not valid_window_duration(window):
                raise ValueError("counter/window time inconsistency")
            if phase_for_window(window, attempt["main_reset_receipt"], attempt["main_traffic"], schedule.settling_s) != "steady":
                raise ValueError("window outside verified steady phase")
            if not attempt.get("restoration_verified") or attempt["state"] != "completed":
                raise ValueError("episode restoration or completion unverified")
            if member["partition"] != episode.partition or member["family_id"] != episode.family_id:
                raise ValueError("schedule split membership mismatch")
            if families.setdefault(episode.family_id, episode.partition) != episode.partition:
                raise ValueError("family overlaps partitions")
            if episode_partitions.setdefault(episode.episode_id, episode.partition) != episode.partition:
                raise ValueError("episode overlaps partitions")
            interval = (attempt["main_traffic"]["run_id"], window["start_monotonic_s"], window["end_monotonic_s"])
            if interval in duplicate_ranges:
                raise ValueError("duplicated measurement window")
            duplicate_ranges[interval] = member["window_id"]
            run_id = window["run_id"]
            if run_id not in sample_maps:
                path = store.path.parent / "raw" / "telemetry" / f"{run_id}.jsonl"
                raw = path.read_bytes()
                if not raw.endswith(b"\n"):
                    raise ValueError("raw JSONL has partial tail")
                samples = [json.loads(line) for line in raw.splitlines()]
                for sample in samples:
                    reject_ground_truth(sample)
                sample_maps[run_id] = {s["sample_id"]: s for s in samples}
                if len(sample_maps[run_id]) != len(samples):
                    raise ValueError("duplicate raw sample")
                raw_files[str(path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "records": len(samples)}
                with store.connection() as db:
                    indexed = {r[0]: r[1] for r in db.execute("SELECT sample_id,content_hash FROM telemetry_samples WHERE run_id=?", (run_id,))}
                if indexed != {s["sample_id"]: digest(s) for s in samples}:
                    raise ValueError("raw/index content mismatch")
                with store.connection() as db:
                    session = json.loads(db.execute("SELECT payload_json FROM telemetry_collectors WHERE run_id=?", (run_id,)).fetchone()[0])
                rebuilt = aggregate_windows(samples, session, TelemetrySettings.model_validate(session["settings"]),
                                            session["ended_monotonic_s"], final=True)
                reconstructed[run_id] = {w["window_id"]: w for w in rebuilt}
            rebuilt = reconstructed[run_id].get(window["window_id"])
            if not rebuilt or rebuilt["features"] != window["features"] or not rebuilt["inference_ready"]:
                raise ValueError("stored features do not reconstruct from raw observations")
            sources = sample_maps[run_id]
            if not window["sample_ids"] or any(sample_id not in sources for sample_id in window["sample_ids"]):
                raise ValueError("missing raw provenance")
            for sample_id in window["sample_ids"]:
                if seen_samples.setdefault(sample_id, episode.partition) != episode.partition:
                    raise ValueError("raw measurements overlap partitions")
            # Receipt kind is a target label, never a feature or a filter on measured values.
            truth = attempt["main_reset_receipt"]["laboratory_journal"]
            if truth["configuration"]["kind"] != episode.scenario.kind:
                raise ValueError("receipt label mismatch")
            stored_truth = store.get_record("ground_truth", attempt["main_traffic"]["run_id"])
            if (not stored_truth or stored_truth["payload"]["fault_label"] != episode.scenario.kind
                    or datetime.fromisoformat(stored_truth["payload"]["activated_utc"]) != datetime.fromisoformat(truth["activated_utc"])
                    or datetime.fromisoformat(stored_truth["payload"]["deactivated_utc"]) != datetime.fromisoformat(truth["deactivated_utc"])):
                raise ValueError("separate ground-truth record does not align with receipt")
        except (ValueError, KeyError, OSError, AssertionError) as exc:
            errors.append(f"{member['window_id']}: {exc}")
            continue
        features.append({"window_id": window["window_id"], **window["features"]})
        labels.append({"window_id": window["window_id"], "episode_id": episode.episode_id,
            "label": episode.scenario.kind, "phase": "steady", "traffic_run_id": attempt["main_traffic"]["run_id"],
            "activated_utc": truth["activated_utc"], "deactivated_utc": truth["deactivated_utc"],
            "configuration": truth["configuration"], "injection_parameters": truth["parameters"]})
        provenance.append({"window_id": window["window_id"], "episode_id": episode.episode_id,
            "collector_run_id": run_id, "attempt_id": attempt["attempt_id"], "at_utc": window["at_utc"],
            "start_monotonic_s": window["start_monotonic_s"], "end_monotonic_s": window["end_monotonic_s"],
            "source_sample_ids": window["sample_ids"], "raw_path": str(store.path.parent / "raw/telemetry" / f"{run_id}.jsonl"),
            "window_hash": member["window_hash"], "context": window["context"], "data_quality": window["data_quality"]})
        class_counts[episode.scenario.kind] += 1
        split_counts[episode.partition] += 1
        episode_counts[episode.episode_id] += 1
        missing.update(name for name, value in window["features"].items() if value is None)
    completed = {a["episode_id"] for a in attempts if a["state"] == "completed"}
    shortfalls = {e.episode_id: {"expected": e.target_windows, "actual": episode_counts[e.episode_id]}
                  for e in schedule.episodes if episode_counts[e.episode_id] != e.target_windows}
    rejected = Counter(reason for a in attempts for rejection in a.get("rejected_windows", []) for reason in rejection["reasons"])
    quality = {"schema_version": 1, "batch_id": batch_id, "purpose": schedule.purpose,
        "structural_checks_passed": not errors, "errors": errors, "class_counts": {kind: class_counts[kind] for kind in CLASSES},
        "accepted_windows": len(features), "completed_episodes": len(completed), "expected_episodes": len(schedule.episodes),
        "expected_windows": sum(e.target_windows for e in schedule.episodes), "episode_window_counts": dict(episode_counts),
        "independent_episodes_by_class": {kind: sum(episodes[e].scenario.kind == kind for e in completed) for kind in CLASSES},
        "partitions": dict(split_counts), "missing_feature_counts": {name: missing[name] for name in sorted(FEATURES)}, "shortfalls": shortfalls,
        "class_counts_by_partition": {p: dict(Counter(label["label"] for label in labels
            if episodes[label["episode_id"]].partition == p)) for p in split_counts},
        "completed_families_by_partition": {p: len({episodes[e].family_id for e in completed if episodes[e].partition == p}) for p in split_counts},
        "rejected_window_count": sum(len(a.get("rejected_windows", [])) for a in attempts),
        "rejected_window_reasons": dict(rejected), "attempt_errors": [a.get("error") for a in attempts if a.get("error")],
        "episode_overlap": False if not errors else None, "family_overlap": False if not errors else None,
        "duplicated_measurement_windows": False if not errors else None,
        "ground_truth_in_features": False if not errors else None,
        "test_handling": "Structural checks only; no exploratory test-feature analysis or model development",
        "dataset_ready": schedule.purpose in {"main", "expansion"} and batch["state"] == "completed" and not errors and not shortfalls}
    feature_path = output / "features.csv"
    with feature_path.with_suffix(".tmp").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["window_id", *sorted(FEATURES)])
        writer.writeheader()
        writer.writerows(features)
    feature_path.with_suffix(".tmp").replace(feature_path)
    write_lines(output / "labels.jsonl", labels)
    write_lines(output / "provenance.jsonl", provenance)
    write_lines(output / "episodes.jsonl", repository.iter_attempts(batch_id))
    splits = {p: {"episode_ids": [e.episode_id for e in schedule.episodes if e.partition == p],
                  "family_ids": sorted({e.family_id for e in schedule.episodes if e.partition == p}),
                  "window_ids": [m["window_id"] for m in members if m["partition"] == p],
                  "phase_policy": "All baseline, steady and recovery observations inherit their episode partition"}
              for p in ({"pilot"} if schedule.purpose == "pilot" else {"train", "validation", "test"})}
    atomic_json(output / "splits.json", splits)
    atomic_json(output / "schedule.json", schedule.model_dump())
    atomic_json(output / "quality_report.json", quality)
    files = {name: {"sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(), "bytes": (output / name).stat().st_size}
             for name in ("features.csv", "labels.jsonl", "provenance.jsonl", "episodes.jsonl", "splits.json", "schedule.json", "quality_report.json")}
    manifest = {"schema_version": 1, "dataset_version": "completion3_v1" if schedule.config_version == 'completion3_v1' else "initial_v1", "batch_id": batch_id,
        "state": batch["state"], "dataset_ready": quality["dataset_ready"], "purpose": schedule.purpose,
        "source": "Measured Mininet/OVS/Linux tc/iperf emulation; no synthetic rows",
        "schedule_hash": batch["schedule_hash"], "recovery_amendment": batch.get("recovery_amendment"),
        "environment": batch.get("environment"),
        "application_config_hash": batch["config_hash"], "topology_hash": digest(batch["definition"]),
        "feature_schema_version": 1, "feature_columns": sorted(FEATURES), "metadata_columns": ["window_id"],
        "units": {"_ms": "milliseconds", "_bps": "bits/second", "_fraction": "fraction", "_pps": "packets/second", "_bytes": "bytes", "active_flow_count": "count"},
        "accepted_windows": len(features), "completed_episodes": len(completed), "files": files,
        "raw_files": raw_files, "quality_report": str(output / "quality_report.json"),
        "limitations": ["Emulator-generated course-project dataset, not production-scale evidence",
            "Seeds do not guarantee packet-sequence reproducibility", "Receiver intervals available at traffic completion",
            "Missing optional metrics remain null; no fitted preprocessing", "Fault location fixed to supported s2->s3 and QoS s3->s5; loss/delay directions vary",
            "Workload and class settings may be confounded; matched healthy controls reduce but do not eliminate this risk"]}
    atomic_json(output / "manifest.json", manifest)
    if batch.get("artifact_dir"):
        artifact = Path(batch["artifact_dir"])
        atomic_json(artifact / ("pilot_quality_report.json" if schedule.purpose == "pilot" else "dataset_quality_report.json"), quality)
        atomic_json(artifact / ("pilot_manifest.json" if schedule.purpose == "pilot" else "dataset_manifest.json"),
                    manifest | {"authoritative_manifest": str(output / "manifest.json")})
        if schedule.purpose == "main":
            card = artifact.parent / "docs/DATASET_CARD.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(f"""# ExplainNet Twin initial dataset

Collection software: implemented. Collection state: **{batch['state']}**.
Dataset ready / Stage 7 gate: **{quality['dataset_ready']}**.

## Measured size and provenance

Accepted windows: **{len(features)} / {quality['expected_windows']}**.
Independent completed episodes: **{len(completed)} / {len(schedule.episodes)}**.
Class counts: `{dict(class_counts)}`. Partitions: `{dict(split_counts)}`.
Rejected windows: {quality['rejected_window_count']}; full reasons, missingness and shortfalls are in the quality report.

These are emulator-generated measurements from the fixed five-switch/six-host Mininet topology, OVS 3.7.1 and Linux tc. UDP/TCP receiver measurements come from installed iperf3 3.20; there are no manufactured, repeated, perturbed or oversampled rows. One independent network/namespace is created per episode attempt. UTC phase boundaries come from actual application/reset receipts; local monotonic intervals determine counter rates. Only wholly steady, complete inference-ready ten-second windows enter the feature table. Successful application and restoration are required before membership is committed. Failed attempts are retained separately.

## Faults and controls

Labels: healthy, saturation, loss, latency, qos. Saturation offers more than the fixed 100 Mbps shared capacity using h5→h6 background traffic. Loss is 3/8/15% netem impairment; latency adds 15/35/60 ms with supported reverse direction and optional 3 ms variation. These impairments use s2→s3 (and s3→s2 for bidirectional recipes). QoS restricts critical s3→s5 service to 0.8/0.5/0.3 Mbps under matched competing traffic, while the physical parent remains 20 Mbps. Healthy families include matched competing QoS and 70 Mbps background high-utilization controls with acceptable critical service.

## Collection and reserved splits

The predeclared compact schedule has 12 episodes per class, six accepted windows each (360 target). Each episode declares 85 seconds of measurement to allow five-second settling, window alignment and rejection overhead. Baseline/recovery controls each measure eight seconds, with two-second native omitted warmup. Actual pilot timing informed the estimate; approximately two hours plus resource-dependent overhead are expected for the batch. Episodes run sequentially under an experiment lock. One bounded retry preserves failed raw evidence.

Each class has six recipe families with two repetitions. Four families train, one validation, one test: **40/10/10 episodes**, or **66.7/16.7/16.7%**. Related recipes, all baseline/recovery records, and all windows from an episode inherit one partition. Evaluation reserves distinct load/packet size/direction combinations. The five-episode pilot is separate from the sealed main test set. Optional expansion declares 600 episodes / 3,600 windows and is not launched automatically.

The original declaration remains reserved. Current explicit recovery amendment: `{(batch.get('recovery_amendment') or {}).get('version', 'none')}`. Its full checksummed content/history is in the manifest; it may extend bounded collection time/attempts and declare sampler cadence. Actual collector settings remain in raw/storage provenance. Coverage, required receiver/probe gates, target windows and family/episode partitions remain enforced. Sampling cadence changes are a dataset limitation to retain in evaluation.

## Inputs, labels and structural checks

Features are the unchanged 21-column Stage 5 allowlist; units and sources are documented in `TELEMETRY_USAGE.md`. `window_id` is CSV metadata, not an input. All other IDs, timestamps, scenarios, severity, seeds, injection settings, filenames and partition labels are excluded from inputs. Missing optional RTT/jitter/class metrics remain null. Labels, split manifests, raw-source provenance and episode receipts are separate exports. No imputation, scaling, feature selection or model fitting has occurred.

Structural checks currently passed: **{not errors}**. They verify unique membership, schema/units, raw hashes/index alignment, raw reconstruction of accepted features, actual phase/ground-truth alignment, episode/family isolation and absence of cross-partition duplicate measurement sources. Test handling is structural only; future model development must use training/validation partitions. The quality report records explicit class shortfalls rather than dropping failed classes.

## Limitations and reproduction

This is a course-project emulation dataset, not production-scale evidence. Only supported fixed fault locations are varied in direction; arbitrary fault locations are not claimed. Workload/class correlation and emulator scheduling remain possible confounders despite matched controls. Seeds are recorded where supported but do not promise identical packet sequences. Resource pressure covers the Linux VM, not Windows. Receiver intervals arrive at completion; transition and partial windows are excluded. Exact state/counts/checksums are authoritative in `{output / 'manifest.json'}` and `artifacts/dataset_quality_report.json`.

See `DATASET_USAGE.md` for plan, status, cancellation, resume and export commands. Stage 7 may begin only when the main manifest reports `dataset_ready: true` and all required quality checks pass.
""")
    return {"manifest_path": str(output / "manifest.json"), "quality": quality}
