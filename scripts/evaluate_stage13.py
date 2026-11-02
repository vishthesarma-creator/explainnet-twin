"""Reproducible Stage 13 audit, freeze/test, backend SHAP and evidence reporting."""
import argparse
import csv
import json
import time
import urllib.request
from collections import Counter
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json, export_dataset
from explainnet.dataset_repository import DatasetRepository
from explainnet.diagnosis_service import DiagnosisService
from explainnet.evaluation import evaluate_test, freeze
from explainnet.model_bundle import BundleRepository
from explainnet.storage import Store, utc_now
from explainnet.telemetry_service import TelemetryService

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/stage13'
BATCH = 'db5a15991774142f0a8ef871522face4d'


def audit(store):
    repo = DatasetRepository(store)
    batch = repo.batch(BATCH)
    result = export_dataset(store,BATCH)
    members = repo.members(BATCH)
    episodes = {e['episode_id']:e for e in batch['schedule']['episodes']}
    counts = Counter((episodes[m['episode_id']]['scenario']['kind'],episodes[m['episode_id']]['scenario']['severity'],m['partition']) for m in members)
    value = {**result['quality'],'feature_schema':json.loads(Path(result['manifest_path']).read_text())['feature_columns'],
        'class_severity_split_counts':[{'class':c,'severity':s,'split':p,'windows':n,
            'episodes':len({m['episode_id'] for m in members if (episodes[m['episode_id']]['scenario']['kind'],episodes[m['episode_id']]['scenario']['severity'],m['partition'])==(c,s,p)})}
            for (c,s,p),n in sorted(counts.items())],
        'membership_sha256':digest(members),'schedule_sha256':batch['schedule_hash'],
        'measurement_source':'Existing accepted and newly measured main episodes; pilot excluded',
        'quarantine':'All rejected windows remain indexed in dataset_attempts with reasons; no membership accepted from failed/canceled attempts.'}
    atomic_json(OUT/'dataset_audit.json',value)
    return value


def train(store,settings):
    existing = BundleRepository(store).list()
    if existing:
        matching=[r for r in existing if r['manifest'].get('training_profile')=='stage13'
            and r['manifest']['dataset']['batch_id']==BATCH]
        if not matching:
            raise ValueError('Existing bundles do not match the intended Stage 13 dataset/profile; no silent reuse or retraining')
        record=matching[0]
        BundleRepository(store).load(record['model_id'])
        if (OUT/'frozen_evaluation.json').exists():
            frozen=json.loads((OUT/'frozen_evaluation.json').read_text())
            if record['model_id']!=frozen['model_id'] or record['manifest_sha256']!=frozen['model_manifest_sha256']:
                raise ValueError('Existing bundle differs from frozen model; no test-driven retraining')
        return record
    service = DiagnosisService(store,TelemetryService(store,AgentClient(settings.agent_socket),settings.telemetry,settings.objective),ROOT/'artifacts')
    from explainnet.contracts import JobState
    job_id = 'j'+uuid4().hex
    store.create_job(job_id,'model_train','explicit-stage13',{'batch_id':BATCH,'profile':'stage13'})
    start = time.monotonic()
    try:
        result = service.train(BATCH,profile='stage13')
    except Exception as exc:
        store.finish_job(job_id,JobState.failed,(time.monotonic()-start)*1000,error=str(exc))
        raise
    store.finish_job(job_id,JobState.succeeded,(time.monotonic()-start)*1000,result={'model_id':result['bundle']['model_id']})
    atomic_json(OUT/'training_receipt.json',{'job_id':job_id,'model_id':result['bundle']['model_id'],'at_utc':utc_now()})
    return result['bundle']


def backend(settings,record):
    url = f'http://127.0.0.1:{settings.port}'
    def http(path,body=None):
        req = urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json','Idempotency-Key':'s13'+uuid4().hex})
        with urllib.request.urlopen(req,timeout=20) as r:
            return json.load(r)
    def job(path,body):
        submitted = http(path,body)
        deadline = time.monotonic()+120
        while time.monotonic()<deadline:
            r = http('/v1/jobs/'+submitted['job_id'])
            if r['state'] in {'succeeded','failed','canceled','interrupted'}:
                if r['state'] != 'succeeded':
                    raise RuntimeError(r.get('error') or r['state'])
                return r['result']
            time.sleep(.5)
        raise TimeoutError('Backend job deadline; request not retried')
    job('/v1/models/load',{'model_id':record['model_id']})
    dataset = Path(settings.data_dir)/'datasets'/BATCH
    splits = json.loads((dataset/'splits.json').read_text())
    ids = set(splits['validation']['window_ids'])
    chosen = {}
    training = {}
    for label in map(json.loads,(dataset/'labels.jsonl').read_text().splitlines()):
        if label['window_id'] in ids:
            chosen.setdefault(label['label'],label['window_id'])
        if label['window_id'] in set(splits['train']['window_ids']):
            training.setdefault(label['label'],label['window_id'])
    fresh=[]
    for label,wid in sorted(training.items()):
        result=job('/v1/models/infer',{'model_id':record['model_id'],'window_id':wid,'mode':'recorded'})
        fresh.append({'class':label,'split':'train','window_id':wid,'diagnosis':result,
            'purpose':'Fresh real backend inference/latency compatibility check; not a model quality estimate'})
        atomic_json(OUT/'backend_inference.json',{'cases':fresh,'measurement_source':'Actual backend execution on measured train windows'})
    cases = []
    for label,wid in sorted(chosen.items()):
        started = time.monotonic()
        diagnosis = job('/v1/models/infer',{'model_id':record['model_id'],'window_id':wid,'mode':'recorded'})
        inference_http_ms = (time.monotonic()-started)*1000
        explanation = job('/v1/explanations/request',{'model_id':record['model_id'],'window_id':wid,'mode':'recorded'})
        deadline = time.monotonic()+180
        while explanation['status']=='pending' and time.monotonic()<deadline:
            time.sleep(.5)
            explanation = http('/v1/explanations/'+explanation['explanation_id'])
        cases.append({'split':'validation','class':label,'window_id':wid,'model_id':record['model_id'],
            'diagnosis':diagnosis,'explanation':explanation,'inference_http_ms':inference_http_ms})
        atomic_json(OUT/'backend_shap.json',{'measurement_source':'Actual backend paths on measured validation windows',
            'cases':cases,'status':'running'})
    value = {'measurement_source':'Actual backend paths on measured validation windows','cases':cases,
        'ready_cases':sum(c['explanation']['status']=='ready' for c in cases),'status':'passed' if all(c['explanation']['status']=='ready' for c in cases) else 'partial'}
    atomic_json(OUT/'backend_shap.json',value)
    prior=ROOT/'artifacts/explanation_validation_report.json'
    if prior.exists() and not (OUT/'prior_explanation_validation_report.json').exists():
        (OUT/'prior_explanation_validation_report.json').write_bytes(prior.read_bytes())
    atomic_json(prior,{'schema_version':1,'stage':13,'status':'real_backend_shap_verified' if value['status']=='passed' else 'partial',
        'model_id':record['model_id'],'actual_measured_shap_cases':[
            {'split':c['split'],'window_id':c['window_id'],'class':c['class'],'model_id':record['model_id'],
                'status':c['explanation']['status'],'runtime_ms':c['explanation'].get('runtime_ms'),
                'explained_class':c['explanation'].get('explained_class'),
                'output_scale':c['explanation'].get('output_scale'),
                'underlying_model_output':c['explanation'].get('underlying_model_output'),
                'additivity_absolute_error':c['explanation'].get('additivity_absolute_error'),
                'additivity_tolerance':c['explanation'].get('additivity_tolerance'),
                'top_features':c['explanation'].get('top_features'),
                'measurement_source':'Actual backend explanation of a measured validation window'} for c in cases],
        'limitations':['SHAP explains raw RF probability, not calibrated confidence or physical causality.',
            'Historical Stage 8 software evidence is preserved in the Stage 13 prior-report archive.']})
    return value


def plots(metrics,lab):
    if not metrics and not lab.get('scale_results') and not lab.get('baseline_results'):
        return
    import plotly.graph_objects as go
    plot_dir = OUT/'plots'
    plot_dir.mkdir(exist_ok=True)
    def save(fig,name):
        fig.update_layout(template='plotly_white',font={'family':'Arial'},width=850,height=560)
        fig.write_html(plot_dir/(name+'.html'),include_plotlyjs=True,full_html=True)
    if metrics:
        matrix = metrics['window_classification']['confusion_matrix']
        labels = metrics['window_classification']['class_order']
        fig=go.Figure(go.Heatmap(z=matrix,x=labels,y=labels,text=matrix,texttemplate='%{text}',colorscale='Blues'))
        fig.update_layout(xaxis_title='Predicted class',yaxis_title='True class',
            title=f"Held-out test · {metrics['windows']} windows / {metrics['episodes']} episodes")
        save(fig,'confusion_matrix')
        bins = [b for b in metrics['calibration']['bins'] if b['count']]
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=[0,1],y=[0,1],mode='lines',name='Perfect calibration reference',line={'dash':'dash','color':'gray'}))
        fig.add_trace(go.Scatter(x=[b['mean_confidence'] for b in bins],y=[b['accuracy'] for b in bins],
            mode='lines+markers',name='Measured test reliability',text=[str(b['count'])+' windows' for b in bins]))
        fig.update_layout(xaxis_title='Mean confidence',yaxis_title='Observed accuracy',title='Test reliability · correlated windows',
            xaxis={'range':[0,1]},yaxis={'range':[0,1]})
        save(fig,'calibration')
    rows = lab.get('scale_results',[])
    measured = [r for r in rows if r.get('healthy_rtt_ms') is not None]
    if measured:
        fig=go.Figure(go.Scatter(x=[r['switches'] for r in measured],y=[r['healthy_rtt_ms'] for r in measured],mode='lines+markers',name='Healthy original'))
        impaired = [r for r in measured if r.get('impaired_rtt_ms') is not None]
        fig.add_trace(go.Scatter(x=[r['switches'] for r in impaired],y=[r['impaired_rtt_ms'] for r in impaired],mode='lines+markers',name='Latency original'))
        fig.update_layout(xaxis_title='Switch count',yaxis_title='Measured RTT (ms)',title='Actual scale observations')
        save(fig,'scale')
    baseline = lab.get('baseline_results',[])
    measured = [r for r in baseline if r.get('rtt_ms') is not None and r.get('measurement_plane')=='twin']
    if measured:
        fig=go.Figure()
        groups = sorted({r['approach'] for r in measured})
        for g in groups:
            fig.add_trace(go.Scatter(x=[g]*sum(r['approach']==g for r in measured),
                y=[r['rtt_ms'] for r in measured if r['approach']==g],mode='markers',name=g))
        fig.update_layout(yaxis_title='RTT (ms)',title='Matched twin comparison · independent source episodes')
        save(fig,'baseline_comparison')
    original=[r for r in baseline if r.get('rtt_ms') is not None and r.get('measurement_plane')=='original']
    if original:
        fig=go.Figure()
        for approach in sorted({r['approach'] for r in original}):
            rows=[r for r in original if r['approach']==approach]
            fig.add_trace(go.Scatter(x=[approach]*len(rows),y=[r['rtt_ms'] for r in rows],mode='markers',
                name=approach,text=[r['episode_id']+' · '+r['state'] for r in rows]))
        fig.update_layout(yaxis_title='Settled RTT (ms)',title='Original-network outcomes · independent trials; rejections retained in report')
        save(fig,'baseline_original_comparison')


def report(store):
    def load(name,default):
        path = OUT/name
        return json.loads(path.read_text()) if path.exists() else default
    audit_value = load('dataset_audit.json',{})
    metrics = load('held_out_metrics.json',{})
    lab = load('lab_report.json',{})
    shap = load('backend_shap.json',{})
    models = BundleRepository(store).list()
    blockers=[]
    if not audit_value.get('dataset_ready'): blockers.append('Main measured dataset has not passed its full target and quality gate.')
    if not models: blockers.append('No production model/calibration bundle exists.')
    if not metrics: blockers.append('Frozen held-out evaluation is unavailable.')
    if shap.get('ready_cases',0)<5: blockers.append('Real backend SHAP verification for all five validation classes is incomplete.')
    if lab.get('status')!='complete': blockers.append('Required recovery/fault/scale campaign is incomplete; inspect per-case checkpoints.')
    primary=[c for n,c in lab.get('cases',{}).items() if n.startswith('primary_')]
    trial_outcomes={a:dict(Counter(c['state'] for c in primary if c['approach']==a))
        for a in sorted({c['approach'] for c in primary})}
    cases=lab.get('cases',{})
    qualification=[]
    for row in lab.get('fault_qualification',[]):
        case=next((c for c in cases.values() if c['episode_id']==row['source_episode']),{})
        experiment=case.get('workflow',{}).get('candidate_result') or {}
        qualification.append(row|{'twin_state':experiment.get('state'),
            'workflow_error':case.get('workflow',{}).get('error'),
            'qualification_details':experiment.get('reasons',[]),
            'trial_refusals':[t.get('reasons',[]) for t in experiment.get('trials',[]) if t['state']!='measured']})
    trained=cases.get('trained',{})
    trained_workflow=trained.get('workflow',{})
    diagnosis=trained_workflow.get('diagnosis') or {}
    explanation=(trained.get('trained_application_gate') or {}).get('explanation') or trained_workflow.get('explanation') or {}
    trained_summary={'state':trained.get('state','not_yet_executed'),'mode':'trained-model',
        'model_id':trained.get('model_id'),'diagnosis_status':diagnosis.get('status'),
        'confidence':diagnosis.get('confidence'),'margin':diagnosis.get('margin'),
        'freshness':diagnosis.get('freshness'),'probability_status':diagnosis.get('probability_status'),
        'explanation_status':explanation.get('status'),'reasons':trained_workflow.get('reasons',[]),
        'workflow_error':trained_workflow.get('error'),'diagnosis_reasons':diagnosis.get('reasons',[]),
        'twin_state':(trained_workflow.get('candidate_result') or {}).get('state'),
        'twin_reasons':(trained_workflow.get('candidate_result') or {}).get('reasons',[]),
        'application_gate_passed':trained.get('trained_application_gate',{}).get('passed'),
        'original_application_state':trained.get('original_action',{}).get('state'),
        'source_episode':trained.get('episode_id'),'measurement_source':'Current real five-switch UDP latency case; separate from observed-only primary trials'}
    scales=[]
    for row in lab.get('scale_results',[]):
        case=next((c for c in cases.values() if c['episode_id']==row['episode_id']),{})
        workflow=case.get('workflow',{})
        experiment=workflow.get('candidate_result') or {}
        scales.append(row|{'healthy_no_unnecessary_repair':case.get('healthy_no_unnecessary_repair'),
            'connectivity_passed':case.get('connectivity',{}).get('passed'),
            'completed_connectivity_probes':case.get('connectivity',{}).get('completed_probes'),
            'workflow_error':workflow.get('error'),
            'workflow_reasons':workflow.get('reasons',[]),'twin_state':experiment.get('state'),
            'qualification_details':experiment.get('reasons',[])})
    value = {'schema_version':1,'stage':13,'finalized_utc':utc_now(),
        'status':'complete_with_declared_limits' if not blockers else 'in_progress_or_blocked',
        'dataset_audit':audit_value,'model_metadata':[r['manifest'] for r in models],
        'held_out_metrics':metrics,'baseline_results':lab.get('baseline_results',[]),
        'scale_results':scales,'fault_qualification':qualification,
        'summary':{'campaign_status':lab.get('status'),'execution_finished':lab.get('execution_finished',False),
            'primary_independent_attempts':len(primary),'primary_outcomes':trial_outcomes,
            'failed_cases':lab.get('failed_cases',[]),'case_errors':lab.get('errors',[]),
            'trained_recovery':trained_summary,
            'healthy_no_unnecessary_repair':{n:c.get('healthy_no_unnecessary_repair') for n,c in cases.items() if 'healthy_workflow' in c},
            'all_attempts_source':'artifacts/stage13/lab_report.json cases, including attempts with no usable measurements'},
        'checks':{'focused':load('software_checks.json',{}),'additional':load('additional_checks.json',{})},'blockers':blockers,
        'measurement_sources':{'dataset':'Real measured main episodes; pilot separate','diagnosis':'Frozen held-out offline replay',
            'backend_shap':'Real backend on measured validation windows','lab':'Current isolated packet experiments; per-case topology/protocol/repetition/plane recorded',
            'historical':'Stages 9–11 linked separately; no incompatible historical trials silently pooled'},
        'limitations':['Five-switch emulation training; correlated windows and few episode families.',
            'Original freeze did not bind all imported modules/settings; a dated post hoc receipt now guards reuse without retroactive pre-test claims or rescoring.',
            'Replay evidence availability includes backfill and is not historical online detection latency.',
            'Observed-only opt-in and trained-model gates remain separate.',
            'Recovery and scale uncertainty intervals are not estimated: three primary sources per approach and one source per additional topology. Within-snapshot repeats are not independent source episodes.',
            'Twin-only baseline results are not original-network repair results.',
            'Fixed rule may choose the same action as twin ranking; no superiority claim follows from coincident actions.'],
        'reproduce':['.venv/bin/python scripts/status_stage13.py',
            '.venv/bin/python scripts/stage13_provenance.py',
            '.venv/bin/python scripts/evaluate_stage13.py score',
            '.venv/bin/python scripts/status_stage13_lab.py',
            'sudo env PYTHONPATH=src /usr/bin/python3 scripts/stage13_lab_supervisor.py --resume '+lab.get('campaign_id','492fca67')+' --detach',
            '.venv/bin/python scripts/evaluate_stage13.py report']}
    atomic_json(ROOT/'artifacts/evaluation_validation_report.json',value)
    for name,rows in [('baseline_summary',value['baseline_results']),('scale_summary',value['scale_results'])]:
        if rows:
            fields = sorted({k for r in rows for k,v in r.items() if not isinstance(v,(dict,list))})
            with (OUT/(name+'.csv')).open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
    plots(metrics,lab)
    text = ['# ExplainNet Twin — Stage 13 evaluation',f"\nRecorded UTC: {value['finalized_utc']}",f"\nStatus: **{value['status']}**",
        '\n## Dataset',f"\n{audit_value.get('accepted_windows','Unavailable')}/360 windows; {audit_value.get('completed_episodes','Unavailable')}/60 episodes. Splits: {audit_value.get('partitions',{})}.",
        '\n## Model and held-out diagnosis',f"\nTrusted bundles: {len(models)}. Real backend SHAP ready cases: {shap.get('ready_cases',0)}/5."]
    if metrics:
        text += [f"\nTest: {metrics['windows']} windows from {metrics['episodes']} episodes. Macro F1 {metrics['window_classification']['macro_f1']:.4f}; accuracy {metrics['window_classification']['accuracy']:.4f}; coverage {metrics['abstention']['coverage_fraction']:.4f}.",
            f"\nBrier (five-class sum convention): {metrics['calibration']['multiclass_brier_sum']:.4f}; log loss {metrics['calibration']['log_loss']:.4f}. Episode bootstrap: {metrics['uncertainty']}.",
            '\nOnline detection delay was not measured by historical replay. See separately labeled window replay times and source availability.']
    text += ['\n## Recovery, baselines and scale','\nCurrent packet trials and their failures/rejections are checkpointed in `artifacts/stage13/labs/`. Matched twin baselines and original applied outcomes are separate in the JSON/CSV report.',
        '\nIndependent primary attempts by outcome: `'+json.dumps(trial_outcomes,sort_keys=True)+'`. All attempted sources count, including those without usable metrics. Within-snapshot trials are not independent repetitions.']
    original=[r for r in value['baseline_results'] if r.get('measurement_plane')=='original']
    if original:
        text += ['\n### Original-network comparison','\n| Approach | Attempts | Sources with post data | Mean RTT (ms) | Mean critical (Mbps) | Outcomes |',
            '| --- | ---: | ---: | ---: | ---: | --- |']
        def display_mean(rows,key,scale=1):
            values=[r[key]/scale for r in rows if r.get(key) is not None]
            return f'{sum(values)/len(values):.3f}' if values else 'Unavailable'
        for approach in sorted({r['approach'] for r in original}):
            rows=[r for r in original if r['approach']==approach]
            text.append(f"| {approach} | {len(rows)} | {sum(r.get('rtt_ms') is not None for r in rows)} sources | {display_mean(rows,'rtt_ms')} | {display_mean(rows,'critical_bps',1e6)} | {dict(Counter(r['state'] for r in rows))} |")
    if value['scale_results']:
        text += ['\n### Actual scale trials','\n| Switches | Healthy RTT (ms) | Fault RTT (ms) | Original outcome |',
            '| ---: | ---: | ---: | --- |']
        for row in value['scale_results']:
            text.append(f"| {row['switches']} | {row.get('healthy_rtt_ms')} | {row.get('impaired_rtt_ms')} | {row['state']} |")
    if value['fault_qualification']:
        text += ['\n### Other-fault qualification',*['\n- '+json.dumps(r,sort_keys=True) for r in value['fault_qualification']]]
    text += ['\n### Trained-model recovery path','\n'+json.dumps(trained_summary,sort_keys=True),
        '\nPrimary comparisons above use explicit observed-only opt-in. They are not evidence of trained AI repair. Healthy controls: `'+
        json.dumps(value['summary']['healthy_no_unnecessary_repair'],sort_keys=True)+'`.']
    text += ['\n## Blockers',*['\n- '+b for b in blockers], '\n## Reproduction','\n```bash',*value['reproduce'],'```',
        '\nThe score command verifies the saved freeze and dependency receipt, then reuses the original test metrics without rescoring. Resume skips finished cases. A fresh full campaign omits `--resume`; it retains the same declared protocol/order and writes a new campaign directory. Never run native campaigns concurrently.',
        '\n## Limits',*['\n- '+l for l in value['limitations']], '\nStopped after Stage 13; Stages 14 and 15 remain pending.']
    (ROOT/'docs/EVALUATION_STAGE13.md').write_text('\n'.join(text)+'\n')
    return value


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['audit','train','score','backend','report'])
    parser.add_argument('--config',type=Path,default=ROOT/'artifacts/stage6/runtime/config.json')
    args=parser.parse_args(); OUT.mkdir(exist_ok=True)
    settings=load_settings(args.config); store=Store(settings.database_path)
    if args.action=='audit': result=audit(store)
    elif args.action=='train': result=train(store,settings)
    elif args.action=='score':
        record=train(store,settings)
        frozen=freeze(store,record['model_id'],ROOT/'config/evaluation_stage13.json',OUT)
        if (OUT/'held_out_metrics.json').exists():
            from stage13_provenance import verify
            verify(settings)
            result=json.loads((OUT/'held_out_metrics.json').read_text())
        else:
            result=evaluate_test(store,frozen,settings,OUT)
    elif args.action=='backend': result=backend(settings,BundleRepository(store).list()[0])
    else: result=report(store)
    print(json.dumps({k:result[k] for k in ('status','dataset_ready','accepted_windows','episodes','model_id','ready_cases','blockers') if k in result},indent=2))


if __name__=='__main__': main()
