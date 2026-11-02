"""API/job fixtures are software verification only, never packet fidelity evidence."""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.storage import Store
from explainnet.twin_service import TwinCanceled, TwinService

ROOT = Path(__file__).resolve().parents[1]


def test_twin_jobs_prompt_validation_and_worker_survives_cancellation(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run',
        agent_socket=tmp_path / 'none.sock', topology_file=ROOT / 'config/topology.yaml')
    Store(settings.database_path).initialize()
    monkeypatch.setattr(TwinService, 'snapshot', lambda _self, request: {'snapshot_id': 'snUnit', 'key': request.request_key})
    def cancel_measure(_self, _request):
        raise TwinCanceled('unit canceled; no packets executed')
    monkeypatch.setattr(TwinService, 'measure', cancel_measure)
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/twins/construct', json={'twin_id': '../../original', 'snapshot_id': 'snUnit'}).status_code == 422
        assert client.post('/v1/twins/calibrate', json={'twin_id': 'twUnit', 'operation_id': 'calUnit', 'max_trials': 4}).status_code == 422
        began = time.monotonic()
        submission = client.post('/v1/twins/snapshot', json={'instance_id': 'original', 'request_key': 'unitKey',
            'baseline': {}, 'policy': {}})
        assert submission.status_code == 202 and time.monotonic() - began < 1
        def await_job(job_id):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                record = client.get('/v1/jobs/' + job_id).json()
                if record['state'] in {'succeeded', 'failed', 'canceled'}:
                    return record
                time.sleep(.01)
            raise TimeoutError('fixture job did not finish')
        assert await_job(submission.json()['job_id'])['result']['snapshot_id'] == 'snUnit'
        canceled = client.post('/v1/twins/measure', json={'twin_id': 'twUnit', 'trial_id': 'trialUnit'}).json()
        assert await_job(canceled['job_id'])['state'] == 'canceled'
        following = client.post('/v1/jobs/environment-check').json()
        assert await_job(following['job_id'])['state'] == 'succeeded'
        assert client.get('/v1/health').json()['worker_live']
