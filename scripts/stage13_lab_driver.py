"""Current packet evaluation. Setup truth is never passed to diagnosis/twin inputs."""
import json
import os
import random
import shutil
import sys
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.config import load_network, load_settings
from explainnet.dataset_export import atomic_json
from explainnet.model_bundle import BundleRepository
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkDefinition,
    NetworkStartRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    WorkloadProfile,
)
from explainnet.storage import Store, utc_now
from explainnet.topology.spec import scale_definition
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest

ROOT=Path(__file__).resolve().parents[1]


def main():
    cfg,tag=Path(sys.argv[1]),sys.argv[2]
    settings=load_settings(cfg); out=cfg.parent
    store=Store(settings.database_path); agent=AgentClient(settings.agent_socket)
    twins=TwinService(store,agent,settings.objective)
    base=load_network(settings.topology_file).model_dump()
    report=json.loads((out/'report.json').read_text()) if (out/'report.json').exists() else {
        'schema_version':1,'stage':13,'campaign_id':tag,'status':'running','cases':{},'baseline_results':[],
        'scale_results':[],'fault_qualification':[],'app_uid':os.geteuid(),'software_fixtures':False,
        'historical_trials_pooled':False,'observed_only_opt_in_explicit':True,'errors':[]}
    report['status']='running'
    def save():
        atomic_json(out/'report.json',report)
        atomic_json(ROOT/'artifacts/stage13/lab_report.json',report)
    def http(path,body=None):
        req=urllib.request.Request(f'http://127.0.0.1:{settings.port}'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json','Idempotency-Key':'s13'+uuid4().hex})
        with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)
    def job(path,body):
        submitted=http(path,body); end=time.monotonic()+130
        while time.monotonic()<end:
            r=http('/v1/jobs/'+submitted['job_id'])
            if r['state'] in {'succeeded','failed','canceled','interrupted'}:
                if r['state']!='succeeded': raise RuntimeError(r.get('error') or r['state'])
                return r['result']
            time.sleep(.4)
        raise TimeoutError('Job outcome unknown; not retried')
    def workflow(body):
        job('/v1/lab/workflow',body)
        end=time.monotonic()+930; previous=None
        while time.monotonic()<end:
            w=http('/v1/lab/workflows/'+body['workflow_id'])
            if w['state']!=previous:
                print(body['workflow_id']+': '+w['state'],flush=True); previous=w['state']
            if w['state'] in {'recommended','refused','failed','interrupted','succeeded','rolled_back'}: return w
            time.sleep(1)
        raise TimeoutError('Bounded workflow deadline')
    def import_model():
        source_settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
        source=BundleRepository(Store(source_settings.database_path))
        records=source.list()
        if not records: return None
        record=records[0]; source.load(record['model_id'])
        target=BundleRepository(store); target.root.mkdir(exist_ok=True)
        destination=target.root/record['model_id']
        shutil.copytree(source.root/record['model_id'],destination)
        with store.connection() as db:
            copied=record|{'directory':str(destination)}
            db.execute('INSERT INTO model_bundles VALUES(?,?,?,?)',(record['model_id'],record['manifest']['created_utc'],record['manifest_sha256'],json.dumps(copied)))
        batch=record['manifest']['dataset']['batch_id']
        shutil.copytree(source.store.path.parent/'datasets'/batch,store.path.parent/'datasets'/batch)
        target.load(record['model_id'])
        job('/v1/models/load',{'model_id':record['model_id']})
        return record['model_id']
    def request(instance,baseline,policy):
        return {'instance_id':instance,'workflow_id':'w'+uuid4().hex,'request_key':'k'+uuid4().hex,
            'baseline':baseline,'policy':policy,'max_repairs':1,'max_hypotheses':2,'timeout_s':900}
    def summarize(case):
        exp=case.get('workflow',{}).get('candidate_result') or case.get('experiment') or {}
        candidates={c['candidate_id']:c for c in exp.get('candidates',[])}
        selected=(exp.get('recommendation') or {}).get('selected_candidate_id')
        fixed=next((c['candidate_id'] for c in exp.get('candidates',[]) if c['action']['family']=='reroute'
            and any(change['pair_id']=='critical' and change['to_path']=='alternative' for change in c['action']['changes'])),None)
        def bulk_mean(windows):
            rates=[w['per_flow'].get('h2->h4:udp',{}).get('delivered_bps') for w in windows]
            return sum(rates)/len(rates) if rates and all(r is not None for r in rates) else None
        for approach,candidate in [('no_change',next((k for k,v in candidates.items() if v['action']['family']=='no_change'),None)),
            ('fixed_rule',fixed),('twin_guided',selected)]:
            trials=[t for t in exp.get('trials',[]) if t['candidate_id']==candidate and t['state']=='measured']
            def mean(field,trials=trials):
                values=[t['window']['features'].get(field) for t in trials]
                return sum(values)/len(values) if values and all(v is not None for v in values) else None
            report['baseline_results'].append({'episode_id':case['episode_id'],'topology':case['switches'],
                'workload':'8 Mbps critical / 5 Mbps bulk UDP','fault':'high one-way latency','protocol':'udp',
                'repetition':case['repetition'],'approach':approach,'candidate_id':candidate,'measurement_plane':'twin',
                'measurement_source':'Current matched capture after verified fresh twin resets','within_episode_trials':len(trials),
                'rtt_ms':mean('rtt_mean_ms'),'critical_bps':mean('critical_goodput_bps'),'loss_fraction':mean('udp_loss_fraction'),
                'bulk_bps':bulk_mean([t['window'] for t in trials]),
                'state':exp.get('state'),'cost':candidates.get(candidate,{}).get('expected_disruption'),
                'note':'Fixed rule may coincide with twin choice. Twin results are not original applied outcomes.'})
        action=case.get('original_action') or {}
        post=[p['window'] for p in action.get('post_windows',[])] or case.get('no_change_windows',[])
        predicted=[p for row in action.get('post_windows',[]) for p in row.get('predicted_rtt_mean_ms',[])]
        actual=[w['features']['rtt_mean_ms'] for w in post]
        report['baseline_results'].append({'episode_id':case['episode_id'],'topology':case['switches'],
            'workload':'8 Mbps critical / 5 Mbps bulk UDP','fault':'high one-way latency','protocol':'udp',
            'repetition':case['repetition'],'approach':case['approach'],'measurement_plane':'original',
            'measurement_source':'Current original matched verification windows; qualification-gated application where permitted',
            'state':case['state'],'rtt_ms':sum(actual)/len(actual) if actual else None,
            'critical_bps':sum(w['features']['critical_goodput_bps'] for w in post)/len(post) if post else None,
            'bulk_bps':bulk_mean(post),
            'loss_fraction':sum(w['features']['udp_loss_fraction'] for w in post)/len(post) if post else None,
            'application_ms':action.get('application',{}).get('application_elapsed_ms'),
            'verification_and_application_ms':action.get('elapsed_ms'),
            'verification_ms':action.get('verification_ms'),
            'detection_observation_ms':case.get('workflow',{}).get('timings_ms',{}).get('detection_observation'),
            'live_detection_delay_ms':case.get('live_detection_timing',{}).get('delay_ms'),
            'diagnosis_stage_ms':case.get('workflow',{}).get('timings_ms',{}).get('diagnosis_and_explanation_submission'),
            'inference_ms':case.get('workflow',{}).get('diagnosis',{}).get('inference_ms'),
            'twin_evaluation_ms':case.get('twin_evaluation_ms'),'recovery_total_ms':case.get('recovery_total_ms'),
            'prediction_observation_rtt_error_ms':abs(sum(actual)/len(actual)-sum(predicted)/len(predicted)) if actual and predicted else None,
            'repair_success':case['state']=='succeeded','rollback_count':int(case['state']=='rolled_back'),
            'repeat_action_count':max(0,case.get('action_count',0)-1),
            'action_cost':candidates.get(action.get('candidate_id'),{}).get('expected_disruption') if action else
                next((c['expected_disruption'] for c in candidates.values() if c['action']['family']=='no_change'),None) if case.get('retained_impaired') else None,
            'transient_disruption':action.get('transient_disruption'),
            'note':'Original outcome. Fixed rule requires the same safety qualification and an identical selected action; no change retains the impairment. Common shadow-evaluation overhead is reported separately.'})
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            if http('/v1/health')['worker_live']: break
        except OSError: pass
        time.sleep(.3)
    else: raise RuntimeError('API startup deadline')
    specs=[('primary_'+str(r),5,'latency','udp',r,True,False) for r in range(3)]
    specs += [(f'primary_{approach}_{r}',5,'latency','udp',r,approach=='fixed',False)
        for approach in ('nochange','fixed') for r in range(3)]
    first=specs.pop(0)
    random.Random(20261016).shuffle(specs)
    specs=[first,*specs]
    specs += [(name,5,kind,proto,0,False,False) for name,kind,proto in
        [('loss','loss','udp'),('saturation','saturation','udp'),('qos','qos','udp'),('latency_tcp','latency','tcp')]]
    specs += [('scale_'+str(n),n,'latency','udp',0,True,False) for n in (10,15)]
    specs += [('trained',5,'latency','udp',0,True,True)]
    report['declared_order']=[{'case':s[0],'switches':s[1],'repetition':s[4]} for s in specs]
    report['order_seed']=20261016
    try:
        for name,size,kind,protocol,repetition,apply,trained in specs:
            if report['cases'].get(name,{}).get('finished'): continue
            case=report['cases'][name]={'episode_id':'s13_'+name+'_'+uuid4().hex[:8],'switches':size,
                'fault':kind,'bulk_protocol':protocol,'critical_protocol':'udp','repetition':repetition,
                'started_utc':utc_now(),'state':'starting','mode':'trained-model' if trained else 'observed-only',
                'measurement_source':'Current real Mininet/OVS/tc/iperf packet experiment','config':str(cfg)}
            case['approach']='no_change' if 'nochange' in name else 'fixed_rule_with_safety_qualification' if 'fixed' in name else 'twin_guided'
            original='s13_'+uuid4().hex[:14]; case['instance_id']=original; active_workflow=None; start=time.monotonic()
            print('Starting '+name+' with '+str(size)+' switches',flush=True); save()
            try:
                if trained:
                    model=import_model()
                    if not model:
                        case.update(state='blocked',reason='No actual production model; trained path not attempted',finished=True); continue
                    case['model_id']=model
                definition=scale_definition(base,size)
                declared=json.loads((ROOT/'config/topologies'/('scale_'+str(size)+'_v1.json')).read_text())
                if declared != definition: raise ValueError('Declared scale template differs from deterministic definition')
                construction_start=time.monotonic()
                case['construction']=agent.network_start(NetworkStartRequest(instance_id=original,definition=NetworkDefinition.model_validate(definition)))
                case['construction_ms']=(time.monotonic()-construction_start)*1000
                case['connectivity']=agent.network_probe(ProbeRequest(instance_id=original,source_host='h1',target_host='h3'))
                healthy=agent.traffic_start(TrafficStartRequest(instance_id=original,profiles=[WorkloadProfile(
                    profile_id=p,source_host=a,target_host=b,protocol='udp',offered_bps=rate,duration_s=900,warmup_s=3,
                    stream_receiver=True,config_version='recovery_observation_v1',packet_size=1200)
                    for p,a,b,rate in [('critical','h1','h3',8000000),('bulk','h2','h4',5000000)]]))
                job('/v1/telemetry/start',{'instance_id':original,'duration_s':600})
                time.sleep(4)
                pilots=[twins.capture(original,10)['window'] for _ in range(2)]
                case['healthy_windows']=pilots
                baseline={'window_ids':[w['window_id'] for w in pilots],'definition_hash':digest(definition)}
                _reference,policy=twins.pilot_reference(**baseline)
                case['frozen_policy']=policy
                if name in {'primary_0','scale_10','scale_15'}:
                    healthy_request=request(original,baseline,policy)
                    case['healthy_workflow']=workflow(healthy_request)
                    case['healthy_no_unnecessary_repair']=case['healthy_workflow']['state']=='refused' and 'service acceptable' in str(case['healthy_workflow'].get('reasons'))
                agent.traffic_stop(TrafficRunRequest(instance_id=original,run_id=healthy['run_id']))
                recipe={'schema_version':1,'config_version':'recovery_observation_v1','kind':kind,'severity':'high',
                    'warmup_s':3,'measurement_s':900,'bidirectional':False,'variation_ms':0,'high_utilization':False,
                    'traffic_profile':'shared' if kind=='saturation' else 'qos_competing' if kind=='qos' else 'moderate',
                    'critical_bps':2000000 if kind=='qos' else 8000000,'bulk_protocol':protocol,'packet_size':1200,'seed':20261016+repetition}
                # Existing API stores setup labels only in ground_truth. The
                # following diagnosis/twin calls receive no recipe or label.
                case['stimulus_receipt']=job('/v1/laboratory/scenarios/start',{'instance_id':original,'scenario':recipe})
                time.sleep(5)
                impaired=twins.capture(original,10)['window']; case['impaired_window']=impaired
                job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':not trained})
                body=request(original,baseline,policy); active_workflow=body['workflow_id']
                recovery_started=time.monotonic()
                w=workflow(body); case['workflow']=w
                if name.startswith('primary_nochange'):
                    # Keep exactly the same impaired route. Match the fresh
                    # pre/settling/two-window verification protocol, with no
                    # original action. Shadow evaluation is separate overhead.
                    case['no_change_pre_window']=twins.capture(original,10)['window']
                    time.sleep(2)
                    case['no_change_windows']=[twins.capture(original,10)['window'] for _ in range(2)]
                    case['retained_impaired']=True
                if trained and w['state']=='recommended':
                    explanation=w.get('explanation',{})
                    if explanation.get('explanation_id'):
                        end=time.monotonic()+60
                        while explanation.get('status')=='pending' and time.monotonic()<end:
                            explanation=http('/v1/explanations/'+explanation['explanation_id'])
                            if explanation.get('status')=='pending': time.sleep(.5)
                    diag=w.get('diagnosis',{})
                    permitted=(diag.get('status')=='supported' and diag.get('freshness')=='fresh'
                        and diag.get('probability_status')=='calibrated' and (diag.get('confidence') or 0)>=.70
                        and (diag.get('margin') or 0)>=.15 and explanation.get('status')=='ready'
                        and explanation.get('model_id')==diag.get('model_id')
                        and explanation.get('window_id')==diag.get('window_id'))
                    case['trained_application_gate']={'passed':permitted,'diagnosis':diag,'explanation':explanation}
                    if not permitted: apply=False
                if name.startswith('primary_fixed') and w['state']=='recommended':
                    exp=w['candidate_result']; selected=exp['recommendation']['selected_candidate_id']
                    candidate=next(c for c in exp['candidates'] if c['candidate_id']==selected)
                    fixed=[{'pair_id':'critical','from_path':'primary','to_path':'alternative'}]
                    case['fixed_proposal']=fixed
                    if candidate['action']['family']!='reroute' or candidate['logical_diff']!=fixed:
                        case['fixed_policy_refusal']='Fixed proposal differs from the currently qualified selected action; application not requested.'
                        apply=False
                if w['state']=='recommended' and apply:
                    job('/v1/lab/mode',{'mode':'assisted-repair','allow_observed_only':not trained})
                    action='a'+uuid4().hex
                    job('/v1/lab/apply',{'workflow_id':w['workflow_id'],'action_id':action,'request_key':'k'+uuid4().hex})
                    end=time.monotonic()+180
                    while time.monotonic()<end:
                        w=http('/v1/lab/workflows/'+w['workflow_id'])
                        if w['state'] in {'succeeded','rolled_back','failed','refused','interrupted'}: break
                        time.sleep(1)
                    case['workflow']=w
                    try: case['original_action']=http('/v1/lab/actions/'+action)
                    except OSError: pass
                case['state']=case['workflow']['state']
                pre_windows=case['workflow'].get('pre_windows',[])
                critical=next((p for r in case['stimulus_receipt'].get('traffic_runs',[]) for p in r.get('profiles',[])
                    if p['parameters']['profile_id']=='critical'),{})
                anchor=critical.get('client_launch_clock')
                activated=case['stimulus_receipt'].get('laboratory_journal',{}).get('activated_utc')
                if len(pre_windows)>=2 and anchor and activated:
                    detected=pre_windows[1]
                    offset=anchor['utc_epoch_s']-anchor['monotonic_s']
                    if abs(datetime.fromisoformat(detected['at_utc']).timestamp()-detected['end_monotonic_s']-offset)<=.25:
                        fault_start_mono=datetime.fromisoformat(activated).timestamp()-offset
                        case['live_detection_timing']={'fault_start_utc':activated,'detection_utc':detected['at_utc'],
                            'delay_ms':(detected['end_monotonic_s']-fault_start_mono)*1000,
                            'criterion':'Second persistent violating coordinator window',
                            'source':'Current packet experiment; monotonic delay via contemporaneous owned launch clock, UTC offset consistency <=250 ms'}
                if case.get('retained_impaired'): case['state']='retained_impaired'
                if case.get('fixed_policy_refusal'): case['state']='rejected_by_safety_policy'
                if trained and not case.get('trained_application_gate',{}).get('passed') and w['state']=='recommended':
                    case['state']='refused_by_model_gates'
                case['recovery_total_ms']=(time.monotonic()-recovery_started)*1000
                case['twin_evaluation_ms']=(case['workflow'].get('candidate_result') or {}).get('elapsed_ms')
                with store.connection() as db:
                    case['action_count']=db.execute('SELECT count(*) FROM lab_action_state WHERE instance_id=?',(original,)).fetchone()[0]
                if name.startswith('primary_'): summarize(case)
                if name in {'loss','saturation','qos','latency_tcp'}:
                    report['fault_qualification'].append({'fault':kind,'bulk_protocol':protocol,'critical_protocol':'udp',
                        'switches':size,'state':case['state'],'reasons':case['workflow'].get('reasons'),
                        'original_application_attempted':False,'source_episode':case['episode_id']})
                if name in {'primary_0','scale_10','scale_15'}:
                    report['scale_results'].append({'switches':size,'episode_id':case['episode_id'],'repetitions':1,
                        'healthy_rtt_ms':sum(w['features']['rtt_mean_ms'] for w in pilots)/len(pilots),
                        'impaired_rtt_ms':impaired['features'].get('rtt_mean_ms'),
                        'construction_ms':case['construction_ms'],
                        'twin_construction_ms':(case['workflow'].get('candidate_result') or {}).get('twin_construction_ms'),
                        'twin_evaluation_ms':case.get('twin_evaluation_ms'),
                        'healthy_coverage':min(w['data_quality']['coverage_fraction'] for w in pilots),
                        'fault_coverage':impaired['data_quality']['coverage_fraction'],
                        'cpu_busy_fraction':impaired['features'].get('cpu_busy_fraction'),
                        'memory_used_fraction':impaired['features'].get('memory_used_fraction'),
                        'state':case['state'],'model_transfer':'Five-switch training only; larger-size transfer unvalidated',
                        'original_repair_state':case.get('original_action',{}).get('state'),
                        'original_post_rtt_ms':sum(p['window']['features']['rtt_mean_ms'] for p in case.get('original_action',{}).get('post_windows',[]))/len(case['original_action']['post_windows']) if case.get('original_action',{}).get('post_windows') else None,
                        'measurement_plane':'original healthy/fault and separate twin evaluation','workload':'8/5 Mbps UDP'})
            except Exception as exc:  # noqa: BLE001 - preserve every attempted packet trial
                case.update(state='failed',error=str(exc),traceback=traceback.format_exc())
                print(name+': '+str(exc),flush=True)
                report['errors'].append({'case':name,'error':str(exc)})
            finally:
                if active_workflow:
                    try:
                        http('/v1/lab/automation/stop',{})
                        end=time.monotonic()+90
                        while time.monotonic()<end:
                            w=http('/v1/lab/workflows/'+active_workflow)
                            # A recommendation has finished evaluation and no action was submitted.
                            if w['state'] in {'recommended','succeeded','rolled_back','failed','refused','interrupted'}: break
                            time.sleep(.5)
                    except Exception as exc:  # noqa: BLE001 - retain cleanup diagnostics
                        case['coordinator_cleanup_error']=str(exc)
                for path in ('/v1/telemetry/stop','/v1/laboratory/scenarios/reset'):
                    try: job(path,{'instance_id':original})
                    except Exception as exc:  # noqa: BLE001 - retain scoped cleanup failure
                        case.setdefault('cleanup_errors',[]).append(str(exc))
                try: case['cleanup']=agent.network_cleanup(InstanceRequest(instance_id=original))
                except Exception as exc:  # noqa: BLE001 - retain scoped cleanup failure
                    case.setdefault('cleanup_errors',[]).append(str(exc))
                try: job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
                except Exception as exc:  # noqa: BLE001 - retain control reset failure
                    case.setdefault('cleanup_errors',[]).append(str(exc))
                if name in {'primary_0','scale_10','scale_15'} and not any(r['episode_id']==case['episode_id'] for r in report['scale_results']):
                    report['scale_results'].append({'switches':size,'episode_id':case['episode_id'],'state':case['state'],
                        'reason':case.get('error') or case.get('reason'),'healthy_rtt_ms':None,'impaired_rtt_ms':None,
                        'measurement_source':'Actual attempted packet experiment; failed stage retained'})
                if name in {'loss','saturation','qos','latency_tcp'} and not any(r['source_episode']==case['episode_id'] for r in report['fault_qualification']):
                    report['fault_qualification'].append({'fault':kind,'bulk_protocol':protocol,'switches':size,
                        'state':case['state'],'reasons':case.get('error'),'original_application_attempted':False,'source_episode':case['episode_id']})
                case.update(finished=True,ended_utc=utc_now(),total_trial_ms=(time.monotonic()-start)*1000)
                if name.startswith('primary_') and not any(r['episode_id']==case['episode_id'] for r in report['baseline_results']):
                    summarize(case)
                save()
        failures=[name for name,c in report['cases'].items() if c['state'] in {'failed','blocked'} or c.get('cleanup_errors')]
        report['execution_finished']=True
        report['failed_cases']=failures
        report['status']='completed_with_failures' if failures else 'complete'
        report['evidence_qualified']=not failures
    finally:
        try:
            http('/v1/lab/automation/stop',{})
            report['final_control']=job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
        except Exception as exc:  # noqa: BLE001 - final stop failure is visible in evidence
            report['errors'].append({'final_stop_error':str(exc)})
        save()
    return 0 if report.get('status')=='complete' else 1


if __name__=='__main__': sys.exit(main())
