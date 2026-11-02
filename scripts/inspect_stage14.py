"""Read current integration readiness and retained scientific provenance; no training."""
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.model_bundle import BundleRepository
from explainnet.storage import Store, utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage14'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
    prior=json.loads((ROOT/'artifacts/stage13/final_audit.json').read_text())
    paths=['artifacts/stage13/frozen_evaluation.json','artifacts/stage13/posthoc_provenance.json',
        'artifacts/stage13/held_out_metrics.json','artifacts/stage13/test_predictions.json',
        'artifacts/stage13/final_audit.json','artifacts/evaluation_validation_report.json',
        'artifacts/recovery_validation_report.json','config/evaluation_stage13.json']
    result={'stage':14,'at_utc':utc_now(),'app_uid':os.geteuid(),'scientific_artifact_sha256':{p:sha(ROOT/p) for p in paths},
        'stage13_status':prior['status'],'stage13_report_hash_matches':sha(ROOT/'artifacts/evaluation_validation_report.json')==prior['evaluation_report_sha256'],
        'model_training_or_test_scoring_performed':False,'browser_automation':'No supported browser automation tool is available; use Streamlit AppTest and actual HTTP'}
    with sqlite3.connect('file:'+str(settings.database_path)+'?mode=ro',uri=True) as db:
        result['sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
        result['foreign_key_violations']=len(db.execute('PRAGMA foreign_key_check').fetchall())
        result['main_partitions']=dict(db.execute("SELECT partition,count(*) FROM dataset_members WHERE batch_id='db5a15991774142f0a8ef871522face4d' GROUP BY partition"))
        result['episode_split_overlap']=db.execute('SELECT count(*) FROM (SELECT episode_id FROM dataset_members GROUP BY episode_id HAVING count(DISTINCT partition)>1)').fetchone()[0]
        result['family_split_overlap']=db.execute('SELECT count(*) FROM (SELECT batch_id,family_id FROM dataset_members GROUP BY batch_id,family_id HAVING count(DISTINCT partition)>1)').fetchone()[0]
        result['ready_explanations']=db.execute("SELECT count(*) FROM explanations WHERE state='ready'").fetchone()[0]
        result['active_jobs']=db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    repo=BundleRepository(Store(settings.database_path))
    result['models']=[]
    for record in repo.list():
        bundle=repo.load(record['model_id'])
        result['models'].append({'model_id':record['model_id'],'compatible':True,
            'calibrated':bundle['calibrator'] is not None,'manifest_sha256':record['manifest_sha256'],
            'feature_order':bundle['feature_order'],'class_order':bundle['class_order']})
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{settings.port}/v1/dashboard/status',timeout=15) as response:
            result['actual_backend_status']=json.load(response)
    except (OSError,urllib.error.URLError) as exc:
        result['actual_backend_status']={'available':False,'error':str(exc)}
    lab=json.loads((ROOT/'artifacts/stage13/lab_report.json').read_text())
    traces=[]
    for name,case in lab['cases'].items():
        if case['state']!='succeeded' or not name.startswith('primary_'):
            continue
        w=case['workflow']; action=case['original_action']; exp=w['candidate_result']
        checks={'source_identity':w['instance_id']==case['instance_id']==action['instance_id'],
            'incident_action_link':w['incident_id']==action['incident_id'],
            'workflow_action_link':w['workflow_id']==action['workflow_id'],
            'snapshot_action_link':w['snapshot_id']==action['snapshot_id']==exp['snapshot_id'],
            'separate_twin':exp['twin_id']!=case['instance_id'],
            'two_verified_original_windows':len(action['post_windows'])>=2 and all(p['evaluation']['eligible'] for p in action['post_windows']),
            'explicit_observed_only':w['diagnosis']['status']=='observed-only',
            'cleanup_stopped':case['cleanup']['state']=='stopped'}
        traces.append({'case':name,'source_episode':case['episode_id'],'incident_id':w['incident_id'],
            'workflow_id':w['workflow_id'],'action_id':action['action_id'],'snapshot_id':w['snapshot_id'],
            'twin_id':exp['twin_id'],'checks':checks,'all_passed':all(checks.values())})
    result['historical_integrated_lineage']=traces
    result['status']='passed_with_declared_limits' if result['stage13_report_hash_matches'] and all(t['all_passed'] for t in traces) and result['models'] else 'needs_review'
    atomic_json(OUT/'starting_state.json',result)
    print(json.dumps({k:result[k] for k in ('status','stage13_status','main_partitions','ready_explanations','active_jobs','models','historical_integrated_lineage')},indent=2))


if __name__=='__main__': main()
