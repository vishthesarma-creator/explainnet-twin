"""Read-only final provenance, model, lineage, concurrency and state audit."""
import hashlib
import json
import sqlite3
import statistics
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.dataset_repository import DatasetRepository
from explainnet.model_bundle import BundleRepository
from explainnet.storage import Store, utc_now
from explainnet.topology.spec import runtime_switch_name

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage14'
BATCH='db5a15991774142f0a8ef871522face4d'


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def archived_explanation_concurrency():
    """Reuse only timing/source-count metadata from the closed Stage 13 packet DB."""
    case=read(ROOT/'artifacts/stage13/lab_report.json')['cases']['trained']
    archive=ROOT/'artifacts/stage13/labs/492fca67/data_a1b7d229.tar.gz'
    with tempfile.TemporaryDirectory(prefix='explainnet-stage14-audit-') as temporary:
        database=Path(temporary)/'e.sqlite3'
        with tarfile.open(archive,'r:gz') as tar:
            names=set(tar.getnames())
            for suffix in ('','-wal','-shm'):
                name='data/explainnet.sqlite3'+suffix
                if name not in names: continue
                member=tar.getmember(name)
                if member.size>1_000_000_000: raise ValueError('Evidence database exceeds bounded audit size')
                with tar.extractfile(member) as source,(Path(str(database)+suffix)).open('wb') as target:
                    while block:=source.read(1024*1024): target.write(block)
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
            e=case['workflow']['explanation']['explanation_id']
            payload=json.loads(db.execute('SELECT payload_json FROM explanations WHERE explanation_id=?',(e,)).fetchone()[0])
            counts=dict(db.execute('SELECT s.source,count(*) FROM telemetry_samples s JOIN telemetry_collectors c ON c.run_id=s.run_id '
                'WHERE c.instance_id=? AND s.at_utc>=? AND s.at_utc<=? GROUP BY s.source',
                (case['instance_id'],payload['created_utc'],payload['completed_utc'])))
            beginning=datetime.fromisoformat(payload['created_utc'])
            finished=datetime.fromisoformat(payload['completed_utc'])
            observations=[datetime.fromisoformat(r[0]) for r in db.execute('SELECT s.at_utc FROM telemetry_samples s '
                'JOIN telemetry_collectors c ON c.run_id=s.run_id WHERE c.instance_id=? AND s.source=\'network_agent\' '
                'AND s.at_utc>=? AND s.at_utc<=? ORDER BY s.at_utc',
                (case['instance_id'],(beginning-timedelta(seconds=30)).isoformat(),(finished+timedelta(seconds=30)).isoformat()))]
            before=[t for t in observations if t<=beginning]; after=[t for t in observations if t>=finished]
            gaps=[(b-a).total_seconds() for a,b in pairwise(observations)]
            cadence=statistics.median(gaps) if gaps else None
            bracket=(after[0]-before[-1]).total_seconds() if before and after else None
    return {'measurement_source':'Retained actual Stage 13 trained packet case; only timing/source-count metadata inspected',
        'source_episode':case['episode_id'],'instance_id':case['instance_id'],'explanation_id':e,'status':payload['status'],
        'reason':payload.get('reason'),
        'created_utc':payload['created_utc'],'completed_utc':payload['completed_utc'],'runtime_ms':payload['runtime_ms'],
        'samples_during_explanation_request_processing':counts,
        'local_median_observation_gap_s':cadence,'explanation_bracketing_gap_s':bracket,
        'continuity_at_sampling_resolution':bool(bracket is not None and cadence is not None and bracket<=2*cadence+.5),
        'resolution_limitation':'Processing can finish between sampler ticks. Bracketing continuity does not claim an observation inside a sub-cadence SHAP runtime; explicit worker overlap is separately tested with software fixtures.',
        'archive':str(archive.relative_to(ROOT)),'archive_sha256':sha(archive)}


def main():
    initial=read(OUT/'starting_state.json')
    unchanged={name:sha(ROOT/name)==expected for name,expected in initial['scientific_artifact_sha256'].items()}
    assert all(unchanged.values()),'Retained scientific artifact changed'
    settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
    store=Store(settings.database_path)
    assert digest(DatasetRepository(store).members(BATCH))==read(ROOT/'artifacts/stage13/dataset_audit.json')['membership_sha256']
    registry=BundleRepository(store)
    compatible=[]
    for record in registry.list():
        registry.load(record['model_id']); compatible.append(record['model_id'])
    assert compatible==[m['model_id'] for m in initial['models']]
    with store.connection() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert not db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone()
    with urllib.request.urlopen(f'http://127.0.0.1:{settings.port}/v1/lab/control',timeout=10) as response:
        control=json.load(response)
    assert not control['auto_enabled'] and not control['allow_observed_only']
    resources=read(OUT/'resource_audit.json'); assert resources['status']=='passed'
    latest=read(OUT/'latest_rehearsal.json'); folder=Path(latest['directory'])
    report=read(folder/'report.json'); supervisor=read(folder/'supervisor.json')
    assert supervisor['driver_exit_code']==0 and supervisor['owned_bridges_removed'] and supervisor['socket_removed']
    assert not report['errors'] and report['cleanup']['state']=='stopped'
    assert report['healthy_no_unnecessary_repair']
    assert report['collector_continued_during_twin']
    assert not report['final_control']['auto_enabled'] and not report['final_control']['allow_observed_only']
    w=report['workflow']; action=report['action_before_undo']; exp=w['candidate_result']
    checks={'incident':w['incident_id']==action['incident_id'],
        'workflow':w['workflow_id']==action['workflow_id'],
        'snapshot':w['snapshot_id']==action['snapshot_id']==exp['snapshot_id'],
        'owned_original':report['instance_id']==w['instance_id']==action['instance_id'],
        'separate_twin':exp['twin_id']!=report['instance_id'],
        'observed_only_explicit':w['diagnosis']['status']=='observed-only',
        'original_two_windows':len(action['post_windows'])==2 and all(p['evaluation']['eligible'] for p in action['post_windows']),
        'verified_before_undo':action['state']=='succeeded','intentional_undo_verified':report['undo']['state']=='rolled_back',
        'source_preserved_in_trials':all(t['original_unchanged'] for t in exp['trials'])}
    assert all(checks.values())
    original_token=report['construction']['token']
    switches=[f's{i}' for i in range(1,6)]
    source_names={runtime_switch_name(original_token,s) for s in switches}
    twin_tokens={t['reset']['runtime_token'] for t in exp['trials']}
    twin_names={runtime_switch_name(token,s) for token in twin_tokens for s in switches}
    assert original_token not in twin_tokens and source_names.isdisjoint(twin_names)
    background=archived_explanation_concurrency()
    assert background['status']=='ready' and background['continuity_at_sampling_resolution']
    for path in (OUT/'dashboard_canonical.json',folder/'dashboard.json'):
        ui=read(path)
        assert ui['status']=='passed' and len(ui['pages'])==6 and ui['no_jobs_or_audits_from_navigation']
    value={'stage':14,'status':'passed','at_utc':utc_now(),'scientific_artifacts_unchanged':unchanged,
        'membership_digest_unchanged':True,'compatible_models':compatible,'sqlite_integrity':'ok','foreign_key_violations':0,
        'canonical_control':control,'resource_audit':resources,'fresh_rehearsal_lineage':checks,
        'runtime_isolation':{'original_bridge_names':sorted(source_names),'twin_bridge_names':sorted(twin_names),
            'disjoint':True,'source':'Actual root construction/reset tokens mapped by the validated runtime-name function'},
        'historical_actual_explanation_concurrency':background,
        'fresh_twin_collection_continuity':True,'rehearsal_archive_sha256':sha(folder/'rehearsal_evidence.tar.gz'),
        'test_scoring_or_training_performed':False,'new_migration_required':False,'full_project_complete':False,'stage15_started':False}
    atomic_json(OUT/'final_audit.json',value)
    print(json.dumps({'status':'passed','runtime_isolation':True,'membership_unchanged':True,
        'explanation_concurrency':background,'rehearsal':report['status']},indent=2))


if __name__=='__main__': main()
