"""Stop only the verified failed API process, after confirming no live agent dataplane."""
import json
import os
import signal
import urllib.request
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

runtime = Path('artifacts/stage6/runtime')
status = json.loads((runtime / 'supervisor.json').read_text())
config = json.loads((runtime / 'config.json').read_text())
pid = status['api_pid']
command = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()
if str(runtime / 'config.json') not in command or 'explainnet' not in command:
    raise ValueError('API process ownership mismatch')
with urllib.request.urlopen(f"http://127.0.0.1:{config['port']}/v1/agent/inventory", timeout=15) as response:
    inventory = json.load(response)['inventory']
if any(r['state'] == 'running' or r.get('live_verified') for r in inventory.get('instances', [])):
    raise ValueError('live dataplane exists; use ordinary cancellation and cleanup instead')
atomic_json(Path('artifacts/stage7/failed_worker_stop.json'), {'at_utc': utc_now(), 'api_pid': pid,
    'command': command, 'inventory': inventory, 'reason': 'SQLite polling lock killed worker; queued dataset actions cannot run',
    'signal': 'SIGKILL after verifying no live dataplane'})
os.kill(pid, signal.SIGKILL)
print(json.dumps({'stopped_failed_api_pid': pid, 'live_dataplanes': 0}))
