"""One bounded healthy/latency/refusal rehearsal, only after the host is free."""
import argparse
import fcntl
import json
from pathlib import Path

from completion_stage2 import Verification

from explainnet.application_profiles import PROFILES, ROOT
from explainnet.completion_client import CompletionClient
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage4'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',choices=['fresh','contract_verified'],default='fresh')
    args=parser.parse_args()
    api=CompletionClient(PROFILES['trained'][0],OUT/'rehearsal_jobs')
    host=api.get('/v1/demo/host-status')
    if host['active']:
        atomic_json(OUT/'rehearsal.json',{'status':'blocked','at_utc':utc_now(),'blocker':host['reason'],
            'new_native_episodes':0,'compatible_evidence':'artifacts/completion_stage2/verified: trained healthy refusal, latency success with two repairs/four C0 controls/two original verification windows/Undo; loss fidelity refusal',
            'resume':'.venv/bin/python scripts/rehearse_completion_stage4.py'})
        print(host['reason']);return
    plan=OUT/'rehearsal_plan.json'
    if not plan.exists():atomic_json(plan,{'at_utc':utc_now(),'conditions':['healthy','latency','loss'],
        'independent_sources_per_condition':1,'automatic_repair':False,'observed_only_fallback':False,
        'purpose':'Bounded fresh integration acceptance, not new model training/test tuning or comparative research campaign'})
    with Path('/var/tmp/explainnet-experiment-1000.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verifier=Verification(args.run_id,output_root=OUT)
        cases=[]
        for kind in ['healthy','latency','loss']:
            path=verifier.out/('stage4_'+kind+'.json')
            if path.exists():
                case=json.loads(path.read_text())
                if not case.get('finished'):raise RuntimeError('Interrupted case requires explicit reconciliation; no replay')
            else:case=verifier.run_case('stage4_'+kind,scenario_kind=kind)
            cases.append({'condition':kind,'state':case['state'],'instance_id':case['instance_id'],
                'model_id':case['model_id'],'elapsed_ms':case['elapsed_ms'],'cleanup':case.get('cleanup'),
                'source_artifact':str(path)})
            atomic_json(OUT/'rehearsal.json',{'status':'running','at_utc':utc_now(),'cases':cases,'automatic_repair':False})
            if case.get('cleanup',{}).get('blocked'):raise RuntimeError('Cleanup unresolved; no further source started')
        api.post('/v1/lab/automation/stop',{})
        atomic_json(OUT/'rehearsal.json',{'status':'executed','at_utc':utc_now(),'cases':cases,'automatic_repair':False,
            'interpretation':'Inspect actual supported diagnosis/SHAP/fidelity/trials/verification. Terminal execution does not imply every requirement passed.'})


if __name__=='__main__':main()
