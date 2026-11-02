"""Software fixtures only; these checks are never reported as packet efficacy."""
import base64
import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_explanations import unit_background
from test_models import fitted_unit_bundle, measurements, policy_bundle, window, write_loader_fixture

from explainnet.completion_baselines import independent_proposal
from explainnet.completion_client import CompletionClient
from explainnet.completion_protocol import SEED, make_completion_schedule
from explainnet.contracts import ServiceObjective
from explainnet.dataset_contracts import digest
from explainnet.model_bundle import validate_bundle
from explainnet.model_contracts import CLASS_ORDER
from explainnet.model_dataset import Partition, load_measured_dataset
from explainnet.model_features import feature_array
from explainnet.model_policy import infer
from explainnet.storage import Store
from explainnet.telemetry_contracts import TelemetrySettings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def test_prospective_counts_family_separation_and_historical_holdout_disjoint():
    schedule=make_completion_schedule().model_dump()
    assert schedule==make_completion_schedule().model_dump()
    assert len(schedule['episodes'])==600
    assert Counter(e['partition'] for e in schedule['episodes'])=={'train':400,'validation':100,'test':100}
    assert Counter(e['scenario']['kind'] for e in schedule['episodes'])==dict.fromkeys(CLASS_ORDER,120)
    assert sum(e['target_windows'] for e in schedule['episodes'])==3600
    groups=[{e['family_id'] for e in schedule['episodes'] if e['partition']==p} for p in ['train','validation','test']]
    assert [len(g) for g in groups]==[40,10,10]
    assert not groups[0]&groups[1] and not groups[1]&groups[2] and not groups[0]&groups[2]
    signature=lambda e:digest({k:v for k,v in e['scenario'].items() if k not in {'seed','measurement_s','warmup_s'}})
    old=json.loads(Path('config/datasets/main_v1.json').read_text())['episodes']
    assert not {signature(e) for e in old}&{signature(e) for e in schedule['episodes'] if e['partition']=='test'}
    assert not {e['scenario']['seed'] for e in old}&{e['scenario']['seed'] for e in schedule['episodes']}
    assert schedule['telemetry']['min_coverage_fraction']==.65 and schedule['max_attempts']==2


def test_native_plan_reserved_independent_primary_and_scale_sources():
    from completion_stage3_labs import make_native_plan
    plan=make_native_plan({'seed':SEED})
    assert plan==make_native_plan({'seed':SEED}) and len(plan)==30
    assert len({e['name'] for e in plan})==30
    primary=[e for e in plan if e['purpose']=='primary_matched_comparison']
    assert Counter(e['approach'] for e in primary)==dict.fromkeys(['impaired_no_change','independent_no_twin','trained_twin'],3)
    for repeat in range(3):assert len({e['seed'] for e in primary if e['repetition']==repeat})==1
    scale=[e for e in plan if e['purpose']=='scale_benchmark']
    assert Counter((e['switches'],e['condition']) for e in scale)=={(s,c):3 for s in [5,10,15] for c in ['healthy','latency']}
    assert all(e['approach']=='recommend_only' for e in scale if e['switches']>5)


def test_expansion_loader_preserves_sealed_test_and_topology_identity(tmp_path):
    manifest=write_loader_fixture(tmp_path)
    manifest.update(purpose='expansion',dataset_version='completion3_v1',topology_hash='verified-topology')
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    train,validation,hashes=load_measured_dataset(tmp_path)
    # Existing fixture test cells are deliberately nonnumeric SEALED values.
    assert train.counts()['windows']==40 and validation.counts()['windows']==10
    assert hashes['topology_hash']=='verified-topology'


def test_completion_training_all_eight_families_without_validation_fit(monkeypatch):
    from explainnet.model_training import train_models
    def data(partition,families):
        y=np.asarray([c for c in CLASS_ORDER for _ in range(families*4)])
        groups=np.asarray([f'{partition}_{c}_{i//4}' for c in CLASS_ORDER for i in range(families*4)])
        episodes=np.asarray([f'{partition}_{c}_{i//2}' for c in CLASS_ORDER for i in range(families*4)])
        windows=[window() for _ in y]
        for i,w in enumerate(windows):
            w.update(window_id=f'{partition}_{i}',start_monotonic_s=i*10,context={'config_hash':'topology'})
            if partition=='validation':w['features']['rtt_mean_ms']=100
        return Partition(feature_array([w['features'] for w in windows]),y,groups,episodes,windows)
    train,validation=data('train',8),data('validation',3)
    monkeypatch.setattr('explainnet.model_training.CANDIDATES',[{'max_depth':2,'min_samples_leaf':2,'max_features':'sqrt'}])
    bundle,report=train_models(train,validation,{'manifest_sha256':'fixture','topology_hash':'topology'},TelemetrySettings(),ServiceObjective(),profile='completion3')
    assert bundle['seed']==SEED and bundle['classifier'][-1].random_state==SEED
    assert bundle['isolation_forest'].random_state==SEED
    assert bundle['classifier'][0].sample_count_==len(train.y)
    assert bundle['classifier'][0].statistics_[bundle['classifier'][0].feature_names_.index('rtt_mean_ms')]==measurements()['rtt_mean_ms']
    assert bundle['anomaly_preprocessing'].sample_count_==int((train.y=='healthy').sum())
    assert report['data_coverage']['calibration_partition']=='validation'
    folds=report['selection']['candidates'][0]['folds']
    seen=[]
    for fold in folds:
        assert not set(fold['fit_groups'])&set(fold['validation_groups'])
        seen.extend(fold['validation_groups'])
    assert len(seen)==40 and len(set(seen))==40
    assert bundle['supported_topology_hashes']==['topology']


def test_embedded_background_partition_and_hash_are_immutable():
    bundle,X=fitted_unit_bundle()
    bundle['training_background']=unit_background(bundle,X)
    validate_bundle(bundle)
    for defect in ['partition','content_hash','dataset','model_id']:
        bad=deepcopy(bundle);bad['training_background'][defect]='changed'
        with pytest.raises(ValueError,match='training-only SHAP'):validate_bundle(bad)


def test_larger_topology_abstains_without_changing_raw_predictions():
    bundle=policy_bundle();bundle['supported_topology_hashes']=['five']
    w=window();w['context']={'config_hash':'five'}
    good=infer(bundle,w,TelemetrySettings(),ServiceObjective())
    w['context']['config_hash']='fifteen'
    outside=infer(bundle,w,TelemetrySettings(),ServiceObjective())
    assert good['raw_probabilities']==outside['raw_probabilities']
    assert outside['status']!='supported'
    assert any('topology' in r for r in outside['reasons'])


def test_independent_selector_ignores_truth_model_and_twin_results():
    w=window();w['features']['rtt_p95_ms']=80
    view={'definition':{'pairs':[{'pair_id':'critical','source_host':'h1','target_host':'h3',
        'paths':{'primary':['s1','s2','s5'],'alternative':['s1','s4','s5']}}]},'selected_paths':{'critical':'primary'}}
    proposal=independent_proposal(w,view)
    changed=independent_proposal(w|{'ground_truth':{'label':'healthy'},'diagnosis':{'predicted_class':'qos'}},view|{'twin_results':{'winner':'primary'}})
    assert proposal['action']==changed['action'] and proposal['action']['changes'][0]['to_path']=='alternative'
    assert not proposal['uses_twin_results'] and not proposal['uses_injector_truth']
    assert independent_proposal(window(),view)['action'] is None


@pytest.mark.parametrize('defect',['hash','offset','oversized','empty','next_offset'])
def test_paged_job_evidence_rejects_corruption(defect):
    value=json.dumps({'result':{'verified':True}}).encode();total=len(value)
    page={'sha256':hashlib.sha256(value).hexdigest(),'total_bytes':total,'offset':0,'base64':base64.b64encode(value).decode(),'next_offset':total}
    if defect=='hash':page['sha256']='bad'
    if defect=='offset':page['offset']=1
    if defect=='oversized':page['total_bytes']=32*1024*1024+1
    if defect=='empty':page['base64']=''
    if defect=='next_offset':page['next_offset']=total+1
    reader=object.__new__(CompletionClient);reader.get=lambda _:page
    with pytest.raises(ValueError,match='mismatch'):reader.job_evidence('jfixture')


def test_unknown_submission_reconciles_without_replay(tmp_path):
    reader=object.__new__(CompletionClient);reader.directory=tmp_path
    (tmp_path/'logical.json').write_text(json.dumps({'request_key':'key','route':'/v1/example','body':{},'state':'pending_submission'}))
    reader.get=lambda _:{'found':False}
    reader.client=SimpleNamespace(submit=lambda *a:pytest.fail('unknown outcome must never be resubmitted'))
    with pytest.raises(RuntimeError,match='reconcile'):reader.job('logical','/v1/example',{})


def test_incomplete_corpus_never_opens_training_or_holdout(tmp_path):
    from complete_stage3_analysis import completed_cohort
    store=Store(tmp_path/'e.sqlite3');store.initialize()
    with pytest.raises(ValueError,match='training/test evaluation prohibited'):completed_cohort(store)


def test_freeze_binds_native_plan_runtime_and_scientific_sources(tmp_path,monkeypatch):
    from explainnet.completion_evaluation import freeze_pipeline
    protocol={'seed':SEED};protocol['protocol_hash']=digest(protocol)
    p=tmp_path/'protocol.json';p.write_text(json.dumps(protocol))
    (tmp_path/'runtime').mkdir();(tmp_path/'runtime/config.json').write_text('{}')
    (tmp_path/'labs').mkdir();plan=tmp_path/'labs/plan.json'
    plan.write_text(json.dumps({'protocol_hash':protocol['protocol_hash'],'cases':[]}))
    cfg=tmp_path/'eval.json';cfg.write_text('{}')
    bundle={'training_profile':'completion3','training_background':{'content_hash':'bg'},
        'dataset':{'manifest_sha256':'dataset','protocol_hash':protocol['protocol_hash']}}
    registry=SimpleNamespace(inspect=lambda _:{'manifest_sha256':'model'},load=lambda _:bundle)
    monkeypatch.setattr('explainnet.completion_evaluation.BundleRepository',lambda _:registry)
    monkeypatch.setattr('explainnet.completion_evaluation.freeze',lambda *a:{'fixture':True})
    output=tmp_path/'out'
    freeze_pipeline(None,'m',p,cfg,output)
    receipt=json.loads((output/'pipeline_freeze.json').read_text())
    assert 'src/explainnet/service_requirements.py' in receipt['source_sha256']
    assert receipt['native_plan_sha256']==hashlib.sha256(plan.read_bytes()).hexdigest()
    assert not (output/'test_access.json').exists()
    (tmp_path/'runtime/config.json').write_text('{"changed":true}')
    with pytest.raises(ValueError,match='changed after freeze'):freeze_pipeline(None,'m',p,cfg,output)


def test_full_completion_evaluator_shap_ablation_and_resume(tmp_path,monkeypatch):
    """Actual toy RF/IF/SHAP plumbing, never a measured accuracy claim."""
    from test_stage13 import test_full_frozen_evaluator_saves_predictions_before_labels

    from explainnet.completion_evaluation import evaluate_pipeline
    from explainnet.model_bundle import BundleRepository

    test_full_frozen_evaluator_saves_predictions_before_labels(tmp_path,monkeypatch)
    store=Store(tmp_path/'e.sqlite3');registry=BundleRepository(store)
    bundle=registry.load('munit');_,X=fitted_unit_bundle()
    protocol={'seed':SEED};protocol['protocol_hash']=digest(protocol)
    declaration=tmp_path/'prospective';declaration.mkdir()
    protocol_path=declaration/'protocol.json';protocol_path.write_text(json.dumps(protocol))
    (declaration/'runtime').mkdir();(declaration/'runtime/config.json').write_text('{}')
    (declaration/'labs').mkdir();(declaration/'labs/plan.json').write_text(json.dumps({'protocol_hash':protocol['protocol_hash'],'cases':[]}))
    bundle.update(model_id='munit_completion3',training_profile='completion3')
    bundle['dataset']['protocol_hash']=protocol['protocol_hash']
    bundle['dataset']['topology_hash']='fixture-five'
    bundle['supported_topology_hashes']=['fixture-five']
    from explainnet.service_requirements import VERSION
    bundle['service_contract_version']=VERSION
    bundle['training_background']=unit_background(bundle,X)
    registry.publish(bundle,{},X)
    data=tmp_path/'datasets/fixture'
    (data/'schedule.json').write_text(json.dumps({'episodes':[
        {'episode_id':c+str(r),'family_id':c+'_family'+str(r)} for c in CLASS_ORDER for r in range(2)]}))
    configuration=declaration/'evaluation_config.json'
    configuration.write_text(json.dumps({'training_profile':'completion3','test_tuning_permitted':False,'seed':SEED,'bootstrap_repetitions':10}))
    output=tmp_path/'completion_evaluation'
    settings=SimpleNamespace(telemetry=TelemetrySettings(),objective=ServiceObjective())
    result=evaluate_pipeline(store,bundle['model_id'],settings,protocol_path,configuration,output)
    assert result['windows']==result['episodes']==result['families']==10
    assert result['SHAP']['ready']==result['SHAP']['denominator']==10
    assert result['SHAP']['max_additivity_error']<=1e-6
    assert result['no_XAI']=={'identical':10,'denominator':10,'post_hoc':True}
    assert (output/'test_access.json').exists() and (output/'pipeline_freeze.json').exists()
    assert evaluate_pipeline(store,bundle['model_id'],settings,protocol_path,configuration,output)==result


@pytest.mark.parametrize('defect',['background','protocol','domain','service'])
def test_completion_bundle_refuses_incomplete_scientific_binding(defect):
    from explainnet.service_requirements import VERSION
    bundle,X=fitted_unit_bundle()
    bundle['training_profile']='completion3'
    bundle['dataset'].update(protocol_hash='a'*64,topology_hash='fixture-five')
    bundle.update(supported_topology_hashes=['fixture-five'],service_contract_version=VERSION)
    bundle['training_background']=unit_background(bundle,X)
    validate_bundle(bundle)
    if defect=='background':bundle.pop('training_background')
    if defect=='protocol':bundle['dataset']['protocol_hash']='missing'
    if defect=='domain':bundle['supported_topology_hashes']=['other']
    if defect=='service':bundle['service_contract_version']='other'
    with pytest.raises(ValueError,match='completion3 protocol/domain/service/background'):validate_bundle(bundle)


def test_report_does_not_count_partial_candidate_repeats_as_complete():
    from completion_stage3_labs import complete_candidate_coverage
    trials=[{'candidate_id':c,'family':'no_change' if c=='c0' else 'reroute','hypothesis_id':'h0',
        'repetition':r,'state':'measured'} for c in ['c0','c1','c2'] for r in range(2)]
    experiment={'trials':trials,'randomized_order':deepcopy(trials)}
    assert complete_candidate_coverage(experiment)
    trials[-1]['state']='refused'
    assert not complete_candidate_coverage(experiment)
    trials.pop()
    assert not complete_candidate_coverage(experiment)
