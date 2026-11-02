"""Named application identities; stores and privileged owners remain separate."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    'trained': (ROOT / 'artifacts/stage6/runtime/config.json', 8501),
    'observed-only': (ROOT / 'artifacts/stage14/rehearsals/bb745a91/config.json', 8502),
}


def identity(settings):
    from explainnet.config import load_settings
    name, path = 'custom', None
    for label, (config, _) in PROFILES.items():
        if config.exists() and load_settings(config).config_hash == settings.config_hash:
            name, path = label, str(config)
            break
    return {'profile': name, 'config_path': path, 'config_hash': settings.config_hash,
        'database_path': str(settings.database_path), 'agent_socket': str(settings.agent_socket),
        'api_url': f'http://127.0.0.1:{settings.port}',
        'diagnosis_contract': 'trained IF/RF/SHAP; laboratory recovery requires current qualified evidence' if name == 'trained'
            else 'observed-only laboratory; no trained diagnosis claimed' if name == 'observed-only' else 'custom configuration; inspect model status'}
