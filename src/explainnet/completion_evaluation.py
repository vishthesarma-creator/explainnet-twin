"""Prospective stage-3 frozen evaluation, post-hoc SHAP and no-XAI measurements."""
import csv
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.evaluation import episode_bootstrap, evaluate_test, freeze
from explainnet.explanation_engine import RFExplainer
from explainnet.model_bundle import BundleRepository
from explainnet.model_contracts import CLASS_ORDER
from explainnet.model_policy import infer
from explainnet.storage import utc_now


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_pipeline(store,model_id,protocol_path,configuration,output):
    output.mkdir(exist_ok=True,parents=True)
    root=Path(__file__).resolve().parents[2]
    protocol=json.loads(protocol_path.read_text())
    if digest({k:v for k,v in protocol.items() if k!='protocol_hash'})!=protocol['protocol_hash']:
        raise ValueError('Prospective protocol integrity mismatch')
    registry=BundleRepository(store);record=registry.inspect(model_id);bundle=registry.load(model_id)
    if bundle['training_profile']!='completion3' or not bundle.get('training_background'):
        raise ValueError('New frozen trained pipeline/background required; no legacy/observed-only substitution')
    if bundle['dataset'].get('protocol_hash')!=protocol['protocol_hash']:
        raise ValueError('Immutable model is not bound to the prospective protocol')
    # Include transitive project dependencies, not just the evaluator's imports.
    sources=sorted((root/'src/explainnet').rglob('*.py'))
    sources += [root/'scripts'/name for name in ['complete_stage3_analysis.py','completion_stage3_labs.py','completion_stage2.py']]
    cohort=protocol_path.parent
    measured_config=cohort/'runtime/config.json'
    native_plan=cohort/'labs/plan.json'
    if not native_plan.exists():raise ValueError('Concrete native comparison plan must be declared before test access')
    if json.loads(native_plan.read_text())['protocol_hash']!=protocol['protocol_hash']:raise ValueError('Native plan protocol mismatch')
    value={'model_id':model_id,'model_manifest_sha256':record['manifest_sha256'],
        'dataset_manifest_sha256':bundle['dataset']['manifest_sha256'],'protocol_sha256':sha(protocol_path),
        'protocol_hash':protocol['protocol_hash'],'background_hash':bundle['training_background']['content_hash'],
        'configuration_sha256':sha(configuration),
        'runtime_configuration_sha256':sha(measured_config),'native_plan_sha256':sha(native_plan),
        'requirements_sha256':sha(root/'requirements.txt'),
        'source_sha256':{str(p.relative_to(root)):sha(p) for p in sources}}
    path=output/'pipeline_freeze.json'
    if path.exists():
        prior=json.loads(path.read_text())
        if {k:v for k,v in prior.items() if k!='frozen_utc'}!=value:
            raise ValueError('Pipeline changed after freeze. No new confirmatory claim without a new independent holdout.')
    else:
        atomic_json(path,value|{'frozen_utc':utc_now()})
    legacy=freeze(store,model_id,configuration,output)
    return legacy,bundle


def evaluate_pipeline(store,model_id,settings,protocol_path,configuration,output):
    frozen,bundle=freeze_pipeline(store,model_id,protocol_path,configuration,output)
    result_path=output/'completion3_metrics.json'
    if result_path.exists():
        result=json.loads(result_path.read_text())
        if result['model_id']!=model_id:raise ValueError('Evaluation result model mismatch')
        return result
    access=output/'test_access.json'
    if not access.exists():atomic_json(access,{'first_opened_utc':utc_now(),'model_id':model_id,'purpose':'frozen confirmatory evaluation; no tuning permitted'})
    measured=evaluate_test(store,frozen,settings,output)
    saved=json.loads((output/'test_predictions.json').read_text())
    directory=store.path.parent/'datasets'/bundle['dataset']['batch_id']
    labels={v['window_id']:v for v in map(json.loads,(directory/'labels.jsonl').read_text().splitlines())}
    schedule=json.loads((directory/'schedule.json').read_text())
    families={e['episode_id']:e['family_id'] for e in schedule['episodes']}
    predictions=saved['predictions'];y=np.array([labels[p['window_id']]['label'] for p in predictions])
    probabilities=np.array([[(p['decision']['calibrated_probabilities'] or p['decision']['raw_probabilities'])[c] for c in CLASS_ORDER] for p in predictions])
    scores=np.array([p['decision']['anomaly_score'] for p in predictions],dtype=float)
    fault=y!='healthy';valid=np.isfinite(scores)
    auc=float(roc_auc_score(fault[valid],scores[valid])) if len(set(fault[valid]))==2 else None
    ap=float(average_precision_score(fault[valid],scores[valid])) if fault[valid].any() else None
    family_ci=episode_bootstrap(y,probabilities,[families[p['episode_id']] for p in predictions],frozen['config']['seed'],frozen['config']['bootstrap_repetitions'])
    family_ci.update(unit='whole recipe families; class-stratified',limitation='Two held-out families/class; fixed emulator/fault locations and correlated episodes limit generalization.')
    cold=time.monotonic();explainer=None;setup_error=None
    try:explainer=RFExplainer(bundle,bundle['training_background'])
    except (ValueError,RuntimeError) as exc:setup_error=str(exc)
    cold_ms=(time.monotonic()-cold)*1000
    explanations=[];no_xai=[];previous={};stability=[]
    for p in predictions:
        with store.connection() as db:
            w=json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?',(p['window_id'],)).fetchone()[0])
        started=time.monotonic()
        decision=infer(bundle,w,settings.telemetry,settings.objective,baseline=p['rule_baseline'])
        elapsed=(time.monotonic()-started)*1000
        identical=all(decision.get(k)==p['decision'].get(k) for k in ['raw_probabilities','calibrated_probabilities','predicted_class','status','anomalous','incident','reasons'])
        no_xai.append({'window_id':w['window_id'],'episode_id':p['episode_id'],'identical_prediction_and_support':identical,'inference_ms':elapsed})
        if p['decision']['predicted_class'] is None:
            explanations.append({'window_id':w['window_id'],'model_id':model_id,'status':'unsupported','reason':'no selected class'});continue
        if explainer is None:
            explanations.append({'window_id':w['window_id'],'model_id':model_id,'status':'failed','reason':setup_error});continue
        started=time.monotonic()
        try:x=explainer.explain(w,p['decision'])
        except (ValueError,RuntimeError) as exc:
            explanations.append({'window_id':w['window_id'],'model_id':model_id,'status':'failed','reason':str(exc),'elapsed_ms':(time.monotonic()-started)*1000});continue
        x.update(window_id=w['window_id'],model_id=model_id,model_manifest_hash=frozen['model_manifest_sha256'],
            background_hash=bundle['training_background']['content_hash'],mode='frozen_offline_test',elapsed_ms=(time.monotonic()-started)*1000)
        explanations.append(x)
        contributions={}
        for c in x['contributions']:contributions[c['original_feature']]=contributions.get(c['original_feature'],0)+c['contribution']
        top=set(sorted(contributions,key=lambda k:-abs(contributions[k]))[:3])
        old=previous.get(p['episode_id'])
        if old:
            stable_class=old['class']==x['explained_class']
            stability.append({'episode_id':p['episode_id'],'left_window':old['window'],'right_window':w['window_id'],
                'same_explained_class':stable_class,'top3_jaccard':len(top&old['top'])/len(top|old['top']) if stable_class else None})
        previous[p['episode_id']]={'window':w['window_id'],'top':top,'class':x['explained_class']}
    atomic_json(output/'heldout_shap.json',{'model_id':model_id,'training_background_hash':bundle['training_background']['content_hash'],
        'cases':explanations,'neighboring_window_stability':stability,'interpretation':'Raw RF contribution scale, not calibrated confidence, causality or user-study utility'})
    atomic_json(output/'no_xai.json',{'model_id':model_id,'removed_work':'Post-hoc SHAP only. Model/data/service/selection inputs fixed.',
        'cases':no_xai,'identical_cases':sum(c['identical_prediction_and_support'] for c in no_xai),'denominator':len(no_xai),
        'causal_selection_effect':'SHAP is not a selector input; no accuracy/choice difference is manufactured.',
        'actuation':'Live ablation does not remove shared original ownership/service/fidelity/rollback gates; report recommendation/twin-only if not qualified.'})
    measured.update(protocol_hash=json.loads(protocol_path.read_text())['protocol_hash'],
        families=len({families[p['episode_id']] for p in predictions}),
        family_counts_by_class={c:len({families[p['episode_id']] for i,p in enumerate(predictions) if y[i]==c}) for c in CLASS_ORDER},
        family_uncertainty=family_ci,IF_ranking={'ROC_AUC':auc,'average_precision':ap,'fault_prevalence':float(fault.mean()),
            'denominator':int(valid.sum()),'missing_scores':int((~valid).sum()),'score':'negative score_samples; larger is more anomalous'},
        no_XAI={'identical':sum(c['identical_prediction_and_support'] for c in no_xai),'denominator':len(no_xai),'post_hoc':True},
        SHAP={'ready':sum(x['status']=='ready' for x in explanations),'denominator':len(predictions),'cold_setup_ms':cold_ms,
            'max_additivity_error':max((x['additivity_absolute_error'] for x in explanations if x['status']=='ready'),default=None),
            'mean_event_ms':float(np.mean([x['elapsed_ms'] for x in explanations if x['status']=='ready'])) if any(x['status']=='ready' for x in explanations) else None,
            'neighbor_pairs':len(stability),'same_class_pairs':sum(x['same_explained_class'] for x in stability),
            'mean_top3_jaccard_same_class':float(np.mean([x['top3_jaccard'] for x in stability if x['top3_jaccard'] is not None])) if any(x['top3_jaccard'] is not None for x in stability) else None,
            'source':'actual frozen offline explanations; backend validation lineage checked separately'},
        healthy_false_intervention={'value':None,'reason':'Offline alerts are not original-network actions; live healthy source outcomes reported separately'},
        host_load={'cpus':os.cpu_count(),'load_average':list(os.getloadavg())},
        limitations=['Prospective600-window/100-episode heldout with10 families; exact counts above override legacy compact-evaluator text.',
            'Validation reused for bounded selection/calibration/IF threshold; all validation scores are development only.',
            'Replay detection/evidence-availability delays are distinct from actual live onset-detection and end-to-end repair.',
            'Post-hoc SHAP utility/stability is not a user-study result; raw RF contributions differ from calibrated confidence.',
            'Fixed fault locations and shared emulator host; no production-network claim.'])
    with (output/'predictions_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['window_id','episode_id','family_id','actual','predicted','status','confidence','anomaly_score','inference_ms'])
        writer.writeheader()
        for i,p in enumerate(predictions):
            writer.writerow({'window_id':p['window_id'],'episode_id':p['episode_id'],'family_id':families[p['episode_id']],
                'actual':str(y[i]),'predicted':p['decision']['predicted_class'],**{k:p['decision'].get(k) for k in ['status','confidence','anomaly_score','inference_ms']}})
    current=json.loads((output/'pipeline_freeze.json').read_text())
    root=Path(__file__).resolve().parents[2]
    if any(sha(root/name)!=expected for name,expected in current['source_sha256'].items()):
        raise ValueError('Scientific pipeline source changed during heldout evaluation; result is not a new confirmatory claim')
    if (sha(protocol_path)!=current['protocol_sha256'] or sha(configuration)!=current['configuration_sha256']
            or sha(protocol_path.parent/'runtime/config.json')!=current['runtime_configuration_sha256']
            or sha(protocol_path.parent/'labs/plan.json')!=current['native_plan_sha256']):
        raise ValueError('Declared protocol/configuration/native plan changed during heldout evaluation')
    atomic_json(result_path,measured)
    return measured
