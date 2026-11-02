#!/usr/bin/env python3
"""Unprivileged Stage 10 native trials; train recipes are setup truth only."""
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

from explainnet.agent import AgentClient
from explainnet.config import load_network, load_settings
from explainnet.network_contracts import InstanceRequest, NetworkStartRequest, ProbeRequest, TrafficRunRequest
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.storage import Store
from explainnet.twin_contracts import SnapshotRequest
from explainnet.twin_service import TwinService

ROOT = Path(__file__).resolve().parents[1]


def main():
    config, tag = Path(sys.argv[1]), sys.argv[2]
    settings, out = load_settings(config), config.parent
    agent, store = AgentClient(settings.agent_socket), Store(load_settings(config).database_path)
    twins = TwinService(store, agent, settings.objective)
    definition = load_network(settings.topology_file)
    prior = json.loads((ROOT / 'artifacts/twin_validation_report.json').read_text())
    baseline = {k: prior['pilot']['baseline'][k] for k in ('window_ids', 'definition_hash')}
    _reference, policy = twins.pilot_reference(**baseline)
    assert policy == prior['pilot']['policy'], 'fidelity tolerances changed'
    report = {'schema_version': 1, 'stage': 10, 'status': 'running', 'tag': tag, 'app_uid': os.geteuid(),
        'config_file': str(config), 'fidelity_policy': policy, 'cases': {}, 'checks': {}, 'errors': [],
        'original_repairs_executed': False, 'sealed_test_partition_accessed': False,
        'production_model_available': False, 'stage9_report_file': str(ROOT / 'artifacts/twin_validation_report.json')}

    def checkpoint():
        (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        (ROOT / 'artifacts/candidate_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')

    def http(path, body=None):
        request = urllib.request.Request(f'http://127.0.0.1:{settings.port}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    def job(path, body, filename):
        (out / filename).write_text(json.dumps(body, indent=2) + '\n')
        start = time.monotonic()
        submission = http(path, body)
        report['checks'].setdefault('submission_ms', []).append((time.monotonic() - start) * 1000)
        end = time.monotonic() + 760
        last_progress = None
        while time.monotonic() < end:
            record = http('/v1/jobs/' + submission['job_id'])
            if record['state'] in {'succeeded', 'failed', 'canceled'}:
                if record['state'] != 'succeeded':
                    raise RuntimeError(record)
                return record['result']
            if path == '/v1/recovery/test':
                try:
                    current = http('/v1/recovery/' + body['operation_id'])
                    progress = current['progress']
                    if progress != last_progress:
                        print(body['operation_id'] + ': ' + progress, flush=True)
                        last_progress = progress
                except urllib.error.HTTPError:
                    pass
            time.sleep(.5)
        raise TimeoutError('bounded job polling expired')

    startup = time.monotonic() + 40
    while time.monotonic() < startup:
        try:
            if http('/v1/health')['worker_live']:
                break
        except Exception as exc:  # noqa: BLE001 - finite startup retry
            report['checks']['last_startup_retry'] = str(exc)
        time.sleep(.2)
    schedule = json.loads((ROOT / 'config/datasets/main_v1.json').read_text())
    train = [e for e in schedule['episodes'] if e['partition'] == 'train']
    names = sys.argv[3:] or ['latency', 'healthy', 'saturation', 'loss', 'qos']
    originals = []
    try:
        for name in names:
            kind = 'latency' if name == 'latency_udp' else name
            eligible = [e for e in train if e['scenario']['kind'] == kind]
            chosen = next((e for e in eligible if e['scenario']['severity'] == 'high' and e['scenario']['bulk_protocol'] == 'udp'), eligible[0]) if name == 'latency_udp' else next((e for e in eligible if e['scenario']['severity'] == 'medium'), eligible[0])
            recipe = chosen['scenario']
            recipe = recipe | {'config_version': 'recovery_observation_v1', 'measurement_s': 900, 'warmup_s': 3}
            original = 'original_' + tag + '_' + name
            target = 'tw_' + tag + '_' + name
            case = report['cases'][name] = {'state': 'running', 'permitted_partition': 'train',
                'source_episode_id': chosen['episode_id'],
                'controlled_override': 'finite 900s observation lifetime; fault and demand parameters retained'}
            # Truth is archived separately and only passed to original setup.
            (out / ('ground_truth_' + name + '.json')).write_text(json.dumps(recipe, indent=2) + '\n')
            agent.network_start(NetworkStartRequest(instance_id=original, definition=definition))
            scenario = agent.scenario_start(ScenarioStartRequest(instance_id=original, scenario=recipe))
            originals.append(original)
            run_id = scenario['traffic_runs'][0]['run_id']
            print(name + ': source experiment running', flush=True)
            try:
                snap = job('/v1/twins/snapshot', SnapshotRequest(instance_id=original, request_key='key_' + tag + '_' + name,
                    baseline=baseline, policy=policy, duration_s=15, expiry_s=900).model_dump(), name + '_snapshot_request.json')
                case['snapshot'], case['reconstruction'] = snap['snapshot'], snap['reconstruction']
                payload = {'operation_id': 'recovery_' + tag + '_' + name, 'snapshot_id': snap['snapshot']['snapshot_id'],
                    'twin_id': target, 'max_repairs': 3 if name in {'latency', 'latency_udp', 'healthy'} else 2,
                    'repetitions': 2, 'max_hypotheses': 2, 'duration_s': 10, 'seed': 20261010, 'timeout_s': 700}
                case['plan'] = job('/v1/recovery/plan', payload, name + '_plan_request.json')
                before = agent.twin_view(InstanceRequest(instance_id=original))
                run_before = agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=run_id))
                checkpoint()
                result = job('/v1/recovery/test', payload, name + '_test_request.json')
                case['experiment'], case['state'] = result, result['state']
                after = agent.twin_view(InstanceRequest(instance_id=original))
                run_after = agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=run_id))
                probe = agent.network_probe(ProbeRequest(instance_id=original, source_host='h1', target_host='h3'))
                case['original_preservation'] = {'same_fingerprint': before['fingerprint'] == after['fingerprint'],
                    'same_runtime_token': before['ownership']['token'] == after['ownership']['token'],
                    'same_workload': before['workload'] == after['workload'],
                    'run_id': run_id, 'run_state_before': run_before['state'], 'run_state_after': run_after['state'],
                    'native_forwarding_probe': probe,
                    'all_trial_configuration_digests_unchanged': all(t.get('original_unchanged') for t in result['trials']
                        if t.get('capture_id'))}
                assert case['original_preservation']['same_fingerprint']
                assert run_after['state'] == 'running'
                case['duplicate_submission'] = job('/v1/recovery/test', payload, name + '_duplicate_request.json') == (result | {'idempotent': True})
                retrieved = http('/v1/recovery/' + payload['operation_id'])
                case['retrieval_state_before_original_cleanup'] = retrieved['state']
                if name in {'latency', 'latency_udp'}:
                    cli = subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(config),
                        'recovery-get', payload['operation_id']], cwd=ROOT, capture_output=True, text=True, timeout=25, check=True)
                    (out / 'cli_recommendation.json').write_text(cli.stdout)
                    case['cli_retrieval_matches'] = json.loads(cli.stdout)['state'] == retrieved['state']
                print(name + ': ' + result['state'], flush=True)
            except Exception as exc:  # noqa: BLE001 - honest separate case outcomes
                case.update(state='failed', error=str(exc), traceback=traceback.format_exc())
                print(traceback.format_exc(), flush=True)
            finally:
                agent.network_cleanup(InstanceRequest(instance_id=original))
                checkpoint()
        report['status'] = 'packet_batch_finished'
    finally:
        for original in originals:
            agent.network_cleanup(InstanceRequest(instance_id=original))
        checkpoint()
    return 0


if __name__ == '__main__':
    sys.exit(main())
