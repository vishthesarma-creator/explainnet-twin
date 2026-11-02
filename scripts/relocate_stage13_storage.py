"""Explicit, verified hot-store relocation. Source database/raw files are retained."""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.dataset_repository import DatasetRepository
from explainnet.storage import Store, utc_now

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'artifacts/stage6/runtime/config.json'
OUT = ROOT / 'artifacts/stage13'
source_settings = load_settings(CONFIG)
source = Store(source_settings.database_path)
repo = DatasetRepository(source)
batch_id = 'db5a15991774142f0a8ef871522face4d'
batch = repo.batch(batch_id)
if batch['state'] not in {'failed','canceled','interrupted'}:
    raise ValueError('Stop collection and verify scoped cleanup before relocating')
supervisor = json.loads((ROOT/'artifacts/stage6/runtime/supervisor.json').read_text())
if not supervisor.get('cleanup_preserved_bridges') or Path(source_settings.agent_socket).exists():
    raise ValueError('Supervisor cleanup has not finished')
members = repo.members(batch_id)
destination = Path.home()/'.local/share/explainnet/stage13/data'
if source.path.parent == destination:
    raise ValueError('Already relocated; use the precise dataset resume command')
destination.mkdir(parents=True,exist_ok=True)
marker = destination.parent/'relocation_source.json'
identity = {'source':str(source.path),'batch_id':batch_id,'original_members_sha256':digest(members)}
if marker.exists() and json.loads(marker.read_text()) != identity:
    raise ValueError('Destination belongs to another checkpoint; refusing overwrite')
if not marker.exists() and any(destination.iterdir()):
    raise ValueError('Destination is not empty and has no matching ownership marker')
atomic_json(marker,identity)
with sqlite3.connect('file:'+str(source.path)+'?mode=ro',uri=True) as src, sqlite3.connect(destination/'explainnet.sqlite3') as dst:
    src.backup(dst)
copied = []
for folder in ('raw','datasets','models'):
    origin = source.path.parent/folder
    if not origin.exists():
        continue
    for path in sorted(origin.rglob('*')):
        if path.is_symlink():
            raise ValueError('Unexpected symlink in data tree')
        relative = path.relative_to(source.path.parent)
        target = destination/relative
        if path.is_dir():
            target.mkdir(parents=True,exist_ok=True)
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != before:
            raise ValueError('Copy verification failed: '+str(relative))
        copied.append({'relative_path':str(relative),'sha256':before,'bytes':path.stat().st_size})
new_raw = json.loads(CONFIG.read_text()) | {'data_dir':str(destination)}
from explainnet.config import Settings

new_settings = Settings.model_validate(new_raw)
new_store = Store(new_settings.database_path)
new_repo = DatasetRepository(new_store)
assert digest(new_repo.members(batch_id)) == digest(members)
with new_store.connection() as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
batch = new_repo.batch(batch_id)
attempts = new_repo.attempts(batch_id)
completed = {a['episode_id'] for a in attempts if a['state']=='completed'}
receipt = {'at_utc':utc_now(),'old_config_hash':batch['config_hash'],'new_config_hash':new_settings.config_hash,
    'changed_fields':{'data_dir':{'before':str(source.path.parent),'after':str(destination)}},
    'old_database_retained':True,'members_preserved':len(members),'members_sha256':digest(members),
    'file_count':len(copied),'files':copied}
batch.setdefault('config_migrations',[]).append({k:v for k,v in receipt.items() if k != 'files'})
batch['config_hash'] = new_settings.config_hash
amendment = {'version':'linux_storage_v5','created_utc':utc_now(),'sample_interval_s':2,'measurement_s':100,
    'original_schedule_hash':batch['schedule_hash'],'previous_amendment':batch['recovery_amendment'],
    'reason':'Measured Windows-mount SQLite latency and observation coverage failure. Move the hot database/raw writes to persistent Linux storage with verified byte-identical accepted evidence; scientific configuration and gates unchanged.',
    'episodes':{e['episode_id']:{'attempt_limit':max(2,sum(a['episode_id']==e['episode_id'] for a in attempts)+2)}
        for e in batch['schedule']['episodes'] if e['episode_id'] not in completed}}
amendment['sha256'] = digest(amendment)
batch['recovery_amendment'] = amendment
new_repo.save_batch(batch)
new_store.audit('stage13','verified_hot_storage_relocation',receipt,subject_id=batch_id)
atomic_json(OUT/'storage_relocation.json',receipt)
atomic_json(OUT/'config_before_relocation.json',json.loads(CONFIG.read_text()))
atomic_json(CONFIG,new_raw)
print(json.dumps({k:v for k,v in receipt.items() if k != 'files'},indent=2))
