"""Focused Stage 2 tests. Agent doubles here are not networking evidence."""

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from explainnet.agent import AgentClient, AgentRequest
from explainnet.agent_server import dispatch
from explainnet.api import create_app
from explainnet.config import Settings, load_settings
from explainnet.contracts import DataQuality, JobState, Measurement
from explainnet.jobs import UnsupportedJob, Worker
from explainnet.storage import Store


def settings(tmp_path: Path) -> Settings:
    return Settings(schema_version=1, data_dir=tmp_path / "data", runtime_dir=tmp_path / "run",
                    agent_socket=tmp_path / "missing.sock")


def test_invalid_configuration_and_units(tmp_path: Path):
    config = tmp_path / "bad.yaml"
    config.write_text("schema_version: 2\ndata_dir: relative\nruntime_dir: /tmp/run\nagent_socket: /tmp/a.sock\n")
    with pytest.raises(ValidationError):
        load_settings(config)
    with pytest.raises(ValidationError):
        Measurement(run_id="r1", quality=DataQuality.valid, loss_fraction=1.01)
    with pytest.raises(ValidationError):
        Measurement(run_id="r1", quality=DataQuality.valid, rtt_ms=-1)
    measurement = Measurement(run_id="r1", quality=DataQuality.partial)
    assert measurement.rtt_ms is None and measurement.loss_fraction is None


def test_storage_persists_and_ground_truth_is_separate(tmp_path: Path):
    path = tmp_path / "db.sqlite3"
    store = Store(path)
    assert not store.healthy()
    store.initialize()
    store.initialize()
    store.insert_record("runs", "r1", {"kind": "lab"}, config_hash="a" * 64)
    store.insert_record("ground_truth", "r1", {"fault_label": "loss"})
    store.insert_record("incidents", "i1", {"status": "open"}, run_id="r1")
    store.insert_record("snapshots", "s1", {"fidelity": None}, run_id="r1",
                        config_hash="a" * 64, snapshot_hash="b" * 64)
    store.insert_record("candidates", "c1", {"score": None}, snapshot_id="s1")
    store.insert_record("actions", "a1", {"approved": False}, incident_id="i1", snapshot_id="s1")
    store.audit("test", "created", {"record": "r1"}, subject_id="r1")
    again = Store(path)
    assert again.healthy()
    assert again.get_record("runs", "r1")["payload"] == {"kind": "lab"}
    assert "fault_label" not in again.get_record("runs", "r1")["payload"]
    assert again.get_record("ground_truth", "r1")["payload"]["fault_label"] == "loss"
    assert again.get_record("candidates", "c1")["snapshot_id"] == "s1"
    assert again.get_record("actions", "a1")["incident_id"] == "i1"
    assert len(again.list_audit()) == 1
    with pytest.raises(sqlite3.IntegrityError):
        again.insert_record("incidents", "i2", {}, run_id="missing")


def test_job_transitions_restart_and_actual_handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    agent = AgentClient(tmp_path / "missing.sock")

    # Isolated agent double: verifies worker logic without claiming packet checks.
    monkeypatch.setattr(agent, "health", lambda: {"status": "available"})
    worker = Worker(store, agent, poll_s=0.01)
    with pytest.raises(UnsupportedJob):
        worker.submit("repair", "req")
    canceled = worker.submit("environment_check", "req")
    assert store.cancel_job(canceled)
    interrupted = worker.submit("environment_check", "req")
    assert store.next_queued()["id"] == interrupted
    assert store.next_queued() is None
    worker.start()
    assert store.get_job(interrupted)["state"] == JobState.interrupted
    job_id = worker.submit("environment_check", "req")
    deadline = time.monotonic() + 3
    while store.get_job(job_id)["state"] not in {JobState.succeeded, JobState.failed} and time.monotonic() < deadline:
        time.sleep(0.01)
    result = store.get_job(job_id)
    assert result["state"] == JobState.succeeded
    assert result["result"]["status"] == "healthy"
    assert result["elapsed_ms"] >= 0
    assert not store.finish_job(job_id, JobState.succeeded, 0, result={})
    def fail_check():
        raise RuntimeError("controlled test failure")

    worker.handlers["environment_check"] = fail_check
    failed_id = worker.submit("environment_check", "req")
    deadline = time.monotonic() + 3
    while store.get_job(failed_id)["state"] not in {JobState.succeeded, JobState.failed} and time.monotonic() < deadline:
        time.sleep(0.01)
    assert store.get_job(failed_id)["state"] == JobState.failed
    assert "controlled test failure" in store.get_job(failed_id)["error"]
    assert worker.stop()
    assert store.get_job(canceled)["state"] == JobState.canceled


def test_agent_protocol_validation(monkeypatch: pytest.MonkeyPatch):
    # Isolated command double: validates protocol only, not actual OVS health.
    monkeypatch.setattr("explainnet.agent_server.checked", lambda *args: "ok")
    valid = AgentRequest(operation="health").model_dump()
    assert dispatch(valid)["status"] == "available"
    with pytest.raises(ValueError, match="unsupported"):
        dispatch(valid | {"operation": "shell"})
    with pytest.raises(ValueError, match="unsupported"):
        dispatch(valid | {"operation": []})
    with pytest.raises(ValueError, match="fields"):
        dispatch(valid | {"command": "id"})


def test_api_jobs_errors_and_dependency_reporting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = settings(tmp_path)
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get("/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
        assert response.headers["x-request-id"]
        response = client.post("/v1/jobs/environment-check")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_unavailable"
        assert response.json()["error"]["incident_id"]
    Store(config.database_path).initialize()
    # Isolated agent double: real agent lifecycle is verified separately.
    monkeypatch.setattr(AgentClient, "health", lambda self: {"status": "available"})
    app = create_app(config)
    with TestClient(app) as client:
        assert client.get("/v1/health").json()["status"] == "healthy"
        assert client.get("/v1/config").json()["config_hash"] == config.config_hash
        assert client.post("/v1/jobs/repair").status_code == 501
        assert client.get("/v1/jobs/missing").status_code == 404
        response = client.post("/v1/jobs/environment-check", headers={"x-request-id": "test-request"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = client.get(f"/v1/jobs/{job_id}").json()
            if job["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert job["state"] == "succeeded"
        assert job["request_id"] == "test-request"
    assert not app.state.worker._thread.is_alive()


def test_agent_missing_is_degraded(tmp_path: Path):
    config = settings(tmp_path)
    Store(config.database_path).initialize()
    with TestClient(create_app(config)) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert client.get("/v1/capabilities").json()["agent"] is None
        assert client.get("/v1/agent/inventory").status_code == 503
