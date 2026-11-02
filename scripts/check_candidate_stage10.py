#!/usr/bin/env python3
"""Bounded root supervisor: real agent, unprivileged API/driver, isolated evidence DB."""
import json
import os
import pwd
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    tag = uuid4().hex[:8]
    uid, gid = 1000, pwd.getpwuid(1000).pw_gid
    out = ROOT / 'artifacts/stage10' / tag
    out.mkdir(parents=True)
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    config = out / 'config.json'
    prior = ROOT / 'artifacts/twin_validation_report.json'
    prior_data = Path(json.loads(Path(json.loads(prior.read_text())['config_file']).read_text())['data_dir'])
    data = out / 'data'
    data.mkdir()
    with (sqlite3.connect('file:' + str(prior_data / 'explainnet.sqlite3') + '?mode=ro', uri=True) as source,
          sqlite3.connect(data / 'explainnet.sqlite3') as target):
        source.backup(target)
    sock = Path('/run') / ('explainnet-stage10-' + tag) / 'agent.sock'
    state = Path('/var/lib') / ('explainnet-stage10-' + tag)
    config.write_text(json.dumps({'schema_version': 1, 'data_dir': str(data),
        'runtime_dir': str(out / 'run'), 'agent_socket': str(sock), 'port': port,
        'topology_file': str(ROOT / 'config/topology.yaml'), 'traffic_profiles_file': str(ROOT / 'config/traffic.yaml'),
        'objective': {'max_rtt_ms': 100, 'max_loss_fraction': .02, 'min_goodput_bps': 1000000}}))
    env = os.environ | {'PYTHONPATH': str(ROOT / 'src')}
    before = subprocess.run(['ovs-vsctl', 'list-br'], capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()
    cli = [str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(config)]
    subprocess.run([*cli, 'init'], cwd=ROOT, env=env, user=uid, group=gid, extra_groups=[], timeout=40, check=True)
    agent = api = None
    with (out / 'agent.log').open('w') as agent_log, (out / 'api.log').open('w') as api_log:
        try:
            agent = subprocess.Popen(['python3', '-m', 'explainnet.agent_server', '--allow-uid', str(uid),
                '--socket', str(sock), '--state-dir', str(state), '--stream-receivers'], cwd=ROOT, env=env,
                stdout=agent_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 15
            while not sock.exists() and time.monotonic() < deadline and agent.poll() is None:
                time.sleep(.2)
            if not sock.exists():
                raise RuntimeError('agent failed; inspect agent.log')
            api = subprocess.Popen([*cli, 'serve'], cwd=ROOT, env=env, user=uid, group=gid, extra_groups=[],
                stdout=api_log, stderr=subprocess.STDOUT)
            result = subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / ('scripts/candidate_controls_stage10_driver.py' if sys.argv[1:] == ['controls'] else 'scripts/candidate_stage10_driver.py')),
                str(config), tag, *sys.argv[1:]], cwd=ROOT, env=env, user=uid, group=gid, extra_groups=[], timeout=2400, check=False)
            print(json.dumps({'driver_exit_code': result.returncode, 'evidence_directory': str(out)}), flush=True)
        finally:
            for process in (api, agent):
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            after = subprocess.run(['ovs-vsctl', 'list-br'], capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()
            (out / 'cleanup.json').write_text(json.dumps({'bridges_before': before, 'bridges_after': after,
                'preexisting_bridges_preserved': set(before) <= set(after), 'owned_bridges_removed': before == after,
                'root_state_directory': str(state)}, indent=2))
            print(json.dumps({'scoped_cleanup': before == after}), flush=True)


if __name__ == '__main__':
    main()
