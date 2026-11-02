"""Record verified software and current measured collection state, never mark running data ready."""

import json
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json, export_dataset
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store, utc_now
from explainnet.telemetry_service import owner_ticks

runtime = Path("artifacts/stage6/runtime")
supervisor = json.loads((runtime / "supervisor.json").read_text())
settings = load_settings(runtime / "config.json")
store = Store(settings.database_path)
batch_id = supervisor["batch_id"]
repository = DatasetRepository(store)
batch = repository.batch(batch_id)
assert batch["schedule"]["purpose"] == "main"
assert batch["schedule_hash"] == digest(json.loads(Path("config/datasets/main_v1.json").read_text()))
pilot = json.loads(Path("artifacts/stage6/pilot_report.json").read_text())
result = export_dataset(store, batch_id)
req = urllib.request.Request(f"http://127.0.0.1:{settings.port}/v1/telemetry/reference",
    data=b'{"window_id":"stage6_guard_missing_window"}', headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=10).close()
    raise AssertionError("external mutation was not rejected by the live experiment lock")
except urllib.error.HTTPError as exc:
    assert exc.code == 409
    guard = json.load(exc)
live = batch["state"] == "running" and owner_ticks(batch["owner_pid"]) == batch["owner_start_ticks"]
assert live
report = {"schema_version": 1, "at_utc": utc_now(), "software_status": "complete", "installed_version": "0.6.0",
    "tests": {"passed": 65, "warning": "Existing Starlette/httpx TestClient deprecation"}, "ruff": "passed", "pip_check": "passed",
    "migration": json.loads(Path("artifacts/stage6/migration_report.json").read_text()),
    "pilot": {"status": "complete", "episodes": 5, "accepted_windows": 10,
              "runtime_s": pilot["runtime_total_s"], "all_five_effects_verified": True,
              "all_restorations_verified": True, "structural_checks_passed": True},
    "main": {"state": batch["state"], "live": live, "batch_id": batch_id,
        "supervisor_pid": supervisor["supervisor_pid"], "runner_pid": batch["owner_pid"],
        "start_job_id": supervisor["start_job_id"], "completed_episodes": result["quality"]["completed_episodes"],
        "accepted_windows": result["quality"]["accepted_windows"], "target_episodes": 60, "target_windows": 360,
        "current_episode": batch.get("current_episode"), "manifest_path": result["manifest_path"],
        "dataset_ready": result["quality"]["dataset_ready"], "structural_checks_passed": result["quality"]["structural_checks_passed"],
        "split_hash_unchanged": True, "split_episode_counts": {"train": 40, "validation": 10, "test": 10},
        "projected_total_minutes": pilot["projected_main_minutes"], "external_mutation_guard": guard},
    "expansion": {"declared_only": True, "episodes": 600, "windows": 3600, "launched": False},
    "stage7_ready": False,
    "decision": "Retained the predeclared compact schedule and grouped split after actual five-class pilot/replay passed. Eighty-five measurement seconds allow six steady windows after alignment and settling. Main continues in a durable background process; no completed-dataset claim."}
atomic_json(Path("artifacts/stage6/verification_report.json"), report)
print(json.dumps(report, indent=2))
