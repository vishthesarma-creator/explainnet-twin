"""Explicit offline durable training operation after collection has stopped and passed audit."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.config import load_settings
from explainnet.contracts import JobState
from explainnet.dataset_repository import DatasetRepository
from explainnet.diagnosis_service import DiagnosisService
from explainnet.storage import Store, utc_now
from explainnet.telemetry_service import TelemetryService

parser = argparse.ArgumentParser()
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--batch-id', required=True)
parser.add_argument('--profile', choices=['stage7','stage13'], default='stage7')
args = parser.parse_args()
settings = load_settings(args.config)
store = Store(settings.database_path)
batch = DatasetRepository(store).batch(args.batch_id)
if not batch or batch['state'] != 'completed':
    parser.exit(2, 'Measured dataset is incomplete/not ready; no model trained. Inspect dataset-status or resume the existing batch.\n')
store.initialize()
telemetry = TelemetryService(store, AgentClient(settings.agent_socket), settings.telemetry, settings.objective)
service = DiagnosisService(store, telemetry, settings.dataset_artifact_dir or Path('artifacts'))
job_id = 'j' + uuid4().hex
store.create_job(job_id, 'model_train', 'explicit-offline', {'batch_id': args.batch_id,'profile':args.profile})
with store.connection() as db:
    db.execute("UPDATE jobs SET state='running',started_utc=? WHERE id=? AND state='queued'", (utc_now(), job_id))
start = time.monotonic()
try:
    result = service.train(args.batch_id, profile=args.profile)
except Exception as exc:  # noqa: BLE001 - persist every explicit training-job failure
    store.finish_job(job_id, JobState.failed, (time.monotonic() - start) * 1000, error=str(exc))
    parser.exit(1, str(exc) + '\n')
store.finish_job(job_id, JobState.succeeded, (time.monotonic() - start) * 1000, result=result)
print(json.dumps({'job_id': job_id, 'model_id': result['bundle']['model_id'],
    'bundle_directory': result['bundle']['directory'], 'validation': result['validation_report']['validation']}, indent=2))
