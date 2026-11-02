"""Synthetic fixtures and explicit lifecycle doubles, never measured dataset rows."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_telemetry import BASE, interval, session, snapshot

from explainnet.dataset_contracts import Schedule, make_schedule
from explainnet.dataset_export import export_dataset, phase_for_window
from explainnet.dataset_service import CollectionCanceled, DatasetService
from explainnet.jobs import UnsupportedJob, Worker
from explainnet.scenario_contracts import Scenario
from explainnet.storage import Store
from explainnet.telemetry_contracts import FEATURES, TelemetrySettings
from explainnet.telemetry_math import aggregate_windows
from explainnet.telemetry_storage import TelemetryRepository


@pytest.mark.parametrize("purpose,episodes,windows", [("pilot", 5, 10), ("main", 60, 360), ("expansion", 600, 3600)])
def test_predeclared_sizes_and_group_assignments(purpose, episodes, windows):
    schedule = make_schedule(purpose)
    assert len(schedule.episodes) == episodes
    assert sum(e.target_windows for e in schedule.episodes) == windows
    groups = {}
    for episode in schedule.episodes:
        assert groups.setdefault(episode.family_id, episode.partition) == episode.partition
    if purpose == "main":
        assert [sum(e.partition == p for e in schedule.episodes) for p in ("train", "validation", "test")] == [40, 10, 10]


@pytest.mark.parametrize("defect", ["duplicate", "family", "renamed_recipe", "class", "pilot", "duration"])
def test_schedule_rejects_leakage_and_short_measurement(defect):
    value = make_schedule().model_dump()
    first, second = value["episodes"][:2]
    if defect == "duplicate":
        second["episode_id"] = first["episode_id"]
    elif defect == "family":
        second["partition"] = "test"
    elif defect == "renamed_recipe":
        second["family_id"] = "renamed_family"
        second["partition"] = "test"
    elif defect == "class":
        value["episodes"] = [e for e in value["episodes"] if e["scenario"]["kind"] != "qos"]
    elif defect == "pilot":
        first["partition"] = "pilot"
    else:
        first["scenario"]["measurement_s"] = 20
    with pytest.raises(ValidationError):
        Schedule.model_validate(value)


def test_versioned_recipe_extensions_remain_bounded():
    assert Scenario(kind="loss", config_version="dataset_v1", measurement_s=85, seed=610123).measurement_s == 85
    for changes in ({"measurement_s": 85}, {"seed": 610123}, {"critical_bps": 6000000}):
        with pytest.raises(ValidationError):
            Scenario(kind="loss", **changes)
    with pytest.raises(ValidationError):
        Scenario(kind="qos", config_version="dataset_v1", traffic_profile="qos_competing", critical_bps=8000000)


def fixture_receipt(scenario, run_id="r1"):
    traffic = {"run_id": run_id, "state": "succeeded", "created_utc": BASE.isoformat(),
        "ended_utc": (BASE + timedelta(seconds=38)).isoformat(), "config_hash": "fixture",
        "profiles": [{"parameters": {"profile_id": "critical"}}]}
    receipt = {"laboratory_journal": {"state": "stopped", "restore_errors": [], "configuration": scenario.model_dump(),
        "parameters": {}, "activated_utc": BASE.isoformat(), "deactivated_utc": (BASE + timedelta(seconds=40)).isoformat()},
        "traffic_runs": [traffic]}
    return receipt, traffic


def test_phase_labels_require_actual_success_and_wholly_steady_bounds():
    episode = make_schedule("pilot").episodes[0]
    receipt, traffic = fixture_receipt(episode.scenario)
    window = {"at_utc": (BASE + timedelta(seconds=20)).isoformat(), "duration_s": 10,
        "complete": True, "inference_ready": True, "context": {"traffic_run_ids": ["r1"]}}
    assert phase_for_window(window, receipt, traffic) == "steady"
    assert phase_for_window(window | {"at_utc": (BASE + timedelta(seconds=10)).isoformat()}, receipt, traffic) == "transition_or_warmup"
    bad = deepcopy(receipt)
    bad["laboratory_journal"]["activated_utc"] = None
    assert phase_for_window(window, bad, traffic) == "unverified"
    assert phase_for_window(window, receipt, traffic | {"state": "failed"}) == "unverified"
    assert phase_for_window(window | {"inference_ready": False}, receipt, traffic) == "quality_rejected"


def services(tmp_path):
    store = Store(tmp_path / "explainnet.sqlite3")
    store.initialize()
    agent = SimpleNamespace(capabilities=lambda: {"explicit_unit_double": True}, inventory=lambda: {"instances": []})
    telemetry = SimpleNamespace(settings=TelemetrySettings(), repository=TelemetryRepository(store))
    definition = SimpleNamespace(model_dump=lambda: {"explicit_unit_double": True})
    runner = DatasetService(store, agent, lambda *args: None, telemetry, definition, "fixture")
    return store, runner


def test_interrupted_recovery_is_explicit_and_uses_only_owned_ids(tmp_path, monkeypatch):
    _, runner = services(tmp_path)
    batch = runner.plan(make_schedule("pilot").model_dump())
    batch.update(state="running", owner_pid=99999999, owner_start_ticks="missing")
    runner.repository.save_batch(batch)
    attempt = {"attempt_id": "a1", "batch_id": batch["batch_id"], "episode_id": "e1", "state": "running", "instance_id": "owned1"}
    runner.repository.save_attempt(attempt)
    runner.reconcile()
    assert runner.repository.batch(batch["batch_id"])["state"] == "interrupted"
    assert runner.repository.attempts(batch["batch_id"])[0]["state"] == "interrupted"
    calls = []
    monkeypatch.setattr(runner, "_cleanup", lambda a: calls.append(a["instance_id"]) or True)
    runner._recover_attempts(batch)
    assert calls == ["owned1"]
    assert runner.repository.attempts(batch["batch_id"])[0]["cleanup_verified"]
    with pytest.raises(ValueError, match="explicit resume"):
        runner.start(batch["batch_id"])


def test_failed_injection_and_cancel_never_accept_labels(tmp_path, monkeypatch):
    _, runner = services(tmp_path)
    batch = runner.plan(make_schedule("pilot").model_dump())
    episode = make_schedule("pilot").episodes[0]
    monkeypatch.setattr(runner, "_job", lambda *args, **kwargs: {"session": {"run_id": "tfixture"}})
    monkeypatch.setattr(runner, "_phase", lambda *args: (_ for _ in ()).throw(ValueError("failed injection double")))
    monkeypatch.setattr(runner, "_cleanup", lambda _: True)
    with pytest.raises(ValueError, match="failed injection"):
        runner._episode(batch, episode)
    assert not runner.repository.members(batch["batch_id"])
    assert runner.repository.attempts(batch["batch_id"])[0]["state"] == "failed"
    runner.cancel_event.set()
    with pytest.raises(CollectionCanceled):
        runner._wait_traffic("owned", "r1", 1)
    assert not runner.repository.members(batch["batch_id"])


def test_completed_start_verifies_and_skips_rerun(tmp_path, monkeypatch):
    _, runner = services(tmp_path)
    batch = runner.plan(make_schedule("pilot").model_dump())
    batch["state"] = "completed"
    runner.repository.save_batch(batch)
    calls = []
    monkeypatch.setattr(runner, "_verify_completed", lambda b: calls.append(b["batch_id"]))
    assert runner.start(batch["batch_id"], resume=True)["batch"]["state"] == "completed"
    assert calls == [batch["batch_id"]] and runner.thread is None
    changed = make_schedule("pilot").model_dump()
    changed["episodes"][0]["scenario"]["seed"] += 1
    with pytest.raises(ValueError, match="incompatible"):
        runner.plan(changed)


def test_experiment_lock_blocks_external_mutations_but_preserves_internal_jobs(tmp_path):
    store, _ = services(tmp_path)
    worker = Worker(store, SimpleNamespace())
    worker.dataset.thread = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(UnsupportedJob, match="owns laboratory"):
        worker.submit("network_stop", "external", {"instance_id": "unrelated"})
    job_id = worker._submit_dataset("network_stop", "dataset-runner", {"instance_id": "owned"})
    assert store.get_job(job_id)["origin"] == "dataset"


def test_restart_cancels_orphan_queued_runner_operations(tmp_path):
    store, _ = services(tmp_path)
    store.create_job("jorphan", "network_stop", "dataset-runner", {"instance_id": "owned"}, origin="dataset")
    agent = SimpleNamespace(inventory=lambda: {"instances": []})
    worker = Worker(store, agent)
    worker.start()
    try:
        assert store.get_job("jorphan")["state"] == "canceled"
    finally:
        worker.stop()


def test_membership_deduplicates_and_rejects_cross_partition(tmp_path):
    store, runner = services(tmp_path)
    schedule = make_schedule("pilot")
    batch = runner.plan(schedule.model_dump())
    repo = TelemetryRepository(store)
    collector = session() | {"state": "stopped", "owner_pid": 1, "owner_start_ticks": "1", "settings": TelemetrySettings().model_dump(), "ended_monotonic_s": 40}
    store.insert_record("runs", "t1", {}, config_hash="fixture")
    repo.save_collector(collector)
    records = [snapshot(t) for t in range(41)]
    for point in records:
        point["active_flows"] = [{"traffic_run_id": "r1", "source_host": "h1", "target_host": "h3", "protocol": "udp", "offered_bps": 2000000}]
    records += [interval(t, 250000, 1, 100, 0, 1) | {"run_id": "t1", "at_utc": BASE.isoformat(), "traffic_run_id": "r1"} for t in range(40)]
    for record in records:
        repo.ingest(record)
    windows = aggregate_windows(records, collector, TelemetrySettings(), 40, final=True)
    repo.save_windows(windows, [{"synthetic": True}] * len(windows))
    episode = schedule.episodes[0]
    receipt, traffic = fixture_receipt(episode.scenario)
    store.save_scenario_result(receipt)
    attempt = {"attempt_id": "a1", "batch_id": batch["batch_id"], "episode_id": episode.episode_id,
        "state": "running", "application_verified": True, "restoration_verified": True,
        "collector_run_id": "t1", "main_traffic": traffic, "main_reset_receipt": receipt,
        "raw_path": str(repo.directory / "t1.jsonl"), "raw_sha256": hashlib.sha256((repo.directory / "t1.jsonl").read_bytes()).hexdigest()}
    runner.repository.save_attempt(attempt)
    runner.repository.accept(attempt, episode, windows[1:3])
    runner.repository.accept(attempt, episode, windows[1:3])
    assert len(runner.repository.members(batch["batch_id"])) == 2
    with pytest.raises(ValueError, match="cross-partition"):
        runner.repository.accept(attempt, episode.model_copy(update={"partition": "test"}), windows[1:3])
    result = export_dataset(store, batch["batch_id"])
    assert result["quality"]["structural_checks_passed"], result["quality"]["errors"]
    assert result["quality"]["accepted_windows"] == 2
    assert not result["quality"]["dataset_ready"]
    header = (tmp_path / "datasets" / batch["batch_id"] / "features.csv").read_text().splitlines()[0].split(",")
    assert set(header) == FEATURES | {"window_id"}
    assert not {"label", "partition", "seed", "episode_id"} & set(header)
    with store.connection() as db:
        bad = deepcopy(windows[1])
        bad["features"]["rtt_mean_ms"] = 999
        db.execute("UPDATE telemetry_windows SET payload_json=? WHERE window_id=?", (json.dumps(bad), bad["window_id"]))
    assert not export_dataset(store, batch["batch_id"])["quality"]["structural_checks_passed"]
