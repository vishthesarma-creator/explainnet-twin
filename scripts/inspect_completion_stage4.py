"""Capture actual identities/evidence; one safe campaign-lock refusal, no packets."""
import json
import sqlite3
import time
import urllib.request

from explainnet.application_profiles import PROFILES, ROOT
from explainnet.completion_client import CompletionClient
from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage4'


def get(cfg,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{cfg.port}'+path,timeout=20) as response:return json.load(response)


def main():
    OUT.mkdir(exist_ok=True)
    identities={}
    for name,(path,port) in PROFILES.items():
        cfg=load_settings(path)
        identities[name]={'dashboard_url':f'http://127.0.0.1:{port}','configuration':get(cfg,'/v1/config'),
            'control':get(cfg,'/v1/lab/control'),'active_model_id':get(cfg,'/v1/models')['active_model_id']}
        if identities[name]['control']['auto_enabled']:raise ValueError('Automatic repair must remain off')
    cfg=load_settings(PROFILES['trained'][0]);host=get(cfg,'/v1/demo/host-status')
    with sqlite3.connect('file:'+str(cfg.database_path)+'?mode=ro',uri=True) as db:
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            for table in ['jobs','recovery_workflows','lab_action_state','telemetry_windows','twin_snapshots']}
    identity={'at_utc':utc_now(),'profiles':identities,'host':host,'database_counts':counts}
    atomic_json(OUT/'identity.json',identity)
    if host['active'] and not (OUT/'guard_refusal.json').exists():
        api=CompletionClient(PROFILES['trained'][0],OUT/'jobs');started=time.monotonic()
        try:
            api.job('nominal_campaign_guard','/v1/demo/reference',{'instance_id':'stage4_guard_probe'})
        except RuntimeError as exc:
            if 'Shared emulator campaign is active' not in str(exc):raise
            atomic_json(OUT/'guard_refusal.json',{'status':'expected_refusal','at_utc':utc_now(),'error':str(exc),
                'elapsed_ms':(time.monotonic()-started)*1000,'native_capture_started':False,
                'scope':'Actual API/job path refused before any agent or native packet capture; not a fidelity/repair success'})
        else:raise RuntimeError('Campaign guard unexpectedly allowed nominal capture')
    for name in ['completion_stage1_validation.json','completion_stage2_validation.json','completion_stage3_validation.json','evaluation_validation_report.json']:
        source=ROOT/'artifacts'/name
        if not (OUT/name).exists():(OUT/name).write_bytes(source.read_bytes())
    print(json.dumps({'host':host,'auto_disabled':True,'profiles':{k:v['active_model_id'] for k,v in identities.items()},
        'safe_guard_receipt':(OUT/'guard_refusal.json').exists()}))


if __name__=='__main__':main()
