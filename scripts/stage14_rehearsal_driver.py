"""One fresh explicitly observed-only laboratory rehearsal; existing services enforce safety."""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.config import load_network, load_settings
from explainnet.dataset_export import atomic_json
from explainnet.network_contracts import InstanceRequest, ProbeRequest, TrafficRunRequest
from explainnet.storage import Store, utc_now
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest

ROOT=Path(__file__).resolve().parents[1]
TERMINAL={'succeeded','rolled_back','failed','refused','interrupted'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--tag',required=True)
    parser.add_argument('--preview-s',type=int,default=5)
    args=parser.parse_args()
    if not 0<=args.preview_s<=30: raise ValueError('Preview must be bounded to 0..30 seconds')
    cfg=load_settings(args.config); out=args.config.parent
    store=Store(cfg.database_path); agent=AgentClient(cfg.agent_socket)
    twins=TwinService(store,agent,cfg.objective)
    original='demo14_'+args.tag
    report={'schema_version':1,'stage':14,'tag':args.tag,'status':'running','started_utc':utc_now(),
        'instance_id':original,'app_uid':os.geteuid(),'mode':'observed-only laboratory opt-in',
        'scope':'The isolated rehearsal intentionally has no active classifier. Registered calibrated model/SHAP compatibility is verified separately against the canonical backend; trained original actuation remains unqualified.',
        'trained_model_claim':False,'lab_test_hooks':False,'errors':[],'requests':[],'progress':[],
        'measurement_source':'Fresh Mininet/OVS/tc/iperf packet experiment; original and twin planes separate'}
    start=time.monotonic(); active=None
    def save(): atomic_json(out/'report.json',report)
    def http(path,body=None):
        req=urllib.request.Request(f'http://127.0.0.1:{cfg.port}'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json','Idempotency-Key':'s14'+uuid4().hex})
        with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
    def job(path,body):
        submitted=http(path,body); report['requests'].append({'path':path,'job_id':submitted['job_id'],'at_utc':utc_now()}); save()
        end=time.monotonic()+130
        while time.monotonic()<end:
            value=http('/v1/jobs/'+submitted['job_id'])
            if value['state'] in {'succeeded','failed','canceled','interrupted'}:
                if value['state']!='succeeded': raise RuntimeError(str(value.get('error') or value['state']))
                return value['result']
            time.sleep(.4)
        raise TimeoutError('Job deadline; outcome unknown and not retried')
    def sample_count():
        with store.connection() as db:
            return db.execute('SELECT count(*) FROM telemetry_samples s JOIN telemetry_collectors c ON c.run_id=s.run_id WHERE c.instance_id=?',(original,)).fetchone()[0]
    def workflow(body):
        job('/v1/lab/workflow',body)
        end=time.monotonic()+920; previous=None; last_check=0
        while time.monotonic()<end:
            w=http('/v1/lab/workflows/'+body['workflow_id'])
            if w['state']!=previous:
                print(body['workflow_id']+': '+w['state'],flush=True); previous=w['state']
            if time.monotonic()-last_check>=10:
                t=time.monotonic(); health=http('/v1/health')
                report['progress'].append({'at_utc':utc_now(),'workflow_id':body['workflow_id'],
                    'state':w['state'],'collector_samples':sample_count(),
                    'health_response_ms':(time.monotonic()-t)*1000,'worker_live':health['worker_live']})
                last_check=time.monotonic(); save()
            if w['state'] in TERMINAL|{'recommended'}: return w
            time.sleep(.7)
        raise TimeoutError('Bounded workflow deadline')
    def request(baseline,policy):
        return {'instance_id':original,'workflow_id':'w'+uuid4().hex,'request_key':'k'+uuid4().hex,
            'baseline':baseline,'policy':policy,'max_repairs':1,'max_hypotheses':2,'timeout_s':900}
    save()
    try:
        end=time.monotonic()+120
        while time.monotonic()<end:
            try:
                if http('/v1/health')['worker_live']: break
            except OSError: pass
            time.sleep(.3)
        else: raise TimeoutError('API readiness deadline')
        report['initial_health']=http('/v1/health')
        report['initial_capabilities']=http('/v1/capabilities')
        assert report['initial_health']['agent']=='available'
        report['initial_control']=http('/v1/lab/control')
        assert not report['initial_control']['auto_enabled'] and not report['initial_control']['allow_observed_only']
        report['initial_model_status']=http('/v1/models')
        assert not report['initial_model_status'].get('active_model_id')
        report['construction']=job('/v1/networks/start',{'instance_id':original})
        report['connectivity']=agent.network_probe(ProbeRequest(instance_id=original,source_host='h1',target_host='h3'))
        assert report['connectivity']['passed']
        healthy=job('/v1/traffic/start',{'instance_id':original,'profile_ids':['critical','bulk'],'stream_receiver':True})
        # The explicit profile file supplies exactly 8/5 Mbps UDP for healthy and fault periods.
        report['healthy_traffic']=healthy
        job('/v1/telemetry/start',{'instance_id':original,'duration_s':600})
        time.sleep(4)
        pilots=[twins.capture(original,10)['window'] for _ in range(2)]
        report['healthy_windows']=pilots
        definition=load_network(cfg.topology_file).model_dump()
        baseline={'window_ids':[w['window_id'] for w in pilots],'definition_hash':digest(definition)}
        _,policy=twins.pilot_reference(**baseline)
        report['baseline']=baseline; report['frozen_policy']=policy
        report['healthy_workflow']=workflow(request(baseline,policy))
        assert report['healthy_workflow']['state']=='refused' and 'service acceptable' in str(report['healthy_workflow'].get('reasons'))
        report['healthy_no_unnecessary_repair']=True
        t=time.monotonic(); report['stop_ack']=http('/v1/lab/automation/stop',{})
        report['stop_response_ms']=(time.monotonic()-t)*1000
        agent.traffic_stop(TrafficRunRequest(instance_id=original,run_id=healthy['run_id']))
        recipe={'schema_version':1,'config_version':'recovery_observation_v1','kind':'latency','severity':'high',
            'warmup_s':3,'measurement_s':900,'bidirectional':False,'variation_ms':0,'high_utilization':False,
            'traffic_profile':'moderate','critical_bps':8000000,'bulk_protocol':'udp','packet_size':1200,'seed':20261019}
        # This separate setup endpoint stores injector labels only in ground_truth.
        report['stimulus_receipt']=job('/v1/laboratory/scenarios/start',{'instance_id':original,'scenario':recipe})
        time.sleep(5)
        report['impaired_window']=twins.capture(original,10)['window']
        job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':True})
        body=request(baseline,policy); active=body['workflow_id']
        w=workflow(body); report['workflow']=w
        if w['state']=='recommended':
            job('/v1/lab/mode',{'mode':'assisted-repair','allow_observed_only':True})
            before_jobs=len(report['requests'])
            report['application_preview']=http('/v1/dashboard/applicable/'+active)
            assert len(report['requests'])==before_jobs
            if not report['application_preview']['available']:
                raise RuntimeError('Backend read-only preview refused: '+report['application_preview']['reason'])
            save(); time.sleep(args.preview_s)
            action_id='a'+uuid4().hex
            job('/v1/lab/apply',{'workflow_id':active,'action_id':action_id,'request_key':'k'+uuid4().hex})
            end=time.monotonic()+180
            while time.monotonic()<end:
                w=http('/v1/lab/workflows/'+active)
                if w['state'] in TERMINAL: break
                time.sleep(.7)
            else: raise TimeoutError('Application/verification outcome unknown; not retried')
            report['workflow']=w
            report['action_before_undo']=http('/v1/lab/actions/'+action_id)
            if w['state']=='succeeded':
                report['undo_applicability']=http('/v1/dashboard/reversible/'+original)
                assert report['undo_applicability']['available']
                report['undo']=job('/v1/lab/undo',{'instance_id':original,'action_id':action_id,'request_key':'u'+uuid4().hex})
                report['restored_window']=twins.capture(original,10)['window']
                report['status']='verified_repair_then_undo'
            else:
                report['status']='completed_with_'+w['state']
        else:
            report['status']='completed_with_'+w['state']
        job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
        save()
        result=subprocess.run([sys.executable,str(ROOT/'scripts/check_stage14_dashboard.py'),'--config',str(args.config),
            '--output',str(out/'dashboard.json')],cwd=ROOT,timeout=700,check=False)
        report['dashboard_exit_code']=result.returncode
        if result.returncode: raise RuntimeError('Rehearsal six-page dashboard check failed; see retained logs')
        progress=[p for p in report['progress'] if p['state']=='validating']
        report['collector_continued_during_twin']=len(progress)>=2 and progress[-1]['collector_samples']>progress[0]['collector_samples']
        report['health_latency_ms']={'max':max(p['health_response_ms'] for p in report['progress']),
            'mean':statistics.mean(p['health_response_ms'] for p in report['progress'])}
    except Exception as exc:  # noqa: BLE001 - keep the failed bounded attempt, never fabricate success
        report.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        report['errors'].append(str(exc)); print(traceback.format_exc(),flush=True)
    finally:
        try: report['stop_final']=http('/v1/lab/automation/stop',{})
        except Exception as exc: report['errors'].append('stop: '+str(exc))  # noqa: BLE001
        if active:
            end=time.monotonic()+100
            while time.monotonic()<end:
                try:
                    if http('/v1/lab/workflows/'+active)['state'] in TERMINAL|{'recommended'}: break
                except OSError: break
                time.sleep(.5)
        for path in ('/v1/telemetry/stop','/v1/laboratory/scenarios/reset'):
            try: job(path,{'instance_id':original})
            except Exception as exc: report['errors'].append('cleanup '+path+': '+str(exc))  # noqa: BLE001
        try: report['cleanup']=agent.network_cleanup(InstanceRequest(instance_id=original))
        except Exception as exc: report['errors'].append('owned cleanup: '+str(exc))  # noqa: BLE001
        try: report['final_control']=job('/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
        except Exception as exc: report['errors'].append('mode reset: '+str(exc))  # noqa: BLE001
        report.update(ended_utc=utc_now(),total_elapsed_ms=(time.monotonic()-start)*1000)
        save()
    return 1 if report['status']=='failed' or report['errors'] else 0


if __name__=='__main__': raise SystemExit(main())
