"""Write and inspect declared schedules; this command never starts collection."""

import json
from pathlib import Path

from explainnet.dataset_contracts import digest, make_schedule

for purpose in ("pilot", "main", "expansion"):
    schedule = make_schedule(purpose)
    path = Path("config/datasets") / f"{purpose}_v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schedule.model_dump_json(indent=2) + "\n")
    print(json.dumps({"path": str(path), "schedule_hash": digest(schedule.model_dump()),
        "episodes": len(schedule.episodes), "target_windows": sum(e.target_windows for e in schedule.episodes),
        "steady_measurement_minutes": sum(e.scenario.measurement_s for e in schedule.episodes) / 60,
        "planned_runtime_minutes_excluding_startup": sum(e.scenario.measurement_s + schedule.baseline_s + schedule.recovery_s + 6 for e in schedule.episodes) / 60}))
