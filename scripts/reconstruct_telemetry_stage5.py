#!/usr/bin/env python3
"""Reconstruct windows directly from JSONL; verify SQLite indexes and feature allowlist.

--refresh is for archived pilot schema revisions only. Raw files are never changed.
"""

import argparse
import hashlib
import json
from pathlib import Path

from explainnet.contracts import ServiceObjective
from explainnet.storage import Store
from explainnet.telemetry_contracts import FEATURES, TelemetrySettings
from explainnet.telemetry_math import aggregate_windows
from explainnet.telemetry_monitor import evaluate
from explainnet.telemetry_storage import TelemetryRepository, reject_ground_truth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    store = Store(args.data_dir / "explainnet.sqlite3")
    repo = TelemetryRepository(store)
    config_path = args.data_dir.parent / "config.json"
    objective = ServiceObjective.model_validate(json.loads(config_path.read_text()).get("objective", {}))
    report = {"schema_version": 1, "status": "complete", "source": "real saved JSONL", "collections": [],
              "raw_unchanged": True, "feature_allowlist": sorted(FEATURES)}
    for session in repo.collectors():
        run_id = session["run_id"]
        path = repo.directory / (run_id + ".jsonl")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert data.endswith(b"\n"), "incomplete raw tail"
        records = [json.loads(line) for line in data.splitlines()]
        assert len({r["sample_id"] for r in records}) == len(records)
        with store.connection() as db:
            indexed = {r[0]: r[1] for r in db.execute("SELECT sample_id,content_hash FROM telemetry_samples WHERE run_id=?", (run_id,))}
            saved = {r[0]: json.loads(r[1]) for r in db.execute("SELECT window_id,payload_json FROM telemetry_windows WHERE run_id=?", (run_id,))}
        assert set(indexed) == {r["sample_id"] for r in records}
        for r in records:
            reject_ground_truth(r)
            payload = json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False)
            assert hashlib.sha256(payload.encode()).hexdigest() == indexed[r["sample_id"]]
        settings = TelemetrySettings.model_validate(session["settings"])
        now = session["ended_monotonic_s"]
        windows = aggregate_windows(records, session, settings, now, final=True)
        reference = repo.reference(session["instance_id"])
        alerts = evaluate(windows, settings, objective, reference)
        revisions = []
        for w in windows:
            old = saved[w["window_id"]]
            if w["features"] != old["features"] or w["inference_ready"] != old["inference_ready"]:
                revisions.append({"window_id": w["window_id"], "old_ready": old["inference_ready"],
                    "new_ready": w["inference_ready"], "changed_features": sorted(name for name in FEATURES
                    if name not in old["features"] or w["features"][name] != old["features"][name])})
                assert args.refresh, "feature reconstruction mismatch"
            assert set(w["features"]) == FEATURES
            reject_ground_truth(w)
        if args.refresh:
            repo.save_windows(windows, alerts)
        assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
        report["collections"].append({"run_id": run_id, "raw_records": len(records), "raw_sha256": digest,
            "windows": len(windows), "inference_ready_windows": sum(w["inference_ready"] for w in windows),
            "quality_reasons": sorted({reason for w in windows for reason in w["data_quality"]["reasons"]}),
            "optional_invalid_counter_windows": sum(bool(w["directional"].get("s3->s5", {}).get("invalid_intervals")) for w in windows),
            "schema_revisions": revisions})
    with store.connection() as db:
        for row in db.execute("SELECT features_json FROM inference_ready_windows"):
            assert set(json.loads(row[0])) == FEATURES
    output = args.data_dir.parent / "reconstruction_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
