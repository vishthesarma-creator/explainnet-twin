"""Read-only final live identity, measurements and approved download checks."""
import hashlib
import json
from datetime import UTC, datetime
from urllib.request import urlopen

from explainnet.application_profiles import ROOT
from explainnet.dataset_export import atomic_json


def get(path, port=38223):
    with urlopen(f'http://127.0.0.1:{port}' + path, timeout=60) as response:
        return json.load(response)


def main():
    session = json.loads((ROOT / 'artifacts/completion_stage4/demo_session.json').read_text())
    instance = session['instance_id']
    config = get('/v1/config')['identity']
    assert config['profile'] == 'trained' and config['api_url'].endswith(':38223')
    control = get('/v1/lab/control')
    assert not control['auto_enabled'] and not control['allow_observed_only']
    assert not control['active_workflow_id'] and not control['unsettled_action_ids']
    network = get('/v1/networks/' + instance)
    assert network['state'] == 'running' and network['live_verified']
    telemetry = get('/v1/dashboard/telemetry/' + instance + '?limit=15')
    collector = telemetry['collector']
    assert collector['live'] and collector['observation_age_s'] < 30
    traffic = get('/v1/traffic/' + instance + '/' + session['traffic_run_id'])
    assert traffic['state'] == 'running'
    windows = [{'window_id': w['window_id'], 'at_utc': w['at_utc'], 'complete': w['complete'],
        'inference_ready': w['inference_ready'], 'features': {k: w['features'].get(k) for k in
        ['rtt_mean_ms', 'critical_goodput_bps', 'udp_loss_fraction', 'udp_jitter_ms']}}
        for w in telemetry['windows'] if w['complete'] and w['features'].get('critical_goodput_bps') is not None][:2]
    assert len(windows) == 2
    assert all((datetime.now(UTC) - datetime.fromisoformat(w['at_utc'])).total_seconds() < 60 for w in windows)
    docs = get('/v1/dashboard/deliverables')['records']
    assert len(docs) == 7
    downloads = []
    for item in docs:
        with urlopen('http://127.0.0.1:38223/v1/dashboard/deliverables/' + item['id'], timeout=60) as response:
            content = response.read()
            assert len(content) == item['bytes']
            downloads.append({'id': item['id'], 'bytes': len(content), 'mime': response.headers['Content-Type'],
                              'sha256': hashlib.sha256(content).hexdigest()})
    reference = get('/v1/demo/reference/' + instance)['reference']
    legacy = {'configuration_identity': get('/v1/config', 43989)['identity'],
              'active_model_id': get('/v1/models', 43989)['active_model_id'],
              'auto_enabled': get('/v1/lab/control', 43989)['auto_enabled']}
    evidence = {'at_utc': datetime.now(UTC).isoformat(), 'status': 'passed', 'identity': config,
        'active_model_id': get('/v1/models')['active_model_id'], 'instance_id': instance,
        'network_state': network['state'], 'traffic_run_id': traffic['run_id'], 'traffic_state': traffic['state'],
        'collector': {k: collector.get(k) for k in ['live', 'observation_age_s', 'expires_utc', 'remaining_s', 'status']},
        'fresh_complete_windows': windows, 'nominal_reference_created_utc': reference['created_utc'],
        'control': control, 'approved_downloads': downloads, 'separate_observed_profile': legacy,
        'automatic_cleanup': False, 'foreground_terminals_required': 0,
        'expiry_policy': 'Workload and collector last900s from start; finite, no silent extension. Keep WSL/Windows awake.'}
    atomic_json(ROOT / 'artifacts/completion_stage4/final_live_check.json', evidence)
    session.update(measurement_evidence=windows, collector=collector, verified_utc=evidence['at_utc'])
    atomic_json(ROOT / 'artifacts/completion_stage4/demo_session.json', session)
    print(json.dumps({'status': 'passed', 'instance': instance, 'collector': evidence['collector'], 'windows': windows,
                      'downloads': len(downloads), 'automatic_repair': control['auto_enabled']}, indent=2))


if __name__ == '__main__':
    main()
