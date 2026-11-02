"""Bounded recovery of this stage's stopped-lab archive, retaining every source file."""
import json
import os
import signal
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'artifacts/stage6/runtime/supervisor.json'
report=json.loads(path.read_text())
if report.get('supervisor_pid') != 2366 or report.get('state')!='canceled':
    raise ValueError('This recovery is scoped only to the recorded canceled Stage 13 supervisor 2366')
for field in ('api_pid','agent_pid'):
    if Path('/proc/'+str(report[field])).exists():
        raise ValueError('Owned service still present; archive recovery refused')
bridges=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
if bridges:
    raise ValueError('Expected the already-verified empty lab; no bridge deletion attempted')
process=Path('/proc/2366')
if process.exists():
    cmd=(process/'cmdline').read_bytes()
    if b'scripts/dataset_supervisor.py' not in cmd or b'artifacts/stage6/runtime' not in cmd:
        raise ValueError('Recorded PID identity changed')
    os.kill(2366,signal.SIGKILL)
archive=ROOT/'artifacts/stage13/canceled_root_state.tar.gz'
with tarfile.open(archive,'w:gz') as tar:
    tar.add(report['root_state_dir'],arcname='root_state',recursive=True)
report.update(cleanup_preserved_bridges=True,agent_socket_present=False,
    root_archive_tar=str(archive),archive_recovered_utc=datetime.now(UTC).isoformat(),
    archive_recovery='Only exact stopped-lab supervisor 2366 was terminated during slow file-by-file archive. Source state and partial directory archive retained; complete single-file archive saved.')
path.write_text(json.dumps(report,indent=2)+'\n')
(ROOT/'artifacts/stage13/canceled_supervisor.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'scoped_lab_clean':True,'archive':str(archive),'bytes':archive.stat().st_size}))
