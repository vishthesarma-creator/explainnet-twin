"""Launch only the unprivileged UI, reusing an existing backend configuration."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dashboard.client import ClientSettings

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/example.yaml')
    parser.add_argument('--api-url', help='Optional loopback API URL override')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        parser.error('Run the dashboard as the ordinary application user; the privileged agent is separate.')
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    settings = load_settings(args.config)
    client = ClientSettings(api_url=args.api_url or f'http://{settings.host}:{settings.port}')
    if client.api_url != f'http://{settings.host}:{settings.port}':
        parser.error('API URL must match selected configuration')
    environment = os.environ | {'EXPLAINNET_API_URL': client.api_url,
        'EXPLAINNET_CONFIG_HASH': settings.config_hash, 'EXPLAINNET_CONFIG_PATH': str(args.config.resolve())}
    result = subprocess.run([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'src/explainnet/dashboard/app.py'),
        '--server.address=127.0.0.1', f'--server.port={args.port}', '--server.headless=true',
        '--browser.gatherUsageStats=false'], cwd=ROOT, env=environment, check=False)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
