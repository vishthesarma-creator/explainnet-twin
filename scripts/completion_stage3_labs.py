"""Sequential prospective native comparisons using the new frozen trained model."""
import csv
import json
import random
import signal
from pathlib import Path

from completion_stage2 import Verification

from explainnet.application_profiles import ROOT
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage3'


class NativeStopped(RuntimeError):
    pass


def clocks(case,store):
    journal=(case.get('ground_truth',{}).get('setup',{}).get('laboratory_journal') or {})
    onset=journal.get('activated_monotonic_s')
    with store.connection() as db:
        values=[json.loads(r[0]) for r in db.execute("SELECT d.payload_json FROM diagnoses d JOIN telemetry_windows w USING(window_id) "
            "WHERE w.instance_id=? AND d.mode='live'",(case['instance_id'],))]
    observed=[d['diagnosed_monotonic_s'] for d in values if d.get('incident') and d.get('diagnosed_monotonic_s') is not None
        and onset is not None and d['diagnosed_monotonic_s']>=onset]
    w=case.get('workflow') or {};explanation=w.get('explanation') or {}
    ready=case.get('observation_ready_monotonic_s');diag_ready=case.get('diagnosis_explanation_ready_monotonic_s')
    return {'clock_domain':'same WSL kernel CLOCK_MONOTONIC; UTC is provenance only',
        'fault_onset_monotonic_s':onset,'first_detection_ms':(min(observed)-onset)*1000 if onset is not None and observed else None,
        'observation_ready_to_diagnosis_explanation_ms':(diag_ready-ready)*1000 if ready is not None and diag_ready is not None else None,
        'snapshot_ms':w.get('timings_ms',{}).get('snapshot_capture'),
        'candidate_testing_ms':(w.get('candidate_result') or {}).get('elapsed_ms'),
        'eligible_recommendation_ms':w.get('timings_ms',{}).get('decision_total') if (w.get('candidate_result') or {}).get('state')=='eligible' else None,
        'workflow_finish_ms':w.get('elapsed_ms'),'independent_no_twin_algorithm_ms':case.get('independent_baseline',{}).get('algorithm_ms'),
        'SHAP_compute_ms':explanation.get('runtime_ms'),
        'SHAP_queue_and_compute_ms':(explanation['completed_monotonic_s']-explanation['created_monotonic_s'])*1000
            if explanation.get('completed_monotonic_s') and explanation.get('created_monotonic_s') else None,
        'application_ms':case.get('original_action',{}).get('application',{}).get('application_elapsed_ms'),
        'verification_ms':case.get('original_action',{}).get('verification_ms'),
        'onset_to_outcome_ms':(case['outcome_monotonic_s']-onset)*1000 if onset is not None and case.get('outcome_monotonic_s') else None,
        'outcome_boundary':'Terminal original verification or refusal; recorded before intentional Undo/cleanup',
        'thermal_state':'model/background warmed by backend validation; fresh independent original and fresh twin reset each trial'}


def complete_candidate_coverage(experiment):
    order=experiment.get('randomized_order',[])
    changing={t['candidate_id'] for t in experiment.get('trials',[]) if t['family']!='no_change'}
    key=lambda t:(t['candidate_id'],t['hypothesis_id'],t['repetition'])
    measured={key(t) for t in experiment.get('trials',[]) if t['state']=='measured'}
    return len(changing)>=2 and len(order)>=6 and all(key(t) in measured for t in order)


def summarize(case,store,identity):
    workflow=case.get('workflow') or {};exp=workflow.get('candidate_result') or {};action=case.get('original_action') or {}
    controls=[t['fidelity'] for t in exp.get('trials',[]) if t.get('fidelity')]
    controls += [r['fidelity'] for r in case.get('healthy_twin_controls',[]) if r.get('fidelity')]
    windows=[p['window'] for p in action.get('post_windows',[])] or case.get('no_change_windows',[])
    return {**identity,'instance_id':case['instance_id'],'model_id':case['model_id'],'source_artifact':str(OUT/'labs/native'/(case['name']+'.json')),
        'finished':case.get('finished'),'state':case['state'],'error':case.get('error'),'workflow_error':workflow.get('error'),
        'workflow_reasons':workflow.get('reasons'),'trained_diagnosis':workflow.get('diagnosis') or case.get('trained_observation',{}).get('diagnosis'),
        'matching_explanation':workflow.get('explanation') or case.get('trained_observation',{}).get('explanation'),
        'model_transfer':'in declared5-switch training domain' if case['topology_switches']==5 else 'outside trained topology domain; predictions exploratory, original application prohibited',
        'construction_rpc_ms':case.get('construction_rpc_ms'),'native_construction_ms':case.get('construction',{}).get('construction_elapsed_ms'),
        'connectivity':{k:(case.get(k) or {}).get('passed') for k in ['connectivity','all_pair_connectivity','alternate_connectivity']},
        'control_fidelity':controls,'feasible_repair_count':len(exp.get('candidates',[]))-1 if exp.get('candidates') else None,
        'measured_candidates':len({t['candidate_id'] for t in exp.get('trials',[]) if t['family']!='no_change' and t['state']=='measured'}),
        'complete_repeated_candidate_coverage':complete_candidate_coverage(exp),
        'candidate_trial_count':len(exp.get('trials',[])),'candidate_definitions':exp.get('candidates'),
        'candidate_measurements':[
            {k:t.get(k) for k in ['trial_id','candidate_id','hypothesis_id','repetition','family','state','error','reasons','elapsed_ms','reset_ms','paired_capture_rpc_ms','materialization_ms']}
            | {'original_features':(t.get('original_window') or {}).get('features'),'twin_features':(t.get('window') or {}).get('features'),
                'original_quality':(t.get('original_window') or {}).get('data_quality'),'twin_quality':(t.get('window') or {}).get('data_quality'),
                'protected_flows':(t.get('window') or {}).get('per_flow')} for t in exp.get('trials',[])],
        'recommendation':exp.get('recommendation'),'rejection_details':workflow.get('rejection_details'),
        'independent_baseline':case.get('independent_baseline'),'baseline_original_refusal':case.get('baseline_original_refusal'),
        'original_outcome':action.get('state'),'original_windows':[{'window_id':w['window_id'],'features':w['features'],
            'quality':w['data_quality'],'protected_flows':w['per_flow']} for w in windows],
        'retained_impaired':case.get('retained_impaired',False),'rollback_or_undo':case.get('undo',{}).get('state') or ('rolled_back' if action.get('state')=='rolled_back' else None),
        'action_attempt_count':int(bool(action.get('action_id'))),'verified_success_count':int(action.get('state')=='succeeded'),
        'healthy_action_attempt_count':int(identity['condition']=='healthy' and bool(action.get('action_id'))),
        'transient_disruption':{k:(action.get('transient_disruption') or {}).get(k) for k in ['status','reason','metrics','resolution']},
        'timings':clocks(case,store),'source_episode_ms':case.get('elapsed_ms'),
        'cleanup':case.get('cleanup'),'automatic_repair_enabled':False,'observed_only_fallback':False,
        'measurement_source':'new independent real Mininet source; native paired receiver/probe/counter trials',
        'baseline_scope':'No-twin proposal computed before twin evidence; common shadow qualification required for original actuation and excluded from intrinsic proposal time'}


def make_native_plan(protocol):
    """Reserve all source conditions before opening any new holdout."""
    plan=[]
    for repeat in range(3):
        for approach in ['impaired_no_change','independent_no_twin','trained_twin']:
            plan.append({'name':f'primary_{approach[:8]}_r{repeat}','switches':5,'condition':'latency',
                'approach':approach,'repetition':repeat,'seed':930000000+repeat,'purpose':'primary_matched_comparison'})
    random.Random(protocol['seed']).shuffle(plan)
    for index,kind in enumerate(['loss','saturation','qos']):
        plan.append({'name':'qual_'+kind,'switches':5,'condition':kind,'approach':'trained_twin','repetition':0,
            'seed':931000000+index,'purpose':'bounded_new_model_fault_qualification'})
    for size in [5,10,15]:
        for condition in ['healthy','latency']:
            for repeat in range(3):
                plan.append({'name':f'scale{size}_{condition}_r{repeat}','switches':size,'condition':condition,
                    'approach':'trained_twin' if size==5 else 'recommend_only','repetition':repeat,
                    'seed':932000000+repeat,'purpose':'scale_benchmark'})
    return plan


def declare_native_plan():
    directory=OUT/'labs';directory.mkdir(exist_ok=True)
    protocol=json.loads((OUT/'protocol.json').read_text())
    plan=make_native_plan(protocol)
    plan_path=directory/'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text())['cases']!=plan:raise ValueError('Prospective native plan changed; no replay')
    if not plan_path.exists():atomic_json(plan_path,{'protocol_hash':protocol['protocol_hash'],'cases':plan,'declared_utc':utc_now()})
    if json.loads(plan_path.read_text())['protocol_hash']!=protocol['protocol_hash']:raise ValueError('Native plan protocol mismatch')
    return protocol,plan


def run(config):
    protocol,plan=declare_native_plan()
    directory=OUT/'labs'
    verifier=Verification('native',config=Path(config),output_root=OUT/'labs')
    if verifier.trusted['manifest'].get('training_profile')!='completion3':raise ValueError('New frozen model required; legacy/observed-only substitution forbidden')
    report={'protocol_hash':protocol['protocol_hash'],'model_id':verifier.model,'cases':[],'baseline_results':[],
        'scale_results':[],'per_fault':{},'finished':False,'started_utc':utc_now(),'expected_independent_sources':len(plan)}
    def save():
        atomic_json(directory/'report.json',report)
        from report_completion_stage3 import write_handover
        from status_completion_stage3 import record
        write_handover(record())
    def stop(_s,_f):raise NativeStopped('Native campaign stop requested; preserve source and finish owned verification/rollback')
    previous=signal.signal(signal.SIGTERM,stop)
    try:
        for entry in plan:
            path=verifier.out/(entry['name']+'.json')
            if path.exists():
                case=json.loads(path.read_text())
                if not case.get('finished'):raise RuntimeError('Interrupted source requires explicit reconciliation; not rerun: '+str(path))
            else:
                definition=json.loads((OUT/f"topology_{entry['switches']}.json").read_text())
                case=verifier.run_case(entry['name'],scenario_kind=entry['condition'],definition=definition,
                    strategy=entry['approach'],seed=entry['seed'],healthy_fidelity=entry['purpose']=='scale_benchmark')
            summary=summarize(case,verifier.store,entry);report['cases'].append(summary)
            if entry['purpose']=='primary_matched_comparison':report['baseline_results'].append(summary)
            if entry['purpose']=='scale_benchmark':report['scale_results'].append(summary)
            report['per_fault'].setdefault(entry['condition'],[]).append({'case':entry['name'],'state':summary['state'],
                'diagnosis_status':(summary['trained_diagnosis'] or {}).get('status'),'control_statuses':[v['status'] for v in summary['control_fidelity']],
                'measured_candidates':summary['measured_candidates'],'original_outcome':summary['original_outcome'],
                'model_transfer':summary['model_transfer'],'rejection_details':summary['rejection_details'],'error':summary['workflow_error'] or summary['error']})
            save()
            if case.get('cleanup',{}).get('blocked'):raise RuntimeError('Owned cleanup unsettled: '+case['cleanup']['blocked'])
        report.update(finished=True,ended_utc=utc_now(),automatic_repair_enabled=False)
        with (directory/'cases_summary.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['name','switches','condition','approach','repetition','state','measured_candidates','original_outcome','source_episode_ms'])
            writer.writeheader();writer.writerows({k:c.get(k) for k in writer.fieldnames} for c in report['cases'])
    except Exception as exc:
        report.update(error=str(exc),finished=False,ended_utc=utc_now());raise
    finally:
        signal.signal(signal.SIGTERM,previous)
        verifier.http('/v1/lab/automation/stop',{})
        save()
    return report
