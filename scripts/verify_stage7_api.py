"""Real read-only HTTP checks and training refusal; no measured model-quality claims."""
import json
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

config = json.loads(Path('artifacts/stage6/runtime/config.json').read_text())
base = f"http://127.0.0.1:{config['port']}"

def request(path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)

code, status = request('/v1/models')
assert code == 200 and status['active_model_id'] is None and not status['bundles']
code, missing = request('/v1/models/missing')
assert code == 404
code, refusal = request('/v1/models/train', {'batch_id': 'db5a15991774142f0a8ef871522face4d'})
assert code == 409 and refusal['error']['code'] == 'experiment_locked'
code, repair = request('/v1/jobs/repair', {})
assert code == 501
report = {'schema_version': 1, 'at_utc': utc_now(), 'kind': 'real HTTP process integration, not model validation',
    'model_status': status, 'unknown_bundle_http': 404, 'training_during_collection_http': 409,
    'training_refusal': refusal, 'repair_unsupported_http': 501, 'trained_models': 0, 'network_mutations': 0}
atomic_json(Path('artifacts/stage7/api_verification.json'), report)
print(json.dumps(report, indent=2))
