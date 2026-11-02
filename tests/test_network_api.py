"""Stage 3 API/persistence tests using clearly isolated agent doubles."""

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from explainnet.agent import AgentClient
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.storage import MIGRATIONS, Store
from explainnet.topology.spec import definition_hash

ROOT = Path(__file__).resolve().parents[1]


def test_schema_two_migration_preserves_stage_two_records(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_utc TEXT NOT NULL);" + MIGRATIONS[0])
        db.execute("INSERT INTO schema_migrations VALUES(1,'2026-10-06T00:00:00+00:00')")
        db.execute("INSERT INTO runs VALUES('r1','2026-10-06T00:00:00+00:00','hash','{}')")
        db.execute("INSERT INTO jobs(id,type,state,created_utc,request_id) VALUES('j1','environment_check','succeeded','now','request')")
    store = Store(path)
    assert not store.healthy()
    store.initialize()
    assert store.healthy()
    assert store.get_record("runs", "r1")["config_hash"] == "hash"
    assert store.get_job("j1")["state"] == "succeeded"
    assert store.get_job("j1")["payload"] == {}


def test_network_submission_validation_and_persistence(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / "data", runtime_dir=tmp_path / "run",
                        agent_socket=tmp_path / "missing.sock", topology_file=ROOT / "config" / "topology.yaml",
                        traffic_profiles_file=ROOT / "config" / "traffic.yaml")
    store = Store(settings.database_path)
    store.initialize()
    # Isolated agent double: this tests job submission and persistence only.
    monkeypatch.setattr(AgentClient, "network_start", lambda self, req: {
        "instance_id": req.instance_id, "state": "running", "live_verified": True,
        "config_hash": definition_hash(req.definition.model_dump()), "config_version": req.definition.config_version,
    })
    with TestClient(create_app(settings)) as client:
        invalid = client.post("/v1/networks/start", json={"instance_id": "../../elsewhere"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_request"
        invalid = client.post("/v1/traffic/start", json={"instance_id": "lab1", "profile_ids": ["missing"]})
        assert invalid.status_code == 422
        invalid = client.post("/v1/traffic/start", json={"instance_id": "lab1", "profile_ids": ["bulk"], "packet_size": 1200})
        assert invalid.status_code == 422
        response = client.post("/v1/networks/start", json={"instance_id": "lab1"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = client.get("/v1/jobs/" + job_id).json()
            if job["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert job["state"] == "succeeded"
        assert Store(settings.database_path).list_instances()[0]["config_version"] == "pilot_v1"
        assert client.post("/v1/jobs/repair").status_code == 501
