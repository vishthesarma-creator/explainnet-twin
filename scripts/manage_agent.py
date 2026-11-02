"""Root OS-Python owner lifecycle. Refuses stop with live networks/unsettled actions."""
import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'trained': ('artifacts/stage6/runtime/config.json', '/var/lib/explainnet-teacher-demo'),
    'observed-only': ('artifacts/stage14/rehearsals/bb745a91/config.json', '/var/lib/explainnet-stage14-bb745a91'),
}


def process(pid):
    base = Path('/proc') / str(pid)
    try:
        tail = (base / 'stat').read_text().rsplit(')', 1)[1].split()
        if tail[0] == 'Z':
            return None
        return {'pid': pid, 'start_ticks': tail[19], 'uid': base.stat().st_uid,
            'cwd': str((base / 'cwd').resolve()),
            'argv': [v.decode() for v in (base / 'cmdline').read_bytes().split(b'\0') if v]}
    except (OSError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='trained')
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Use root OS Python; do not use the application venv')
    config, directory = PROFILES[args.profile]
    cfg = json.loads((ROOT / config).read_text())
    argv = ['/usr/bin/python3', '-m', 'explainnet.agent_server', '--allow-uid', '1000',
        '--socket', cfg['agent_socket'], '--state-dir', directory, '--stream-receivers']
    matches = [p for entry in Path('/proc').iterdir() if entry.name.isdigit()
        and (p := process(int(entry.name))) and p['argv'] == argv and p['uid'] == 0 and p['cwd'] == str(ROOT)]
    if len(matches) > 1:
        raise ValueError('multiple owner processes; no signal sent')
    state = Path(directory)
    networks = [json.loads(p.read_text()) for p in state.glob('instance_*.json')]
    actions = [json.loads(p.read_text()) for p in state.glob('lab_action_*.json')]
    active = [r['instance_id'] for r in networks if r['state'] != 'stopped']
    unsettled = [r['action_id'] for r in actions if r['state'] in {'prepared', 'applying', 'applied', 'rolling_back', 'failed'}]
    report = {'at_utc': datetime.now(UTC).isoformat(), 'profile': args.profile, 'processes': matches,
        'owned_nonterminal_networks': active, 'unsettled_actions': unsettled, 'socket': cfg['agent_socket']}
    if args.action == 'stop':
        if active or unsettled:
            raise ValueError('owned networks/actions must be explicitly cleaned/reconciled before stopping this agent')
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/v1/lab/control", timeout=5) as response:
                control = json.load(response)
            if control.get('active_workflow_id') or control.get('monitor_active') or control.get('unsettled_action_ids'):
                raise ValueError('coordinator still active; no signal sent')
        except OSError:
            pass  # Stopped API is permitted only with terminal root journals above.
        if matches:
            saved = matches[0]
            if process(saved['pid']) != saved:
                raise ValueError('PID identity changed; no signal sent')
            os.kill(saved['pid'], signal.SIGTERM)
            end = time.monotonic() + 45
            while process(saved['pid']) == saved and time.monotonic() < end:
                time.sleep(.1)
            if process(saved['pid']) == saved:
                raise RuntimeError('graceful shutdown pending; no forced kill')
        report['status'] = 'stopped'
    elif args.action == 'start':
        if matches:
            report['status'] = 'already_running'
        else:
            if active or unsettled:
                raise ValueError('stale ownership requires explicit reconciliation/cleanup; no startup replay')
            output = ROOT / 'artifacts/completion_stage1'
            output.mkdir(exist_ok=True)
            with (output / (args.profile + '_agent.log')).open('a') as log:
                child = subprocess.Popen(argv, cwd=ROOT, env=os.environ | {'PYTHONPATH': str(ROOT / 'src')},
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report.update(status='started', process=process(child.pid))
            (output / (args.profile + '_agent_process.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'status': 'refused', 'error': str(exc), 'automatic_retry': False}))
        raise SystemExit(1) from None
