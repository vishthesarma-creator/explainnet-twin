"""Preserve historical qualification metadata without pooling incompatible trials."""
import hashlib
import json
from pathlib import Path

from explainnet.dataset_export import atomic_json

ROOT=Path(__file__).resolve().parents[1]
out={}
for name in ('twin','candidate','recovery','dashboard'):
    path=ROOT/'artifacts'/(name+'_validation_report.json')
    value=json.loads(path.read_text())
    chosen={k:value[k] for k in ('status','limitations','blockers','measured_performance_readiness') if k in value}
    for section in ('summary','per_fault'):
        if isinstance(value.get(section),dict):
            chosen[section]={key:{field:entry.get(field) for field in
                ('status','state','historical_state','trial_count','trial_statuses','control_states','condition','reason','original_repair_attempted') if field in entry}
                for key,entry in value[section].items() if isinstance(entry,dict)}
    if 'cases' in value:
        chosen['cases']={k:{field:v.get(field) for field in ('state','status','error','reasons') if field in v}
            for k,v in value['cases'].items() if isinstance(v,dict)}
    out[name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'top_level_fields':list(value),'evidence':chosen,
        'pooling':'Historical only; not pooled with current Stage 13 trials without matching provenance/protocol'}
atomic_json(ROOT/'artifacts/stage13/historical_qualification.json',out)
print(json.dumps({name:{'status':r['evidence'].get('status'),'summary':r['evidence'].get('summary'),
    'per_fault':r['evidence'].get('per_fault')} for name,r in out.items()},indent=2))
