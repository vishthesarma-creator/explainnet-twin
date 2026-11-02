"""Read actual completed trained evidence with the dashboard client; no mutations."""
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx

from explainnet.dashboard.client import ApiClient, ClientSettings
from explainnet.response_evidence import encoded
from explainnet.storage import utc_now

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = json.loads((ROOT/'artifacts/completion_stage2/verified/latency.json').read_text())
    wid, eid = source['workflow_id'], source['workflow']['experiment_id']
    db = sqlite3.connect('file:/home/USER/.local/share/explainnet/stage13/data/explainnet.sqlite3?mode=ro',uri=True)
    def hashes():
        return [hashlib.sha256(db.execute(query,(key,)).fetchone()[0].encode()).hexdigest() for query,key in [
            ('SELECT payload_json FROM recovery_workflows WHERE workflow_id=?',wid),
            ('SELECT payload_json FROM recovery_experiments WHERE operation_id=?',eid)]]
    before = hashes()
    client = ApiClient(ClientSettings(api_url='http://127.0.0.1:38223',timeout_s=30))
    rows = []
    for route in ['/v1/lab/workflows/'+wid, '/v1/recovery/'+eid]:
        wire = httpx.get(client.settings.api_url+route, timeout=30,trust_env=False).json()
        value = client.get(route)
        trials = value.get('trials',value.get('candidate_result',{}).get('trials'))
        assert isinstance(trials,list) and len(trials)==12
        assert len({t['candidate_id'] for t in trials if t['family']!='no_change'})==2
        assert all(t['fidelity']['status']=='pass' for t in trials if t.get('fidelity'))
        rows.append({'route':route,'wire_schema':wire.get('response_schema_version',1),
            'wire_evidence_bytes':wire.get('evidence',{}).get('bytes'),'hydrated_compact_bytes':len(encoded(value)),
            'trial_count':len(trials),'repair_candidate_count':2,'historical_state':value.get('historical_state'),
            'current_projection_state':value['state'],'shape_and_integrity':'passed'})
    assert before==hashes(), 'status read changed persisted completed workflow/experiment'
    report = {'at_utc':utc_now(),'status':'passed','reads':rows,'persisted_selected_records_unchanged':True,
        'limitations':'A historical eligible experiment is correctly stale after scoped source cleanup; cannot be applied now.'}
    (ROOT/'artifacts/completion_stage2/dashboard_reads.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
