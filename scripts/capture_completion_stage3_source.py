"""Record reviewable source hashes against the preserved pre-stage checkpoint."""
import hashlib
import json

from explainnet.application_profiles import ROOT
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage3'


def main():
    checkpoint=json.loads((OUT/'checkpoint.json').read_text())
    current={}
    for directory in ['src','scripts','tests','docs']:
        for p in sorted((ROOT/directory).rglob('*')):
            if p.is_file() and p.suffix in {'.py','.md','.mjs'} and p.name!='COMPLETION_STAGE3.md':
                current[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    old=checkpoint['files']
    atomic_json(OUT/'source_review.json',{'at_utc':utc_now(),'pre_stage_archive':checkpoint['archive'],
        'pre_stage_archive_sha256':checkpoint['sha256'],'final_file_sha256':current,
        'changed_from_checkpoint':[n for n,h in current.items() if n in old and h!=old[n]],
        'added_since_checkpoint':[n for n in current if n not in old],
        'limitation':'Review snapshot, not the future pre-test freeze. Current collection owner keeps its launch-loaded modules; later training/evaluation/native owners load final source. All accepted features are audited by raw reconstruction. Runtime status/handover files update without changing scientific source.'})
    print(json.dumps({'tracked_files':len(current),'changed':sum(n in old and h!=old[n] for n,h in current.items())}))


if __name__=='__main__':main()
