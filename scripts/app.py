"""Normal entry point; ordinary API/UI lifecycle only, no implicit lab mutations."""
import argparse
import subprocess
import sys

from explainnet.application_profiles import PROFILES, ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','status','stop'])
    parser.add_argument('--profile',choices=list(PROFILES),default='trained')
    args=parser.parse_args();config,port=PROFILES[args.profile]
    raise SystemExit(subprocess.call([sys.executable,str(ROOT/'scripts/manage_app.py'),'--config',str(config),
        '--dashboard-port',str(port),args.action],cwd=ROOT))


if __name__=='__main__':main()
