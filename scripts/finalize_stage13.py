#!/usr/bin/env python3
"""Final read-only native/data audits and consistent evidence archive; OS Python only."""
import hashlib
import json
import sqlite3
import subprocess
import tarfile
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'
BATCH='db5a15991774142f0a8ef871522face4d'


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    config=read(ROOT/'artifacts/stage6/runtime/config.json')
    data=Path(config['data_dir'])
    evaluation=read(ROOT/'artifacts/evaluation_validation_report.json')
    lab=read(OUT/'lab_report.json')
    frozen=read(OUT/'frozen_evaluation.json')
    checks=read(OUT/'software_checks.json')
    shap=read(OUT/'backend_shap.json')
    dashboard=read(OUT/'dashboard_check.json')
    assert checks['status']=='passed'
    assert dashboard['status']=='passed' and dashboard['render_did_not_submit_jobs']
    assert sha(ROOT/'src/explainnet/evaluation.py')==frozen['evaluator_sha256']
    assert sha(ROOT/'config/evaluation_stage13.json')==frozen['configuration_sha256']
    provenance=read(OUT/'posthoc_provenance.json')
    assert provenance['kind']=='post_hoc_dependency_receipt' and not provenance['test_rescored']
    for name,expected in provenance['snapshot']['files'].items():
        path=Path(name)
        assert sha(path if path.is_absolute() else ROOT/path)==expected
    assert lab['status']=='complete'
    with sqlite3.connect('file:'+str(data/'explainnet.sqlite3')+'?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        split_counts=dict(db.execute('SELECT partition,count(*) FROM dataset_members WHERE batch_id=? GROUP BY partition',(BATCH,)))
        assert split_counts=={'train':240,'validation':60,'test':60}
        assert db.execute('SELECT count(DISTINCT episode_id) FROM dataset_members WHERE batch_id=?',(BATCH,)).fetchone()[0]==60
        assert not db.execute('SELECT episode_id FROM dataset_members WHERE batch_id=? GROUP BY episode_id HAVING count(DISTINCT partition)>1',(BATCH,)).fetchall()
        assert not db.execute('SELECT family_id FROM dataset_members WHERE batch_id=? GROUP BY family_id HAVING count(DISTINCT partition)>1',(BATCH,)).fetchall()
        mode=json.loads(db.execute('SELECT payload_json FROM recovery_control WHERE singleton=1').fetchone()[0])
        assert not mode['auto_enabled'] and not mode['allow_observed_only']
        current={r[0]:tuple(r) for r in db.execute('SELECT * FROM dataset_members WHERE batch_id=?',(BATCH,))}
        models=list(db.execute('SELECT model_id FROM model_bundles'))
    with sqlite3.connect('file:'+str(OUT/'before_stage13.sqlite3')+'?mode=ro',uri=True) as db:
        original=list(db.execute('SELECT * FROM dataset_members WHERE batch_id=?',(BATCH,)))
    assert len(original)==192 and all(current[r[0]]==tuple(r) for r in original)
    assert len(shap['cases'])==5 and shap['ready_cases']==5
    for case in shap['cases']:
        explanation=case['explanation']
        assert explanation['status']=='ready' and explanation['model_id']==frozen['model_id']
        assert explanation['additivity_absolute_error']<=explanation['additivity_tolerance']
        assert explanation['background_provenance']['partition']=='train'
    primary=[c for n,c in lab['cases'].items() if n.startswith('primary_')]
    attempts=Counter(c['approach'] for c in primary)
    assert attempts=={'twin_guided':3,'no_change':3,'fixed_rule_with_safety_qualification':3}
    assert len({c['instance_id'] for c in primary})==9
    for name in ('primary_0','scale_10','scale_15'):
        assert lab['cases'][name]['healthy_no_unnecessary_repair']
        assert lab['cases'][name]['connectivity']['passed']
    for case in primary:
        assert case['finished'] and case['cleanup']['state']=='stopped'
    assert {r['switches'] for r in lab['scale_results']}=={5,10,15}
    assert len(lab['fault_qualification'])==4
    assert not lab['final_control']['auto_enabled'] and not lab['final_control']['allow_observed_only']
    native_audits=[]
    for path in (OUT/'labs').glob('*/cleanup_*.json'):
        value=read(path)
        assert value['preexisting_bridges_preserved'] and value['owned_bridges_removed']
        native_audits.append({'file':str(path.relative_to(ROOT)),'sha256':sha(path)})
    assert native_audits
    bridges=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
    assert not bridges,'Unexpected remaining bridges; no global cleanup performed'
    # Snapshot SQLite through its backup API, then archive immutable raw/export
    # files. Never tar an inconsistent live database/WAL pair.
    archive=OUT/('application_evidence_'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'.tar.gz')
    with tempfile.TemporaryDirectory(prefix='stage13-final-',dir='/tmp') as temporary:
        snapshot=Path(temporary)/'explainnet.sqlite3'
        with sqlite3.connect('file:'+str(data/'explainnet.sqlite3')+'?mode=ro',uri=True) as source,sqlite3.connect(snapshot) as target:
            source.backup(target)
        with tarfile.open(archive,'x:gz') as output:
            output.add(snapshot,arcname='data/explainnet.sqlite3')
            for folder in ('raw','datasets','models'):
                if (data/folder).exists(): output.add(data/folder,arcname='data/'+folder)
    result={'stage':13,'status':'passed_with_declared_evaluation_limits','at_utc':datetime.now(UTC).isoformat(),
        'dataset_counts':split_counts,'episodes':60,'preserved_original_members':192,'model_ids':[r[0] for r in models],
        'real_validation_shap_cases':5,'primary_independent_trials_by_approach':dict(attempts),
        'primary_outcomes':{a:dict(Counter(c['state'] for c in primary if c['approach']==a)) for a in attempts},
        'healthy_controls_without_unnecessary_repair':{n:lab['cases'][n]['healthy_no_unnecessary_repair'] for n in ('primary_0','scale_10','scale_15')},
        'scale_connectivity_passed':{n:lab['cases'][n]['connectivity']['passed'] for n in ('primary_0','scale_10','scale_15')},
        'scale_outcomes':lab['scale_results'],'qualification':lab['fault_qualification'],
        'native_cleanup_audits':native_audits,'bridges_remaining':bridges,'automatic_repair_disabled':True,
        'observed_only_disabled':True,'application_archive':str(archive.relative_to(ROOT)),'archive_sha256':sha(archive),
        'evaluation_report_sha256':sha(ROOT/'artifacts/evaluation_validation_report.json'),
        'held_out_metrics_sha256':sha(OUT/'held_out_metrics.json'),'full_project_complete':False,
        'posthoc_provenance_sha256':sha(OUT/'posthoc_provenance.json'),
        'limitations':evaluation['limitations']}
    (OUT/'final_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'scale_outcomes','qualification','native_cleanup_audits'}},indent=2))


if __name__=='__main__': main()
