"""HTTP/job doubles for planning and lock behavior; no measured network data."""

import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from explainnet.agent import AgentClient
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.dataset_contracts import make_schedule
from explainnet.storage import Store


def test_plan_jobs_status_cancel_and_locked_mutations(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / "data", runtime_dir=tmp_path / "run",
        agent_socket=tmp_path / "agent.sock", topology_file=Path(__file__).resolve().parents[1] / "config/topology.yaml")
    Store(settings.database_path).initialize()
    monkeypatch.setattr(AgentClient, "inventory", lambda _: {"instances": []})
    monkeypatch.setattr(AgentClient, "capabilities", lambda _: {"explicit_unit_double": True})
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/v1/datasets/bad!id").status_code == 422
        assert client.get("/v1/datasets/missing").status_code == 404
        def job(path, payload):
            started = time.monotonic()
            response = client.post(path, json=payload)
            assert response.status_code == 202
            assert time.monotonic() - started < 1
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = client.get("/v1/jobs/" + response.json()["job_id"]).json()
                if result["state"] in {"succeeded", "failed"}:
                    assert result["state"] == "succeeded", result
                    return result["result"]
                time.sleep(0.01)
            raise AssertionError("bounded fixture job deadline")
        planned = job("/v1/datasets/plan", {"schedule": make_schedule("pilot").model_dump()})
        batch_id = planned["batch_id"]
        assert client.get("/v1/datasets/" + batch_id).json()["batch"]["state"] == "planned"
        assert job("/v1/datasets/cancel", {"batch_id": batch_id})["batch"]["state"] == "canceled"
        app.state.worker.dataset.thread = SimpleNamespace(is_alive=lambda: True)
        try:
            response = client.post("/v1/telemetry/reference", json={"window_id": "missing"})
            assert response.status_code == 409 and response.json()["error"]["code"] == "experiment_locked"
        finally:
            app.state.worker.dataset.thread = None
