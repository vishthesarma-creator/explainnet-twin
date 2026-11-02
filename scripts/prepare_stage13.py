"""Explicit resumable prerequisite amendment; never edits accepted rows or splits."""
import hashlib
import json
import os
import signal
import sqlite3
import time
from pathlib import Path

from explainnet.config import load_network, load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store, utc_now

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/stage13'
OUT.mkdir(exist_ok=True)
config = json.loads((ROOT / 'artifacts/stage6/runtime/config.json').read_text())
store = Store(Path(config['data_dir']) / 'explainnet.sqlite3')
repo = DatasetRepository(store)
batch = repo.batch('db5a15991774142f0a8ef871522face4d')
if batch['state'] not in {'failed','interrupted','canceled'}:
    raise ValueError('Only a stopped incomplete batch can receive this amendment')
with store.connection() as db:
    if db.execute("SELECT count(*) FROM jobs WHERE state IN ('running','queued')").fetchone()[0]:
        raise ValueError('Active jobs must finish before preparation')
members = repo.members(batch['batch_id'])
member_hash = digest(members)
settings = load_settings(ROOT / 'artifacts/stage6/runtime/config.json')
if batch['config_hash'] != settings.config_hash:
    legacy = hashlib.sha256(settings.model_dump_json(exclude={'lab_test_hooks'}).encode()).hexdigest()
    if (settings.lab_test_hooks or batch['config_hash'] != legacy
            or batch['definition'] != load_network(settings.topology_file).model_dump()):
        raise ValueError('Substantive configuration drift; resume migration refused')
    receipt = {'created_utc':utc_now(),'original_hash':legacy,'current_hash':settings.config_hash,
        'only_added_default':{'lab_test_hooks':False},'definition_unchanged':True,
        'accepted_members_sha256':member_hash}
    batch.setdefault('config_migrations',[]).append(receipt)
    batch['config_hash'] = settings.config_hash
    repo.save_batch(batch)
    store.audit('stage13','dataset_config_default_migration',receipt,subject_id=batch['batch_id'])
    atomic_json(OUT / 'config_default_migration.json',receipt)
backup = OUT / 'before_stage13.sqlite3'
if not backup.exists():
    with sqlite3.connect(store.path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
atomic_json(OUT / 'prior_supervisor.json', json.loads((ROOT / 'artifacts/stage6/runtime/supervisor.json').read_text()))
attempts = repo.attempts(batch['batch_id'])
if any(a['state'] != 'completed' and not a.get('cleanup_verified') for a in attempts):
    raise ValueError('Unverified prior cleanup; review ownership first')
if batch.get('recovery_amendment',{}).get('version') != 'receiver_batch_v4':
    completed = {a['episode_id'] for a in attempts if a['state'] == 'completed'}
    amendment = {'version':'receiver_batch_v4','created_utc':utc_now(),
        'sample_interval_s':2,'measurement_s':100,'original_schedule_hash':batch['schedule_hash'],
        'reason':'Finalized receiver arrival previously fsynced and committed each interval, leaving a 70s observation gap. Batched durable ingestion now uses one flush/transaction per arrival. Retain all quality gates, target, recipes, seeds and splits; allow at most two additional attempts per unfinished episode.',
        'previous_amendment':batch.get('recovery_amendment'),
        'episodes':{e['episode_id']:{'attempt_limit':max(2,sum(a['episode_id']==e['episode_id'] for a in attempts)+2)}
                    for e in batch['schedule']['episodes'] if e['episode_id'] not in completed}}
    amendment['sha256'] = digest(amendment)
    batch['recovery_amendment'] = amendment
    repo.save_batch(batch)
    store.audit('stage13','dataset_receiver_batch_recovery',amendment,subject_id=batch['batch_id'])
atomic_json(OUT / 'dataset_amendment.json',batch['recovery_amendment'])
assert digest(repo.members(batch['batch_id'])) == member_hash
manifest = {'schema_version':1,'stage':13,'created_utc':utc_now(),'state':'prerequisites',
    'batch_id':batch['batch_id'],'schedule_hash':batch['schedule_hash'],'preserved_members':len(members),
    'preserved_members_sha256':member_hash,'target_windows':360,'target_episodes':60,
    'expected_split_windows':{'train':240,'validation':60,'test':60},
    'seed':20261007,'recovery_order_seed':20261016,'topology_sizes':[5,10,15],
    'primary_recovery':{'fault':'latency','critical_protocol':'udp','bulk_protocol':'udp',
        'critical_offered_bps':8000000,'bulk_offered_bps':5000000,'repetitions':3,
        'approaches':['no_change','fixed_rule','twin_guided'],
        'success_criteria':'Unchanged Stage11 fidelity, eligibility, original verification and rollback gates; at least two fresh settled acceptable windows and meaningful critical improvement; record transient disruption separately.',
        'fixed_rule':'For measured latency violation recommend critical pair alternative route; application still requires existing safety gates. Unqualified applications are rejected, not forced.'},
    'test_policy':'Do not read test numeric values until a checksummed frozen trained bundle and evaluation configuration exist. No tuning after unsealing.',
    'uncertainty':'Bootstrap episodes, never windows, where sufficient independent repetitions exist.',
    'campaigns_sequential':True,'paid_services':False,
    'checklist':{'starting_state':'passed','dataset':'pending','training_calibration':'pending',
        'held_out_diagnosis':'pending','backend_shap_dashboard':'pending','recovery_baselines':'pending',
        'fault_qualification':'pending','scale':'pending','final_cleanup':'pending'}}
if not (OUT / 'experiment_manifest.json').exists():
    atomic_json(OUT / 'experiment_manifest.json', manifest)
(ROOT / 'docs/STAGE13_CHECKLIST.md').write_text('''# Stage 13 execution checklist

- [x] Inspect actual Stage 12 services, artifacts, resources and failed checkpoint.
- [x] Preserve accepted membership, original schedule and failed raw evidence.
- [ ] Verify receiver-arrival fix and resume the existing 360-window main batch.
- [ ] Audit class/severity/split/provenance and quarantine rejected windows.
- [ ] Train and calibrate reproducibly; freeze configuration before test access.
- [ ] Evaluate held-out diagnosis/localization, latency and episode uncertainty.
- [ ] Exercise backend inference/SHAP and dashboard artifacts.
- [ ] Compare three recovery approaches with three independent primary repetitions.
- [ ] Recheck fault qualification and healthy no-repair behavior.
- [ ] Run actual 5/10/15-switch scale trials.
- [ ] Save reports/plots/raw evidence; verify scoped cleanup and auto disabled.

Machine-readable checkpoint: `artifacts/stage13/experiment_manifest.json`.
No Stage 14 work or final presentation is included.
''')
# Retire only the exact idle unprivileged API using this unchanged configuration;
# the existing supervisor will replace it and the dashboard can reconnect.
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        cmd = (proc / 'cmdline').read_bytes().split(b'\0')
        if (proc.stat().st_uid == os.getuid() and b'explainnet.cli' in cmd and b'serve' in cmd
                and b'artifacts/stage6/runtime/config.json' in cmd):
            os.kill(int(proc.name), signal.SIGTERM)
            deadline = time.monotonic()+30
            while proc.exists() and time.monotonic()<deadline:
                time.sleep(.2)
            if proc.exists():
                raise RuntimeError('Exact API did not stop; no force kill performed')
    except (FileNotFoundError, ProcessLookupError):
        pass
print(json.dumps({'prepared':True,'batch_id':batch['batch_id'],'members_preserved':len(members),
    'remaining_episodes':60-len({m['episode_id'] for m in members}),'backup':str(backup)}))
