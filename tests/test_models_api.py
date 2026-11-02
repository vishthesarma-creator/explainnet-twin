"""HTTP and job integration doubles, separate from measured model validation."""
import sqlite3
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from explainnet.agent import AgentClient
from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.jobs import Worker
from explainnet.storage import Store


def test_explicit_model_jobs_validation_and_no_startup_training(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run', agent_socket=tmp_path / 'agent.sock')
    store = Store(settings.database_path)
    store.initialize()
    monkeypatch.setattr(AgentClient, 'inventory', lambda _: {'instances': []})
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get('/v1/models').json()['active_model_id'] is None
        assert client.get('/v1/models/missing').status_code == 404
        assert client.post('/v1/models/train', json={'batch_id': '../unsafe'}).status_code == 422
        assert client.post('/v1/models/infer', json={'model_id': 'munit', 'window_id': 'wunit', 'mode': 'fake'}).status_code == 422
        assert client.post('/v1/jobs/repair').status_code == 501
        response = client.post('/v1/models/train', json={'batch_id': 'dnotready'})
        assert response.status_code == 202
        job_id = response.json()['job_id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/v1/jobs/' + job_id).json()
            if job['state'] in {'failed', 'succeeded'}:
                break
            time.sleep(.01)
        assert job['state'] == 'failed' and 'not ready' in job['error']
        worker = app.state.worker
        calls = []
        monkeypatch.setattr(worker.diagnosis, 'activate', lambda model_id: calls.append(model_id) or {'active_model_id': model_id})
        response = client.post('/v1/models/load', json={'model_id': 'munit'})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/v1/jobs/' + response.json()['job_id']).json()
            if job['state'] in {'failed','succeeded'}:
                break
            time.sleep(.01)
        assert job['state'] == 'succeeded' and calls == ['munit']
        worker.dataset.thread = SimpleNamespace(is_alive=lambda: True)
        try:
            assert client.post('/v1/models/train', json={'batch_id': 'dbusy'}).status_code == 409
            assert client.get('/v1/models').status_code == 200
        finally:
            worker.dataset.thread = None
        assert client.get('/v1/diagnoses/wunit').json()['records'] == []
    assert not app.state.worker.diagnosis.thread.is_alive()


def test_application_import_is_lightweight():
    # Fresh interpreter is necessary: other tests deliberately import sklearn.
    import subprocess
    result = subprocess.run([sys.executable, '-c',
        "import explainnet.api, sys; assert 'sklearn' not in sys.modules; assert 'numpy' not in sys.modules"],
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_transient_sqlite_poll_lock_does_not_kill_worker(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db.sqlite3')
    store.initialize()
    original = store.next_queued
    seen = []
    def poll():
        if not seen:
            seen.append('locked once')
            raise sqlite3.OperationalError('database is locked')
        return original()
    monkeypatch.setattr(store, 'next_queued', poll)
    agent = SimpleNamespace(inventory=lambda: {'instances': []})
    worker = Worker(store, agent, poll_s=.01)
    worker.handlers['unit_check'] = lambda _: {'passed': True}
    worker.start()
    try:
        job_id = worker.submit('unit_check', 'unit')
        deadline = time.monotonic() + 5
        while store.get_job(job_id)['state'] not in {'succeeded','failed'} and time.monotonic() < deadline:
            time.sleep(.01)
        assert store.get_job(job_id)['state'] == 'succeeded' and worker._thread.is_alive()
    finally:
        worker.stop()
