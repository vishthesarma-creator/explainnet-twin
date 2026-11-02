"""Real read-only integration and Streamlit AppTest smoke; never launches a lab."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from explainnet.config import load_settings
from explainnet.dashboard.client import ApiClient, ClientSettings
from explainnet.dashboard_api import DashboardStatus, Records
from explainnet.storage import utc_now

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'artifacts/stage6/runtime/config.json')
    args = parser.parse_args()
    cfg = load_settings(args.config)
    url = f'http://{cfg.host}:{cfg.port}'
    os.environ['EXPLAINNET_API_URL'] = url
    client = ApiClient(ClientSettings(api_url=url, timeout_s=30))
    report = {'stage': 12, 'at_utc': utc_now(), 'app_uid': os.geteuid(), 'api_url': url,
        'lab_campaign_started': False, 'training_started': False, 'sealed_test_measurements_read': False,
        'visual_verification': {'browser_automation': 'unavailable: browser inventory empty',
            'pixel_layout_verified': False, 'screenshots': [], 'alternative': 'supported Streamlit AppTest rendering/navigation'},
        'checks': {}, 'pages': []}
    baseline = client.get('/v1/dashboard/status', DashboardStatus)
    report['actual_readiness'] = baseline
    sources = client.get('/v1/dashboard/telemetry-sources', Records)['records']
    report['checks']['historical_sources'] = len(sources)
    if sources:
        source = sources[0]['instance_id']
        history = client.get('/v1/dashboard/telemetry/' + source + '?limit=10')
        report['checks']['actual_history_windows'] = len(history['windows'])
        report['checks']['historical_source_live'] = history['collector']['live']
    catalog = client.get('/v1/dashboard/evidence', Records)
    report['checks']['evidence'] = []
    for artifact in catalog['records']:
        if artifact['available']:
            value = client.get('/v1/dashboard/evidence/' + artifact['artifact_id'])
            assert 'evidence' in value
            report['checks']['evidence'].append(artifact['artifact_id'])
    with sqlite3.connect(f'file:{cfg.database_path}?mode=ro', uri=True) as db:
        before = dict(db.execute('SELECT type,count(*) FROM jobs GROUP BY type'))
    app = AppTest.from_file(ROOT / 'src/explainnet/dashboard/app.py')
    page_files = ['overview', 'network', 'incidents', 'twin', 'recovery', 'evidence']
    for page in range(6):
        started = time.monotonic()
        if page:
            app.switch_page('pages/' + page_files[page] + '.py')
        app.run(timeout=90)
        if app.exception:
            raise RuntimeError([e.message for e in app.exception])
        report['pages'].append({'page': app.title[0].value, 'rendered': True,
            'elapsed_ms': (time.monotonic() - started) * 1000, 'errors': [e.value for e in app.error],
            'warnings': [e.value for e in app.warning]})
    report['checks']['navigation_entrypoint'] = True
    with sqlite3.connect(f'file:{cfg.database_path}?mode=ro', uri=True) as db:
        after = dict(db.execute('SELECT type,count(*) FROM jobs GROUP BY type'))
    assert before == after, 'Page rendering must not submit any jobs'
    report['checks']['job_counts_unchanged'] = True
    current = client.get('/v1/lab/control')
    assert baseline['control']['mode'] == current['mode']
    assert not current['auto_enabled'] and not current['allow_observed_only']
    report['checks']['mode_unchanged_automation_disabled'] = True
    with httpx.Client(trust_env=False, timeout=10) as http:
        response = http.get('http://127.0.0.1:8501/_stcore/health')
        assert response.status_code == 200 and response.text == 'ok'
        report['checks']['streamlit_health'] = 'ok'
        report['checks']['streamlit_root_http'] = http.get('http://127.0.0.1:8501').status_code
    report['status'] = 'passed_with_visual_and_live_lab_limitations'
    report['limitations'] = ['No privileged agent/network was started for this UI stage; live mutation, fresh twin and repair outcomes were not re-exercised.',
        'Actual model inference and SHAP remain unavailable; those UI states were exercised only with explicit software fixtures where applicable.',
        'Browser automation was unavailable. AppTest verifies rendering and widgets, not pixel-level layout.']
    report['implementation_files_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / 'src/explainnet/dashboard').rglob('*.py')}
    (ROOT / 'artifacts/dashboard_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'pages': report['pages'], 'checks': report['checks']}))


if __name__ == '__main__':
    main()
