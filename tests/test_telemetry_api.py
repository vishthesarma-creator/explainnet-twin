"""Lifecycle/HTTP doubles; no synthetic observations are claimed as packet evidence."""

import time

from fastapi.testclient import TestClient

from explainnet.agent import AgentClient, AgentUnavailable
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.storage import Store


def test_collector_jobs_idempotence_errors_and_stale_history(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / "data", runtime_dir=tmp_path / "run",
        agent_socket=tmp_path / "agent.sock")
    store = Store(settings.database_path)
    store.initialize()
    monkeypatch.setattr(AgentClient, "inventory", lambda _: {"instances": []})
    monkeypatch.setattr(AgentClient, "network_inspect", lambda _, req: {"state": "running", "live_verified": True})
    def unavailable(*args):
        raise AgentUnavailable("controlled observation timeout")
    monkeypatch.setattr(AgentClient, "telemetry_observe", unavailable)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/telemetry/bad!instance/status").status_code == 422
        assert client.get("/v1/telemetry/lab1/windows?limit=99999").status_code == 422
        assert client.post("/v1/telemetry/start", json={"instance_id": "lab1", "duration_s": 1}).status_code == 422
        def job(path, payload):
            before = time.monotonic()
            response = client.post(path, json=payload)
            assert response.status_code == 202
            assert time.monotonic() - before < 1
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                record = client.get("/v1/jobs/" + response.json()["job_id"]).json()
                if record["state"] in {"succeeded", "failed"}:
                    assert record["state"] == "succeeded", record
                    return record["result"]
                time.sleep(0.01)
            raise AssertionError("collector job timeout")
        first = job("/v1/telemetry/start", {"instance_id": "lab1", "duration_s": 25})
        repeated = job("/v1/telemetry/start", {"instance_id": "lab1", "duration_s": 25})
        assert first["session"]["run_id"] == repeated["session"]["run_id"]
        ended = job("/v1/telemetry/stop", {"instance_id": "lab1"})
        assert ended["status"] == "stale" and not ended["live"]
        assert ended["session"]["errors"][0]["message"] == "controlled observation timeout"
        assert not client.get("/v1/telemetry/lab1/windows?ready_only=true").json()["windows"]
        assert client.get("/v1/telemetry/lab1/alerts").json()["latest"]["status"] == "stale"
