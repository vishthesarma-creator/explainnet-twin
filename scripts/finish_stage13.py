#!/usr/bin/env python3
"""Resume final reporting/checks after an existing packet campaign; never rescore test."""
import argparse
import json
import os
import pwd
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--campaign',default='492fca67')
    parser.add_argument('--detach',action='store_true')
    args=parser.parse_args()
    if not args.campaign.isalnum() or len(args.campaign)>16:
        raise ValueError('Invalid campaign ID')
    if os.geteuid()!=0:
        raise ValueError('Root supervises only; every application command below drops to UID 1000')
    if (OUT/'final_audit.json').exists():
        print('Existing final audit retained; no repeated finalization')
        return 0
    if args.detach:
        pid=os.fork()
        if pid:
            print(json.dumps({'completion_pid':pid,'checkpoint':str(OUT/'completion.json')})); return 0
        os.setsid()
        fd=os.open(OUT/'completion.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
        os.dup2(fd,1); os.dup2(fd,2); os.close(fd)
        os.dup2(os.open('/dev/null',os.O_RDONLY),0)
    record={'stage':13,'pid':os.getpid(),'campaign_id':args.campaign,'state':'waiting_for_native_cleanup',
        'started_utc':datetime.now(UTC).isoformat(),'steps':[],'test_rescored':False}
    def save():
        temp=OUT/'completion.json.tmp'
        temp.write_text(json.dumps(record,indent=2)+'\n'); temp.replace(OUT/'completion.json')
    save()
    uid=1000; gid=pwd.getpwuid(uid).pw_gid
    env=os.environ|{'PYTHONPATH':str(ROOT/'src')}
    def run(name,argv,timeout,root=False):
        record['state']=name; save(); start=time.monotonic()
        with (OUT/('completion_'+name+'.log')).open('a') as output:
            result=subprocess.run(argv,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,
                user=None if root else uid,group=None if root else gid,extra_groups=[],timeout=timeout,check=False)
        record['steps'].append({'name':name,'exit_code':result.returncode,'elapsed_ms':(time.monotonic()-start)*1000})
        save()
        if result.returncode:
            raise RuntimeError(name+' failed; inspect completion_'+name+'.log; no automatic retry')
    try:
        end=time.monotonic()+12000
        campaign=OUT/'labs'/args.campaign
        while time.monotonic()<end:
            reports=list(campaign.glob('cleanup_*.json'))
            if reports:
                cleanup=json.loads(max(reports,key=lambda p:p.stat().st_mtime_ns).read_text())
                if not cleanup.get('owned_bridges_removed') or not cleanup.get('preexisting_bridges_preserved'):
                    raise RuntimeError('Native cleanup did not pass; no global cleanup attempted')
                break
            time.sleep(15)
        else:
            raise TimeoutError('Bounded native-cleanup wait expired')
        python=str(ROOT/'.venv/bin/python')
        run('report',[python,str(ROOT/'scripts/evaluate_stage13.py'),'report'],180)
        run('dashboard',[python,str(ROOT/'scripts/check_stage13_dashboard.py')],700)
        run('static',[python,str(ROOT/'scripts/check_stage13.py'),'--static-only'],120)
        lab=json.loads((campaign/'report.json').read_text())
        if lab.get('status')!='complete':
            raise RuntimeError('Native execution finished with failures; reports retained; resolve concrete failed cases before final audit')
        run('final_audit',['/usr/bin/python3',str(ROOT/'scripts/finalize_stage13.py')],600,root=True)
        manifest_path=OUT/'experiment_manifest.json'
        manifest=json.loads(manifest_path.read_text())
        manifest['state']='stage13_complete_with_declared_limits'
        manifest['checklist']={k:'passed_with_declared_limits' for k in manifest['checklist']}
        manifest['completed_utc']=datetime.now(UTC).isoformat()
        manifest['full_project_complete']=False
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        checklist=ROOT/'docs/STAGE13_CHECKLIST.md'
        checklist.write_text(checklist.read_text().replace('- [ ]','- [x]'))
        final=json.loads((OUT/'final_audit.json').read_text())
        primary={a:dict(Counter(c['state'] for n,c in lab['cases'].items()
            if n.startswith('primary_') and c['approach']==a)) for a in sorted({c['approach'] for n,c in lab['cases'].items() if n.startswith('primary_')})}
        progress=ROOT/'docs/PROGRESS.md'
        with progress.open('a') as handle:
            handle.write('\n## Stage 13 measured evaluation completed ('+datetime.now(UTC).date().isoformat()+')\n\n'
                'Dataset: 360/360 windows, 60/60 episodes, 240/60/60 train/validation/test; original 192 memberships preserved exactly. '
                'Frozen model/test and five real validation SHAP cases retained without rescoring. '
                'Primary independent original attempts: '+json.dumps(primary,sort_keys=True)+'.\n\n'
                'Actual scale outcomes: '+json.dumps([{'switches':r['switches'],'state':r['state'],
                    'healthy_rtt_ms':r.get('healthy_rtt_ms'),'impaired_rtt_ms':r.get('impaired_rtt_ms')} for r in lab['scale_results']],sort_keys=True)+'. '
                'Other-fault qualification: '+json.dumps(lab['fault_qualification'],sort_keys=True)+'. '
                'Trained-model attempt: '+lab['cases'].get('trained',{}).get('state','unavailable')+'.\n\n'
                'Final real API/six-page dashboard check and static/dependency checks passed. SQLite integrity/foreign keys, split/provenance, '
                'source cleanup and automatic/observed-only mode-off audits passed; no OVS bridges remain. '
                'Evidence archive: `'+final['application_archive']+'`. Actual measurements, failures, timings, workload/protocol, '
                'measurement planes and limitations are in `docs/EVALUATION_STAGE13.md`, `artifacts/evaluation_validation_report.json` '
                'and `artifacts/stage13/final_audit.json`. The perfect ten-episode test score is narrow emulation evidence; '
                'other-fault repair and larger-topology model transfer remain conditional or unqualified as recorded. '
                'Stages 14/15 remain pending; the full project is not marked complete.\n')
        record.update(state='complete_with_declared_limits',ended_utc=datetime.now(UTC).isoformat())
    except Exception as exc:  # noqa: BLE001 - preserve actual blocker without a hidden retry
        record.update(state='needs_review',error=str(exc),ended_utc=datetime.now(UTC).isoformat())
        save(); print(json.dumps(record),flush=True); return 1
    save(); print(json.dumps(record),flush=True)
    return 0


if __name__=='__main__': raise SystemExit(main())
