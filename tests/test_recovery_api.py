"""Job validation/cancellation/retrieval wiring; no native network evidence."""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from explainnet.api import create_app
from explainnet.config import Settings
from explainnet.recovery_service import RecoveryService
from explainnet.storage import Store
from explainnet.twin_service import TwinCanceled

ROOT = Path(__file__).resolve().parents[1]


def test_bounded_recovery_jobs_cancel_and_retrieval(tmp_path, monkeypatch):
    settings = Settings(schema_version=1, data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'run',
        agent_socket=tmp_path / 'none.sock', topology_file=ROOT / 'config/topology.yaml')
    Store(settings.database_path).initialize()
    monkeypatch.setattr(RecoveryService, 'plan', lambda _self, req: {'operation_id': req.operation_id, 'candidates': []})
    monkeypatch.setattr(RecoveryService, 'get', lambda _self, operation_id: {'operation_id': operation_id, 'state': 'uncertain'})
    monkeypatch.setattr(RecoveryService, 'cancel', lambda _self, operation_id: {'operation_id': operation_id, 'cancel_requested': True})
    def canceled(*_):
        raise TwinCanceled('fixture cancellation; no native packets')
    monkeypatch.setattr(RecoveryService, 'test', canceled)
    body = {'twin_id': 'twUnit', 'snapshot_id': 'snUnit', 'operation_id': 'opUnit'}
    with TestClient(create_app(settings)) as client:
        for extra in ({'repetitions': 1}, {'max_repairs': 4}, {'timeout_s': 701}, {'instance_id': 'original'}):
            assert client.post('/v1/recovery/test', json=body | extra).status_code == 422
        start = time.monotonic()
        submitted = client.post('/v1/recovery/plan', json=body)
        assert submitted.status_code == 202 and time.monotonic() - start < 1
        def await_job(job_id):
            until = time.monotonic() + 5
            while time.monotonic() < until:
                result = client.get('/v1/jobs/' + job_id).json()
                if result['state'] in {'succeeded', 'failed', 'canceled'}:
                    return result
                time.sleep(.01)
            raise TimeoutError('fixture worker did not finish')
        assert await_job(submitted.json()['job_id'])['state'] == 'succeeded'
        tested = client.post('/v1/recovery/test', json=body).json()
        assert await_job(tested['job_id'])['state'] == 'canceled'
        assert client.post('/v1/recovery/cancel', json={'operation_id': 'opUnit'}).json()['cancel_requested']
        assert client.get('/v1/recovery/opUnit').json()['state'] == 'uncertain'
        subsequent = client.post('/v1/jobs/environment-check').json()
        assert await_job(subsequent['job_id'])['state'] == 'succeeded'
