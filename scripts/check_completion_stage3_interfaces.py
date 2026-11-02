"""Read campaign/dashboard identities; optionally reload only idle trained API/UI."""
import argparse
import json
import subprocess
import sys
import urllib.request

from explainnet.agent import AgentClient
from explainnet.application_profiles import PROFILES, ROOT
from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage3'


def read(cfg,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{cfg.port}'+path,timeout=15) as response:
        raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('Read-only response budget exceeded')
    return json.loads(raw)


def profile(name):
    cfg=load_settings(PROFILES[name][0]);identity=read(cfg,'/v1/config')
    if identity['config_hash']!=cfg.config_hash:raise ValueError('Profile/API identity mismatch: '+name)
    control=read(cfg,'/v1/lab/control');inventory=AgentClient(cfg.agent_socket).inventory()
    return {'name':name,'configuration':identity,'automatic_repair_enabled':control['auto_enabled'],
        'control':control,'active_model_id':read(cfg,'/v1/models')['active_model_id'],
        'running_instances':[{'instance_id':r['instance_id'],'state':r['state']} for r in inventory['instances'] if r['state']=='running'],
        'owner_inventory_hash':digest(inventory)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--reload-trained',action='store_true')
    args=parser.parse_args();before={name:profile(name) for name in PROFILES}
    receipt={'at_utc':utc_now(),'before':before,'reload_trained':args.reload_trained}
    if args.reload_trained:
        trained=before['trained'];control=trained['control']
        if (trained['running_instances'] or control['auto_enabled'] or control.get('active_workflow_id')
                or control.get('unsettled_action_ids') or control.get('cleanup_pending_workflow_ids') or control.get('monitor_active')):
            raise ValueError('Trained profile not idle; no service was stopped')
        receipt['lifecycle']=[]
        for action in ['stop','start']:
            result=subprocess.run([sys.executable,'scripts/manage_app.py','--config',str(PROFILES['trained'][0]),action],
                cwd=ROOT,capture_output=True,text=True,timeout=300,check=False)
            receipt['lifecycle'].append({'action':action,'exit_code':result.returncode})
            atomic_json(OUT/'interface_checks.json',receipt)
            if result.returncode:raise RuntimeError('Scoped ordinary launcher failed: '+result.stderr[-1000:])
    after={name:profile(name) for name in PROFILES}
    for name in PROFILES:
        if before[name]['owner_inventory_hash']!=after[name]['owner_inventory_hash']:
            raise ValueError('Root owner inventory changed across read-only interface refresh: '+name)
        if before[name]['active_model_id']!=after[name]['active_model_id']:raise ValueError('Existing active model changed')
        if after[name]['automatic_repair_enabled']:raise ValueError('Automatic repair unexpectedly enabled')
    cfg=load_settings(PROFILES['trained'][0]);artifact=read(cfg,'/v1/dashboard/evidence/completion3')['evidence']
    pipeline=json.loads((OUT/'pipeline.json').read_text());sup=json.loads((OUT/'runtime/supervisor.json').read_text())
    receipt.update(after=after,status='passed',campaign_artifact={'status':artifact['status'],'accepted_windows':artifact['accepted_windows'],
        'dataset_ready':artifact['dataset_ready'],'new_heldout_metrics_present':bool(artifact.get('held_out_metrics'))},
        campaign={'controller_pid':pipeline['pid'],'supervisor_pid':sup['supervisor_pid'],'agent_pid':sup['agent_pid'],
            'api_pid':sup['api_pid'],'batch_id':sup['batch_id'],'state':sup['state'],'accepted_windows':sup['accepted_windows']})
    atomic_json(OUT/'interface_checks.json',receipt)
    print(json.dumps({'status':receipt['status'],'artifact':receipt['campaign_artifact'],'campaign':receipt['campaign'],
        'normal_profiles':{n:{'active_model_id':v['active_model_id'],'automatic_repair_enabled':v['automatic_repair_enabled'],
            'running_instances':v['running_instances']} for n,v in after.items()}},indent=2))


if __name__=='__main__':main()
