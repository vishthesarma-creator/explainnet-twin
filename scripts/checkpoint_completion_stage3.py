"""Preserve pre-stage-3 sources, including exact reconstruction of initial edits."""
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/completion_stage3'


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'checkpoint.json').exists():
        print('Existing checkpoint preserved'); return
    previous = json.loads((ROOT/'artifacts/completion_stage2_validation.json').read_text())
    base = json.loads((ROOT/'artifacts/completion_stage2/checkpoint.json').read_text())
    touched = {'dataset_contracts','dataset_export','dataset_repository','dataset_service','model_dataset',
        'model_contracts','model_training','telemetry_math','model_policy','diagnosis_service','model_bundle','explanation_service'}
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    path = OUT/('checkpoint_'+stamp+'.zip'); hashes = {}; reconstructed = []
    with zipfile.ZipFile(ROOT/'artifacts/completion_stage2'/base['archive']) as earlier, zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as output:
        for directory in ['src','config','scripts','tests','docs']:
            for file in sorted((ROOT/directory).rglob('*')):
                if not file.is_file() or '__pycache__' in file.parts or file.suffix not in {'.py','.json','.md','.yaml','.yml','.ps1','.mjs'}: continue
                name = file.relative_to(ROOT).as_posix()
                if file.name=='checkpoint_completion_stage3.py': continue
                raw = file.read_bytes()
                if directory=='src' and file.stem in touched:
                    if name not in previous['source_changes_from_checkpoint']:
                        raw = earlier.read(name)
                        assert hashlib.sha256(raw).hexdigest()==base['files'][name]
                    else:
                        text = raw.decode()
                        if file.stem=='model_policy':
                            text = text.replace("    if (bundle.get('supported_topology_hashes') and\n            window.get('context',{}).get('config_hash') not in bundle['supported_topology_hashes']):\n        unsupported.append('topology: outside declared trained domain or topology identity unavailable')\n",'')
                        elif file.stem=='telemetry_math':
                            text = text.replace('"config_hash":points[-1].get(\'config_hash\'), ','')
                        else:
                            raise ValueError('Unaccounted edited preimage '+name)
                        raw = text.encode()
                        assert hashlib.sha256(raw).hexdigest()==previous['source_version']['final_file_sha256'][name], name
                    reconstructed.append(name)
                hashes[name] = hashlib.sha256(raw).hexdigest(); output.writestr(name,raw)
    record = {'at_utc':datetime.now(UTC).isoformat(),'archive':str(path.relative_to(OUT)),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'files':hashes,
        'preimages_reconstructed_after_initial_edits':reconstructed,
        'method':'Unchanged stage-2 files from preserved archive; stage-2-changed files reversed exactly and verified against final stage-2 hashes. Current files were not reverted.',
        'database_backup':False,'models_modified':False}
    (OUT/'checkpoint.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'files':len(hashes),'preimages':len(reconstructed),'archive':str(path)}))


if __name__=='__main__': main()
