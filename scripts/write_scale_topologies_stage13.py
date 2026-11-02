"""Save deterministic validated scale templates; no network operations."""
import json
from pathlib import Path

from explainnet.config import load_network
from explainnet.dataset_export import atomic_json
from explainnet.topology.spec import definition_hash, scale_definition

ROOT=Path(__file__).resolve().parents[1]
base=load_network(ROOT/'config/topology.yaml').model_dump()
directory=ROOT/'config/topologies'; directory.mkdir(exist_ok=True)
records=[]
for size in (5,10,15):
    definition=scale_definition(base,size)
    path=directory/('scale_'+str(size)+'_v1.json')
    atomic_json(path,definition)
    records.append({'switches':size,'hosts':len(definition['hosts']),'links':len(definition['links']),
        'definition_hash':definition_hash(definition),'template':str(path.relative_to(ROOT))})
atomic_json(ROOT/'artifacts/stage13/topology_manifest.json',{'topologies':records,'execution':'Templates only; actual packet results are separate'})
print(json.dumps(records,indent=2))
