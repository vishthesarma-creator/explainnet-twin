"""Focused validation/storage/restoration doubles; these do not prove packet effects."""

import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from explainnet.agent import AgentRequest
from explainnet.network_runtime import NetworkManager
from explainnet.scenario_contracts import Scenario
from explainnet.scenario_runtime import ScenarioEngine
from explainnet.scenario_spec import loss_percent, recipe
from explainnet.storage import Store


@pytest.mark.parametrize("kind,profile", [("healthy", "moderate"), ("saturation", "shared"),
    ("loss", "moderate"), ("latency", "moderate"), ("qos", "qos_competing")])
def test_versioned_recipes_and_workload_bounds(kind, profile):
    for severity in ("low", "medium", "high"):
        s = Scenario(kind=kind, severity=severity, traffic_profile=profile).model_dump()
        parameters = recipe(s)
        profiles = ScenarioEngine.profiles(s, parameters)
        assert all(1000 <= p["offered_bps"] <= 100_000_000 and p["duration_s"] <= 25 for p in profiles)
        if kind == "saturation":
            assert sum(p["offered_bps"] for p in profiles) > 100_000_000
        if kind in {"latency", "loss"}:
            assert sum(p["offered_bps"] for p in profiles) < 20_000_000


@pytest.mark.parametrize("change", [{"schema_version": 2}, {"warmup_s": 0}, {"measurement_s": 99},
    {"bidirectional": True}, {"variation_ms": 4}, {"high_utilization": True}, {"kind": "repair"},
    {"kind": "loss", "traffic_profile": "qos_competing"}, {"measurement_s": True}])
def test_compound_and_out_of_bounds_requests_rejected(change):
    with pytest.raises(ValidationError):
        Scenario.model_validate(Scenario(kind="healthy").model_dump() | change)


def test_fraction_conversion_and_restricted_protocol():
    assert loss_percent(0.03) == "3.000000%"
    assert loss_percent(0.15) == "15.000000%"
    for invalid in (-0.1, 15, True):
        with pytest.raises(ValueError):
            loss_percent(invalid)
    with pytest.raises(ValidationError):
        AgentRequest(operation="scenario_start", parameters={"schema_version": 1, "instance_id": "lab1",
            "scenario": Scenario(kind="healthy").model_dump() | {"command": "tc anything"}})


def test_partial_restore_is_explicit_retryable_and_stops_only_owned_runs(tmp_path, monkeypatch):
    before = {"s2->s3": {"qdisc_raw": "base", "class_raw": "fixed100M", "filters": ""}}
    journal = {"state": "active", "owned_runs": ["r_owned"], "qos_modified": False,
        "modified_directions": [["s2", "s3"]], "before": deepcopy(before), "deactivated_utc": None}
    live = {"record": {"scenario": journal}}
    stopped = []
    manager = SimpleNamespace(lock=threading.RLock(), state_dir=tmp_path, _running=lambda _: live,
        _save=lambda _: None, traffic_stop=lambda instance, run: stopped.append(run),
        probe=lambda *args: {"passed": True})
    (tmp_path / "runs/r_owned").mkdir(parents=True)
    engine = ScenarioEngine(manager)
    monkeypatch.setattr(engine, "_port", lambda *args: "owned-interface")
    monkeypatch.setattr(engine, "_base", lambda *args: (100_000_000, 1))
    monkeypatch.setattr(engine, "_netem", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "evidence", lambda _: {"s2->s3": {"qdisc_raw": "still_faulty",
        "class_raw": "fixed100M", "filters": ""}})
    monkeypatch.setattr(engine, "inspect", lambda _: {"state": journal["state"]})
    with pytest.raises(RuntimeError, match="partial scenario restore"):
        engine.reset("lab1")
    assert journal["state"] == "restore_failed" and journal["deactivated_utc"] is None
    monkeypatch.setattr(engine, "evidence", lambda _: before)
    assert engine.reset("lab1")["state"] == "stopped"
    assert stopped == ["r_owned", "r_owned"]
    assert journal["deactivated_utc"] is not None
    assert engine.reset("lab1")["state"] == "stopped"
    assert len(stopped) == 2


def test_ground_truth_is_separate_and_deactivation_updates(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    store.initialize()
    observed = {"run_id": "r1", "created_utc": "2026-10-07T00:00:00+00:00", "config_hash": "hash",
        "state": "running", "profiles": []}
    journal = {"configuration": Scenario(kind="loss").model_dump(), "parameters": {"loss_fraction": 0.08},
        "activated_utc": "2026-10-07T00:00:00+00:00", "deactivated_utc": None, "state": "active"}
    result = {"laboratory_journal": journal, "traffic_runs": [observed]}
    store.save_scenario_result(result)
    with store.connection() as db:
        assert json.loads(db.execute("SELECT payload_json FROM runs").fetchone()[0]) == observed
        assert json.loads(db.execute("SELECT payload_json FROM ground_truth").fetchone()[0])["fault_label"] == "loss"
    journal.update(state="stopped", deactivated_utc="2026-10-07T00:00:12+00:00")
    store.save_scenario_result(result)
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT payload_json FROM ground_truth").fetchone()[0])["deactivated_utc"]


def test_native_iperf_error_json_is_failed_even_with_zero_exit_code(tmp_path):
    """Process/file doubles reproduce iperf's observed zero-exit structured error case."""
    output, stderr = tmp_path / "native.json", tmp_path / "native.stderr"
    output.write_text(json.dumps({"end": {}, "error": "controlled iperf failure"}))
    stderr.write_text("")
    item = {}
    process = SimpleNamespace(poll=lambda: 0, returncode=0, pid=7)
    session = {"instance_id": "lab1", "processes": [{"proc": process, "item": item, "side": "client",
        "path": output, "stderr_path": stderr}], "files": [], "run": {"run_id": "r1"},
        "started": time.monotonic()}
    manager = SimpleNamespace(sessions={"r1": session}, records={"lab1": {"traffic_processes": [{"pid": 7}]}},
        _write_run=lambda _: None, _save=lambda _: None)
    run = NetworkManager._finish_run(manager, "r1")
    assert run["state"] == "failed"
    assert item["client_json"]["error"] == "controlled iperf failure"
    assert not manager.sessions and not manager.records["lab1"]["traffic_processes"]
