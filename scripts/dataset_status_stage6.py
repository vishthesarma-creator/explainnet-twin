"""Read durable checkpoints without presenting dead-owner history as a live process."""

import argparse
import json
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store
from explainnet.telemetry_service import owner_ticks

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", type=Path, default=Path("artifacts/stage6/runtime"))
args = parser.parse_args()
supervisor = json.loads((args.runtime / "supervisor.json").read_text())
settings = load_settings(args.runtime / "config.json")
repo = DatasetRepository(Store(settings.database_path))
batch_id = supervisor.get("batch_id")
batch = repo.batch(batch_id) if batch_id else None
if batch:
    attempts = repo.attempts(batch_id)
    live = batch["state"] == "running" and owner_ticks(batch["owner_pid"]) == batch["owner_start_ticks"]
    print(json.dumps({"batch_id": batch_id, "state": batch["state"] if live or batch["state"] != "running" else "interrupted",
        "live_owner": live, "runner_pid": batch["owner_pid"], "supervisor_pid": supervisor["supervisor_pid"],
        "current_episode": batch.get("current_episode"), "phase": batch.get("phase"),
        "completed_episodes": sum(a["state"] == "completed" for a in attempts),
        "accepted_windows": len(repo.members(batch_id)), "expected_episodes": len(batch["schedule"]["episodes"]),
        "expected_windows": sum(e["target_windows"] for e in batch["schedule"]["episodes"]),
        "manifest_path": batch.get("manifest_path"), "error": batch.get("error"), "updated_utc": batch["updated_utc"]}, indent=2))
else:
    print(json.dumps(supervisor, indent=2))
