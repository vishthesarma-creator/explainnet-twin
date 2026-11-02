"""Focused software gates, recorded separately from all packet experiments."""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'
tests=['tests/test_stage13.py','tests/test_dataset.py','tests/test_telemetry.py','tests/test_models.py',
    'tests/test_models_api.py','tests/test_network.py','tests/test_recovery.py','tests/test_recovery_api.py',
    'tests/test_workflow.py','tests/test_dashboard.py']
commands=[('focused_tests',[sys.executable,'-m','pytest','-q',*tests],600),
    ('ruff',[sys.executable,'-m','ruff','check','src','scripts','tests'],90),
    ('dependencies',[sys.executable,'-m','pip','check'],60)]
report={'source':'Automated software checks; fixtures are not packet experiments','started_utc':utc_now(),'checks':[]}
parser=argparse.ArgumentParser(); parser.add_argument('--static-only',action='store_true'); args=parser.parse_args()
if args.static_only:
    report=json.loads((OUT/'software_checks.json').read_text())
    report.setdefault('earlier_checks',[]).extend(c for c in report['checks'] if c['name']!='focused_tests')
    report['checks']=[c for c in report['checks'] if c['name']=='focused_tests']
    commands=commands[1:]
    if (OUT/'ruff.log').exists() and not (OUT/'ruff_initial.log').exists():
        (OUT/'ruff_initial.log').write_text((OUT/'ruff.log').read_text())
for name,command,timeout in commands:
    started=time.monotonic()
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=timeout,check=False)
    output=result.stdout+result.stderr
    (OUT/(name+'.log')).write_text(output)
    passed=re.search(r'(\d+) passed',output)
    report['checks'].append({'name':name,'command':command,'exit_code':result.returncode,
        'elapsed_ms':(time.monotonic()-started)*1000,'passed_tests':int(passed[1]) if passed else None,
        'output_file':name+'.log'})
    report['status']='passed' if all(c['exit_code']==0 for c in report['checks']) else 'failed'
    atomic_json(OUT/'software_checks.json',report)
    print(json.dumps(report['checks'][-1]),flush=True)
report['ended_utc']=utc_now()
atomic_json(OUT/'software_checks.json',report)
raise SystemExit(0 if report['status']=='passed' else 1)
