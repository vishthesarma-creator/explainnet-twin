import hashlib
import json
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store

s = load_settings(Path('artifacts/stage6/runtime/config.json'))
b = DatasetRepository(Store(s.database_path)).batch('db5a15991774142f0a8ef871522face4d')
print(json.dumps({'stored':b['config_hash'],'current':s.config_hash,
    'without_later_test_hooks':hashlib.sha256(s.model_dump_json(exclude={'lab_test_hooks'}).encode()).hexdigest(),
    'same_definition':b['definition']==__import__('explainnet.config',fromlist=['load_network']).load_network(s.topology_file).model_dump(),
    'settings':s.model_dump(mode='json')},indent=2))
