"""Save final static/dependency receipts; preserve the measured focused-test history."""
import json
import subprocess
import sys
import time
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage14'


def main():
    path=OUT/'software_checks.json'
    value=json.loads(path.read_text())
    checks=[]
    for name,argv in [('ruff',[sys.executable,'-m','ruff','check','src','scripts','tests']),
        ('dependencies',[sys.executable,'-m','pip','check'])]:
        start=time.monotonic()
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=120,check=False)
        log=OUT/(name+'.log'); log.write_text(result.stdout+result.stderr)
        checks.append({'name':name,'command':argv,'exit_code':result.returncode,'elapsed_ms':(time.monotonic()-start)*1000,
            'source':str(log.relative_to(ROOT))})
    value.update(at_utc=utc_now(),static_checks=checks,status='passed' if all(c['exit_code']==0 for c in checks) else 'failed')
    atomic_json(path,value)
    print(json.dumps({'status':value['status'],'static_checks':checks},indent=2))
    return 0 if value['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
