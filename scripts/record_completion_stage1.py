"""Read-only handover attestation and validation-report collation."""
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from explainnet.app_launcher import owned, request, validate_binding
from explainnet.application_profiles import PROFILES, ROOT
from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json


def main():
    base = ROOT / 'artifacts/completion_stage1'
    audit = json.loads((ROOT / 'artifacts/completion_audit/current_state.json').read_text())
    report = {'schema_version': 1, 'at_utc': datetime.now(UTC).isoformat(), 'stage': 'completion_prompt_1',
        'scope': 'operational stabilization; no trained recovery qualification', 'tests': [], 'profiles': {},
        'preservation': [], 'limitations': ['No fault-repair campaign or trained-model recovery was executed.',
            'Native scenario-reset over 2 MiB was checked with complete synthetic evidence; a historical large native traffic result was checked live.',
            'Interrupted action/cancellation/concurrency failures are software fixtures; no new injected live failure campaign.',
            'Read-only cache references expire; obtain a new source snapshot after eviction.']}
    cases = set()
    for name in ['final_tests', 'delta_tests', 'final_delta', 'handover_tests', 'ownership_tests']:
        path = base / (name + '.xml')
        tree = ET.parse(path)
        suite = tree.getroot().find('testsuite')
        report['tests'].append({'report': str(path.relative_to(ROOT)), **suite.attrib})
        assert suite.attrib['failures'] == suite.attrib['errors'] == '0'
        cases.update((t.attrib['classname'], t.attrib['name']) for t in tree.findall('.//testcase'))
    report['unique_test_cases'] = len(cases)
    report['test_counts_overlap'] = True
    report['healthy_lifecycle'] = json.loads((base / 'live.json').read_text())
    final = base / 'final_live.json'
    report['final_live'] = json.loads(final.read_text()) if final.exists() else None
    report['browser'] = json.loads((base / 'browser/report.json').read_text())
    visual = base / 'browser/final_fresh_network.json'
    if visual.exists():
        captured = json.loads(visual.read_text())
        report['final_visual'] = {'at_utc': captured['at_utc'], 'topology_visible': captured['topology_visible'],
            'fresh_visible': captured['fresh_visible'], 'screenshot': 'artifacts/completion_stage1/browser/final_fresh_network.png'}
    checkpoint = json.loads((base / 'checkpoint.json').read_text())
    report['source_changes'] = {'modified': [], 'removed_or_moved': []}
    for name, expected in checkpoint['files'].items():
        name = name.replace('\\', '/')
        path = ROOT / name
        if not path.exists():
            report['source_changes']['removed_or_moved'].append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            report['source_changes']['modified'].append(name)
        if name.startswith('config/') or name in {'requirements.txt', 'pyproject.toml',
                'artifacts/stage6/runtime/config.json', 'artifacts/stage14/rehearsals/bb745a91/config.json', 'docs/COMPLETION_AUDIT.md'}:
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            report['preservation'].append({'file': name, 'sha256': actual, 'unchanged': expected == actual})
            assert expected == actual
    for item in audit['applications']['canonical']['model_file_checks']:
        actual = hashlib.sha256(Path(item['file']).read_bytes()).hexdigest()
        assert actual == item['sha256']
        report['preservation'].append({'file': item['file'], 'sha256': actual, 'unchanged': True})
    for profile, (config, port) in PROFILES.items():
        cfg = load_settings(config)
        url = f'http://127.0.0.1:{cfg.port}'
        receipt = json.loads((cfg.runtime_dir / 'app_launcher.json').read_text())
        binding = validate_binding(cfg, url)
        assert all(owned(receipt['components'][k]) for k in ('backend', 'dashboard'))
        with sqlite3.connect(cfg.database_path.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            counts = dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition'))
            active = db.execute('SELECT model_id FROM model_activation WHERE singleton=1').fetchone()
            failed_jobs = db.execute("SELECT count(*) FROM jobs WHERE state='failed'").fetchone()[0]
        control = request(url + '/v1/lab/control')
        assert not control['auto_enabled'] and not control['allow_observed_only']
        assert not control.get('active_workflow_id') and not control.get('unsettled_action_ids')
        report['profiles'][profile] = {'identity': binding, 'dashboard_url': f'http://127.0.0.1:{port}',
            'components': {k: receipt['components'][k]['identity'] for k in ('backend', 'dashboard')},
            'control': control, 'health': request(url + '/v1/health'), 'dataset_members': counts,
            'active_model_id': active[0] if active else None, 'retained_failed_jobs': failed_jobs}
    assert report['profiles']['trained']['active_model_id'] == 'm20261016T074751_a92c0db8f44e'
    assert report['profiles']['trained']['dataset_members'] == {
        row['partition']: row['windows'] for row in audit['applications']['canonical']['dataset_counts']}
    assert report['profiles']['observed-only']['dataset_members'] == {}
    report['acceptance'] = 'passed_with_scientific_scope_limits' if (report['final_live']
        and report['final_live'].get('state') == 'healthy_running_verified'
        and report['browser'].get('status') == 'passed' and len(report['browser']['routes']) == 12) else 'pending_final_live_or_browser_checks'
    atomic_json(ROOT / 'artifacts/completion_stage1_validation.json', report)
    print(json.dumps({'acceptance': report['acceptance'], 'unique_test_cases': len(cases),
        'browser': report['browser'].get('status'), 'profiles': list(report['profiles'])}))


if __name__ == '__main__':
    main()
