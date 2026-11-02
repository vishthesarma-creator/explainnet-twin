"""Prepare or explicitly clean one healthy teacher source; never auto-cleans."""
import argparse
import json
import time
from uuid import uuid4

from explainnet.application_profiles import PROFILES, ROOT
from explainnet.completion_client import CompletionClient
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage4'
FILE=OUT/'demo_session.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','status','cleanup','complete-preparation','renew'])
    args=parser.parse_args();api=CompletionClient(PROFILES['trained'][0],OUT/'demo_jobs')
    session=json.loads(FILE.read_text()) if FILE.exists() else None
    if args.action=='status':
        if not session:raise ValueError('No prepared demo session')
        value={'session':session,'collector':api.get('/v1/telemetry/'+session['instance_id']+'/status'),
            'control':api.get('/v1/lab/control')};print(json.dumps(value,indent=2));return
    ctl=api.get('/v1/lab/control')
    if any(ctl.get(k) for k in ['active_workflow_id','unsettled_action_ids','monitor_active','cleanup_pending_workflow_ids']):
        raise ValueError('Workflow/action/cleanup is unsettled; no new demo operation submitted')
    if args.action in {'complete-preparation','renew'}:
        if not session:raise ValueError('No recorded teacher source')
        instance=session['instance_id']
        journal=api.get('/v1/laboratory/scenarios/'+instance).get('laboratory_journal') or {}
        if journal.get('state') not in {None,'stopped'}:raise ValueError('Active scenario prohibits healthy renewal; restore explicitly first')
        if api.get('/v1/dashboard/reversible/'+instance).get('available'):raise ValueError('Undo kept action before renewal')
        namespace='reference_fix' if args.action=='complete-preparation' else 'renew_'+uuid4().hex[:8]
        api=CompletionClient(PROFILES['trained'][0],OUT/'demo_jobs'/namespace)
        if args.action=='renew':
            api.job('collector_stop','/v1/telemetry/stop',{'instance_id':instance})
            actual=api.get('/v1/traffic/'+instance+'/'+session['traffic_run_id'])
            if actual['state']=='running':api.job('traffic_stop','/v1/traffic/stop',{'instance_id':instance,'run_id':session['traffic_run_id']})
            profiles=[{'schema_version':1,'config_version':'workflow_observation_v1','profile_id':p,'source_host':a,'target_host':b,
                'protocol':'udp','offered_bps':rate,'packet_size':1200,'duration_s':900,'warmup_s':3,'stream_receiver':True}
                for p,a,b,rate in [('critical','h1','h3',8_000_000),('bulk','h2','h4',5_000_000)]]
            session['traffic_run_id']=api.job('traffic','/v1/traffic/workload/start',{'instance_id':instance,'profiles':profiles})['run_id']
            atomic_json(FILE,session)
        if not api.get('/v1/telemetry/'+instance+'/status').get('live'):
            api.job('collector','/v1/telemetry/start',{'instance_id':instance,'duration_s':900})
        time.sleep(4)
        reference=api.job('nominal_reference','/v1/demo/reference',{'instance_id':instance},timeout=180)
        session.update(state='healthy_running',reference_created_utc=reference['created_utc'],prepared_utc=utc_now(),collector=api.get('/v1/telemetry/'+instance+'/status'))
        atomic_json(FILE,session);print(json.dumps({'state':session['state'],'instance_id':instance,'collector':session['collector']}));return
    if args.action=='prepare':
        if api.get('/v1/demo/host-status')['active']:raise ValueError('Shared campaign is active; no demonstration started')
        if not api.get('/v1/models')['active_model_id']:raise ValueError('Compatible trained model required; no observed-only fallback')
        if session:raise ValueError('Existing session retained; use status and explicit cleanup, no automatic duplicate preparation')
        instance='demo4_'+uuid4().hex[:10]
        session={'created_utc':utc_now(),'instance_id':instance,'profile':'trained','api_url':'http://127.0.0.1:38223',
            'dashboard_url':'http://127.0.0.1:8501','state':'preparing','automatic_cleanup':False}
        atomic_json(FILE,session)
        api.post('/v1/lab/automation/stop',{})
        api.job('safe_mode','/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
        api.job('create','/v1/networks/start',{'instance_id':instance,'switches':5})
        profiles=[{'schema_version':1,'config_version':'workflow_observation_v1','profile_id':p,'source_host':a,'target_host':b,
            'protocol':'udp','offered_bps':rate,'packet_size':1200,'duration_s':900,'warmup_s':3,'stream_receiver':True}
            for p,a,b,rate in [('critical','h1','h3',8_000_000),('bulk','h2','h4',5_000_000)]]
        traffic=api.job('traffic','/v1/traffic/workload/start',{'instance_id':instance,'profiles':profiles})
        session['traffic_run_id']=traffic['run_id'];atomic_json(FILE,session)
        api.job('collector','/v1/telemetry/start',{'instance_id':instance,'duration_s':900})
        time.sleep(4)
        reference=api.job('nominal_reference','/v1/demo/reference',{'instance_id':instance},timeout=180)
        session.update(state='healthy_running',reference_created_utc=reference['created_utc'],prepared_utc=utc_now())
        data=api.get('/v1/dashboard/telemetry/'+instance+'?limit=4')
        session['collector']=data['collector']
        session['measurement_evidence']=[{'window_id':w['window_id'],'at_utc':w['at_utc'],'complete':w['complete'],
            'inference_ready':w['inference_ready'],'features':{k:w['features'].get(k) for k in ['rtt_mean_ms','critical_goodput_bps','udp_loss_fraction']}}
            for w in data['windows'] if w['complete']][:2]
        atomic_json(FILE,session)
        print(json.dumps({'state':session['state'],'instance_id':instance,'measurements':session['measurement_evidence'],
            'collector':data['collector'],'automatic_repair_enabled':api.get('/v1/lab/control')['auto_enabled']},indent=2))
    else:
        if not session:raise ValueError('No recorded source to clean')
        instance=session['instance_id']
        if api.get('/v1/dashboard/reversible/'+instance).get('available'):raise ValueError('Use explicit Undo before cleanup of a kept repair')
        api.post('/v1/lab/automation/stop',{})
        api.job('cleanup_collector','/v1/telemetry/stop',{'instance_id':instance})
        journal=api.get('/v1/laboratory/scenarios/'+instance).get('laboratory_journal') or {}
        if journal.get('state') not in {None,'stopped'}:api.job('cleanup_scenario','/v1/laboratory/scenarios/reset',{'instance_id':instance})
        api.job('cleanup_network','/v1/networks/cleanup',{'instance_id':instance})
        api.job('cleanup_mode','/v1/lab/mode',{'mode':'recommend','allow_observed_only':False})
        session.update(state='explicitly_cleaned',cleaned_utc=utc_now());atomic_json(FILE,session)
        print('Only the recorded teacher source was cleaned; evidence and other owners are preserved.')


if __name__=='__main__':main()
