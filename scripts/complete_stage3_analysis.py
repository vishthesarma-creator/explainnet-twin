"""Gated ordinary-user stage-3 training, frozen evaluation and native analysis."""
import argparse
import fcntl
import json
import os
import time
from pathlib import Path

from explainnet.application_profiles import ROOT
from explainnet.completion_client import CompletionClient
from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.model_bundle import BundleRepository
from explainnet.model_contracts import CLASS_ORDER
from explainnet.model_dataset import load_measured_dataset
from explainnet.storage import Store, utc_now

OUT=ROOT/'artifacts/completion_stage3'


def completed_cohort(store):
    with store.connection() as db:
        row=db.execute("SELECT payload_json FROM dataset_batches WHERE json_extract(payload_json,'$.schedule.schedule_id')='c3_representative_v1'").fetchone()
        if not row:raise ValueError('New cohort has not been planned; training/test evaluation prohibited')
        batch=json.loads(row[0]);count=db.execute('SELECT count(*) FROM dataset_members WHERE batch_id=?',(batch['batch_id'],)).fetchone()[0]
    if batch['state']!='completed' or count!=3600:raise ValueError(f'New corpus incomplete: {count}/3600, state={batch["state"]}; no training/test access')
    return batch


def train(config):
    cfg=load_settings(config);store=Store(cfg.database_path);batch=completed_cohort(store)
    api=CompletionClient(config,OUT/'analysis_jobs')
    result=api.job('train_new_cohort','/v1/models/train',{'batch_id':batch['batch_id'],'profile':'completion3'},timeout=3500)
    model_id=result['bundle']['model_id'];registry=BundleRepository(store)
    started=time.monotonic();bundle=registry.load(model_id);reload_ms=(time.monotonic()-started)*1000
    if not bundle.get('training_background') or bundle['training_background']['partition']!='train':
        raise ValueError('Immutable training-derived SHAP background missing')
    api.job('activate_new_cohort','/v1/models/load',{'model_id':model_id})
    atomic_json(OUT/'model_metadata.json',{'model_id':model_id,'batch_id':batch['batch_id'],
        'manifest_sha256':result['bundle']['manifest_sha256'],'manifest':result['bundle']['manifest'],
        'validation':result['validation_report'],'verified_reload_ms':reload_ms,'at_utc':utc_now(),
        'scope':'New prospective cohort; historical model preserved in its separate store'})


def evaluate(config):
    from explainnet.completion_evaluation import evaluate_pipeline
    cfg=load_settings(config);store=Store(cfg.database_path);completed_cohort(store)
    model=json.loads((OUT/'model_metadata.json').read_text())['model_id']
    evaluate_pipeline(store,model,cfg,OUT/'protocol.json',OUT/'evaluation_config.json',OUT/'evaluation')


def backend(config):
    cfg=load_settings(config);store=Store(cfg.database_path);completed_cohort(store)
    model=json.loads((OUT/'model_metadata.json').read_text())['model_id'];registry=BundleRepository(store)
    bundle=registry.load(model)
    data=store.path.parent/'datasets'/bundle['dataset']['batch_id']
    training,_validation,_hashes=load_measured_dataset(data)
    api=CompletionClient(config,OUT/'backend_jobs');cases=[];deadline=time.monotonic()+1500
    for label in CLASS_ORDER:
        episode=min(set(training.episodes[training.y==label]))
        indices=sorted([i for i,e in enumerate(training.episodes) if e==episode],key=lambda i:training.windows[i]['start_monotonic_s'])[:2]
        for neighbor,index in enumerate(indices):
            wid=training.windows[index]['window_id'];started=time.monotonic()
            d=api.job(f'infer_{label}_{neighbor}','/v1/models/infer',{'model_id':model,'window_id':wid,'mode':'recorded'})
            inference_rpc_ms=(time.monotonic()-started)*1000
            x=api.job(f'explain_{label}_{neighbor}','/v1/explanations/request',{'model_id':model,'window_id':wid,'mode':'recorded'})
            while x['status']=='pending' and time.monotonic()<deadline:
                time.sleep(.3);x=api.get('/v1/explanations/'+x['explanation_id'])
            lineage=x.get('model_id')==model and x.get('window_id')==wid
            cases.append({'reference_class':label,'window_id':wid,'model_id':model,'mode':'recorded',
                'inference':d,'explanation':x,'inference_rpc_ms':inference_rpc_ms,'lineage_matches':lineage})
            atomic_json(OUT/'backend_checks.json',{'cases':cases,'status':'running','heldout_access':False,
                'scope':'Measured training examples verify actual backend execution/lineage only; not independent performance estimates'})
    ready=all(c['lineage_matches'] and c['explanation']['status']=='ready' for c in cases)
    atomic_json(OUT/'backend_checks.json',{'cases':cases,'status':'passed' if ready else 'incomplete',
        'heldout_access':False,'model_id':model,'at_utc':utc_now(),
        'scope':'Actual API inference/async SHAP on measured training observations; heldout scores are the separately frozen offline evaluation. Fresh native cases exercise live paths.'})


def labs(config):
    from completion_stage3_labs import run
    cfg=load_settings(config);completed_cohort(Store(cfg.database_path))
    with Path('/var/tmp/explainnet-experiment-1000.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(config)


def report(_config):
    from report_completion_stage3 import create_report
    create_report()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['train','evaluate','backend','labs','report']);parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()==0:raise ValueError('Model/application phases must run as the ordinary application user')
    from report_completion_stage3 import write_handover
    from status_completion_stage3 import record
    write_handover(record())
    globals()[args.phase](args.config)


if __name__=='__main__':main()
