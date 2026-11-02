"""Read-only terminal state and identity checks after bounded stage-2 verification."""
import json
import sqlite3
import urllib.request

from explainnet.agent import AgentClient
from explainnet.app_launcher import validate_binding
from explainnet.application_profiles import PROFILES, ROOT
from explainnet.config import load_settings
from explainnet.storage import utc_now


def get(url):
    with urllib.request.urlopen(url,timeout=20) as response:
        return json.load(response)


def main():
    states = {}
    for name,(path,port) in PROFILES.items():
        cfg = load_settings(path); url = f'http://127.0.0.1:{cfg.port}'
        binding = validate_binding(cfg,url)
        control,model = get(url+'/v1/lab/control'),get(url+'/v1/models')
        assert control['mode']=='recommend' and not control['auto_enabled'] and not control['allow_observed_only']
        assert not control.get('active_workflow_id') and not control.get('unsettled_action_ids')
        assert not control.get('cleanup_pending_workflow_ids') and not control.get('monitor_active')
        agent = AgentClient(cfg.agent_socket)
        inventory = agent.inventory()
        active = [r for r in inventory['instances'] if r['state']=='running']
        assert not active if name=='trained' else all(r['instance_id']=='teachlive_cacc533e6c' for r in active)
        assert (model['active_model_id']=='m20261016T074751_a92c0db8f44e') if name=='trained' else model['active_model_id'] is None
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=10) as response:
            ui = response.read().decode()
        db = sqlite3.connect('file:'+str(cfg.database_path)+'?mode=ro',uri=True)
        states[name] = {'binding':binding,'control':control,'active_model_id':model['active_model_id'],
            'dashboard_health':ui,'api_health':get(url+'/v1/health'),
            'verified_live_originals':[{'instance_id':r['instance_id'],'state':r['state'],
                'live_verified':r.get('live_verified'),'role':r.get('role')} for r in active],
            'collectors':[get(url+'/v1/telemetry/'+r['instance_id']+'/status') for r in active],
            'dataset_partition_counts':dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition')),
            'model_registration_count':db.execute('SELECT count(*) FROM model_bundles').fetchone()[0]}
    episodes = []
    for name in ['healthy','latency','loss','saturation','qos','automatic_latency']:
        path = ROOT/'artifacts/completion_stage2/verified'/(name+'.json')
        case = json.loads(path.read_text())
        assert case['finished'] and case['cleanup']['state']=='stopped'
        episodes.append({'case':name,'instance_id':case['instance_id'],'historical_workflow_result':case['state'],
            'cleanup_state':case['cleanup']['state'],'undo_state':(case.get('undo') or {}).get('state')})
    report = {'at_utc':utc_now(),'status':'passed','profiles':states,'verification_episodes':episodes,
        'automatic_repair_disabled':True,'canonical_collector_or_traffic_expiry':None,
        'new_stage2_resources':'all scoped verification originals/twins stopped; journals/native evidence preserved',
        'unrelated_profile':'existing observed-only original untouched; its earlier finite traffic/collector have expired',
        'foreground_terminals_required':False,'keep_wsl_running_for_services':True,
        'visual_check':{'status':'incomplete','reason':'Computer Use stopped: current Brave URL could not be determined confidently. No further UI automation or fallback used.',
            'fresh_stage2_screenshots':[],'prior_evidence':'artifacts/completion_stage1/browser/report.json; not a fresh post-integration visual check'}}
    (ROOT/'artifacts/completion_stage2/final_state.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'profiles':{k:{'active_model':v['active_model_id'],
        'auto':v['control']['auto_enabled'],'active_workflow':v['control'].get('active_workflow_id'),
        'live_originals':v['verified_live_originals'],'partitions':v['dataset_partition_counts']} for k,v in states.items()}},indent=2))


if __name__ == '__main__': main()
