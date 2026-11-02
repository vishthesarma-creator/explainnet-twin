#!/usr/bin/env python3
"""Read-only OS resource proof after the owned rehearsal supervisor has finished."""
import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--tag',required=True); args=parser.parse_args()
    if not args.tag.isalnum() or len(args.tag)!=8: raise ValueError('Invalid rehearsal tag')
    if os.geteuid()!=0: raise ValueError('Read OS ownership/resources as root using OS Python')
    folder=ROOT/'artifacts/stage14/rehearsals'/args.tag
    supervisor=json.loads((folder/'supervisor.json').read_text())
    bridges=subprocess.run(['ovs-vsctl','list-br'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
    leftovers=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        try: argv=entry.joinpath('cmdline').read_bytes().split(b'\0')
        except OSError: continue
        project_service=any(v in argv for v in (b'explainnet.cli',b'explainnet.agent_server',b'streamlit'))
        if project_service and (any(args.tag.encode() in v for v in argv) or b'--server.port=8502' in argv):
            leftovers.append(int(entry.name))
    result={'at_utc':datetime.now(UTC).isoformat(),'stage':14,'tag':args.tag,
        'bridges_remaining':bridges,'rehearsal_service_pids_remaining':leftovers,
        'owned_cleanup_passed':supervisor['owned_bridges_removed'],'preexisting_bridges_preserved':supervisor['preexisting_bridges_preserved'],
        'socket_removed':supervisor['socket_removed'],'no_global_cleanup_executed':True}
    result['status']='passed' if not bridges and not leftovers and all(result[k] for k in ('owned_cleanup_passed','preexisting_bridges_preserved','socket_removed')) else 'needs_review'
    (ROOT/'artifacts/stage14/resource_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
