"""Actual CLI control check without creating networks or enabling a watcher."""
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from explainnet.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'artifacts/stage11/control_cli'
    out.mkdir(exist_ok=True)
    local = Path(tempfile.mkdtemp(prefix='explainnet-control-'))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    config = out / 'config.json'
    config.write_text(json.dumps({'schema_version': 1, 'data_dir': str(local / 'data'), 'runtime_dir': str(local / 'run'),
        'agent_socket': str(local / 'absent.sock'), 'port': port, 'topology_file': str(ROOT / 'config/topology.yaml')}))
    Store(local / 'data/explainnet.sqlite3').initialize()
    cli = [str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(config)]
    evidence = {'app_uid': os.geteuid(), 'networks_created': False, 'watcher_started': False}
    with (out / 'api.log').open('w') as log:
        api = subprocess.Popen([*cli, 'serve'], stdout=log, stderr=subprocess.STDOUT)
        try:
            end = time.monotonic() + 30
            while time.monotonic() < end:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=2) as response:
                        schema = json.load(response)
                    break
                except OSError:
                    time.sleep(.1)
            evidence['api_version'] = schema['info']['version']
            evidence['lab_routes'] = sorted(p for p in schema['paths'] if p.startswith('/v1/lab'))
            mode = out / 'mode.json'
            mode.write_text(json.dumps({'mode': 'observe'}))
            evidence['mode_submission'] = json.loads(subprocess.run([*cli, 'lab-mode', str(mode)], capture_output=True,
                text=True, timeout=15, check=True).stdout)
            time.sleep(.5)
            evidence['control'] = json.loads(subprocess.run([*cli, 'lab-control'], capture_output=True, text=True, timeout=15, check=True).stdout)
            began = time.monotonic()
            evidence['stop'] = json.loads(subprocess.run([*cli, 'lab-stop'], capture_output=True, text=True, timeout=15, check=True).stdout)
            evidence['stop_cli_elapsed_ms'] = (time.monotonic() - began) * 1000
            assert evidence['control']['mode'] == 'observe' and not evidence['stop']['auto_enabled']
        finally:
            api.terminate()
            api.wait(timeout=30)
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
