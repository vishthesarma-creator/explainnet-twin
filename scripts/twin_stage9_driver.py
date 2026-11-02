#!/usr/bin/env python3
"""Unprivileged real packet verification. Truth used only to start fresh train cases."""
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
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    WorkloadProfile,
)
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.storage import Store
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest

ROOT = Path(__file__).resolve().parents[1]


def main():
    config, tag = Path(sys.argv[1]), sys.argv[2]
    settings = load_settings(config)
    out = config.parent
    agent = AgentClient(settings.agent_socket)
    store = Store(settings.database_path)
    service = TwinService(store, agent, settings.objective)
    definition = load_network(settings.topology_file)
    report = {'schema_version': 1, 'status': 'running', 'app_uid': os.geteuid(), 'tag': tag,
        'config_file': str(config), 'cases': {}, 'checks': {}, 'errors': [], 'pilot': {},
        'sealed_test_partition_accessed': False, 'repairs_executed': False}
    prior = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else None
    if prior:
        report = prior | {'status': 'running', 'extra_tag': tag, 'extra_config_file': str(config),
            'prior_report_file': str(Path(sys.argv[3]).resolve())}

    def checkpoint():
        (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        (ROOT / 'artifacts/twin_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')

    def http(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{settings.port}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)

    def job(path, body, file_name=None):
        if file_name:
            (out / file_name).write_text(json.dumps(body, indent=2))
        started = time.monotonic()
        submission = http(path, body)
        report['checks'].setdefault('job_submission_ms', []).append((time.monotonic() - started) * 1000)
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            result = http('/v1/jobs/' + submission['job_id'])
            if result['state'] in {'succeeded', 'failed', 'canceled'}:
                if result['state'] != 'succeeded':
                    raise RuntimeError(result)
                return result['result']
            time.sleep(.2)
        raise TimeoutError('job exceeded 100 second bound')

    def start_case(name, recipe):
        original = 'original_' + tag + '_' + name
        agent.network_start(NetworkStartRequest(instance_id=original, definition=definition))
        scenario = agent.scenario_start(ScenarioStartRequest(instance_id=original, scenario=recipe))
        # Archive the experimental configuration exclusively as laboratory truth.
        (out / ('ground_truth_' + name + '.json')).write_text(json.dumps(recipe, indent=2))
        return original, scenario

    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        try:
            if http('/v1/health')['worker_live']:
                break
        except Exception as exc:  # noqa: BLE001 - bounded startup retry
            report['checks']['last_startup_retry'] = str(exc)
        time.sleep(.2)
    schedule = json.loads((ROOT / 'config/datasets/main_v1.json').read_text())
    # Only select train entries. Never export, diagnose or execute a sealed test entry.
    train = [e for e in schedule['episodes'] if e['partition'] == 'train']
    recipes = {}
    for name in ('healthy', 'saturation', 'loss', 'latency', 'qos'):
        eligible = [e for e in train if e['scenario']['kind'] == name]
        chosen = next((e for e in eligible if e['scenario']['severity'] == 'medium'), eligible[0])
        recipes[name] = chosen['scenario'] | {'measurement_s': 100, 'warmup_s': 3}
    originals, twins = [], []
    try:
        if prior:
            run_extra(report, agent, service, definition, job, http, settings, out, tag, originals, twins, checkpoint)
            report['status'] = 'packet_batch_finished'
            checkpoint()
            return 0
        original, _ = start_case('pilot', recipes['healthy'])
        originals.append(original)
        print('Stage 9: nominal pilot started', flush=True)
        pilots = [service.capture(original, 15), service.capture(original, 15)]
        window_ids = [p['window']['window_id'] for p in pilots]
        baseline = {'window_ids': window_ids, 'definition_hash': digest(definition.model_dump())}
        reference, policy = service.pilot_reference(**baseline)
        report['pilot'] = {'windows': [p['window'] for p in pilots], 'background': [p['background_probe'] for p in pilots],
            'baseline': reference, 'policy': policy, 'frozen_before_fault_verification': True}
        checkpoint()
        agent.network_cleanup(InstanceRequest(instance_id=original))
        for name, recipe in recipes.items():
            case = report['cases'][name] = {'state': 'running', 'trials': []}
            original, _scenario = start_case(name, recipe)
            originals.append(original)
            twin = 'tw_' + tag + '_' + name
            twins.append(twin)
            print('Stage 9: ' + name + ' original started', flush=True)
            try:
                snap = job('/v1/twins/snapshot', {'instance_id': original, 'request_key': 'key_' + tag + '_' + name,
                    'baseline': baseline, 'policy': policy, 'duration_s': 15, 'expiry_s': 180}, name + '_snapshot_request.json')
                case['snapshot'], case['reconstruction'] = snap['snapshot'], snap['reconstruction']
                checkpoint()
                construction = job('/v1/twins/construct', {'twin_id': twin, 'snapshot_id': snap['snapshot']['snapshot_id']}, name + '_construct_request.json')
                case['construction'] = construction
                if construction['state'] != 'running':
                    case['state'] = construction['state']
                    continue
                own, other = snap['snapshot']['ownership'], construction['ownership']
                checks = {key: not set(own[key]) & set(other[key]) for key in ('bridges', 'interfaces')}
                for key in ('name', 'ip', 'namespace'):
                    checks['host_' + key] = not {h[key] for h in own['hosts'].values()} & {h[key] for h in other['hosts'].values()}
                checks['dpids'] = not {s['dpid'] for s in own['switches'].values()} & {s['dpid'] for s in other['switches'].values()}
                case['isolation_identifiers'] = checks
                assert all(checks.values()), checks
                trial = job('/v1/twins/measure', {'twin_id': twin, 'trial_id': 'trial_' + tag + '_' + name,
                    'duration_s': 15}, name + '_measure_request.json')
                case['trials'].append(trial)
                case['state'] = trial['state']
                checkpoint()
                if name == 'healthy':
                    reset = job('/v1/twins/reset', {'twin_id': twin}, name + '_reset_request.json')
                    case['reset'] = reset
                    case['fresh_runtime_token_after_reset'] = reset.get('ownership', {}).get('token') != other['token']
                    case['trials'].append(job('/v1/twins/measure', {'twin_id': twin,
                        'trial_id': 'reset_' + tag, 'duration_s': 15}))
                elif name in {'loss', 'latency'} and len(snap['reconstruction']['hypotheses']) > 1:
                    # One bounded alternate hypothesis; do not optimize tolerances.
                    second = snap['reconstruction']['hypotheses'][1]['hypothesis_id']
                    reset = job('/v1/twins/reset', {'twin_id': twin, 'hypothesis_id': second})
                    case['alternate_reset'] = reset
                    if reset['state'] == 'running':
                        case['trials'].append(job('/v1/twins/measure', {'twin_id': twin,
                            'trial_id': 'alternate_' + tag + '_' + name, 'duration_s': 15}))
                original_run = agent.network_inspect(InstanceRequest(instance_id=original))['runs'][-1]
                before = agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=original_run))
                case['destroy'] = job('/v1/twins/destroy', {'twin_id': twin})
                probe = agent.network_probe(ProbeRequest(instance_id=original, source_host='h1', target_host='h3'))
                after = agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=before['run_id']))
                case['original_after_destroy'] = {'state_before': before['state'], 'state_after': after['state'], 'probe': probe,
                    'same_traffic_run': before['run_id'] == after['run_id']}
            except Exception as exc:  # noqa: BLE001 - report every class independently
                case.update(state='failed', error=str(exc), traceback=traceback.format_exc())
                print(name + ': ' + str(exc), flush=True)
            finally:
                try:
                    job('/v1/twins/destroy', {'twin_id': twin})
                except Exception as cleanup:  # noqa: BLE001
                    case['final_cleanup_error'] = str(cleanup)
                agent.network_cleanup(InstanceRequest(instance_id=original))
                checkpoint()
        report['status'] = 'packet_batch_finished'
    except Exception as exc:  # noqa: BLE001
        report['status'] = 'blocked'
        report['errors'].append({'error': str(exc), 'traceback': traceback.format_exc()})
        print(traceback.format_exc(), flush=True)
    finally:
        for original in originals:
            try:
                agent.network_cleanup(InstanceRequest(instance_id=original))
            except Exception as cleanup:  # noqa: BLE001
                report['checks'].setdefault('original_cleanup_errors', []).append(str(cleanup))
        checkpoint()
    return 0 if report['status'] != 'blocked' else 1


def run_extra(report, agent, service, definition, job, http, settings, out, tag, originals, twins, checkpoint):
    baseline = {k: report['pilot']['baseline'][k] for k in ('window_ids', 'definition_hash')}
    policy = report['pilot']['policy']

    def original(name, stream=True):
        instance = 'original_' + tag + '_' + name
        agent.network_start(NetworkStartRequest(instance_id=instance, definition=definition))
        run = agent.traffic_start(TrafficStartRequest(instance_id=instance, profiles=[WorkloadProfile(
            profile_id=p, source_host=a, target_host=b, protocol='udp', packet_size=1200,
            offered_bps=rate, duration_s=100, warmup_s=3, stream_receiver=stream)
            for p, a, b, rate in [('critical', 'h1', 'h3', 6000000), ('bulk', 'h2', 'h4', 5000000)]]))
        originals.append(instance)
        time.sleep(3)
        return instance, run['run_id']

    def snapshot(instance, name, expiry=180):
        body = {'instance_id': instance, 'request_key': 'key_' + tag + '_' + name,
            'baseline': baseline, 'policy': policy, 'duration_s': 15, 'expiry_s': expiry}
        return job('/v1/twins/snapshot', body, name + '_snapshot_request.json'), body

    mode = sys.argv[4] if len(sys.argv) > 4 else 'all'
    names = {'recovery': ('calibration', 'cancel', 'drift'), 'timing': ('calibration', 'drift'),
        'calibration': ('calibration',)}.get(mode, ('missing_receiver', 'expiry', 'drift', 'cancel'))
    for name in names:
        print('Stage 9: extra ' + name, flush=True)
        if name in report['cases']:
            report.setdefault('earlier_attempts', {}).setdefault(name, []).append(report['cases'][name])
        case = report['cases'][name] = {'state': 'running'}
        instance, run_id = original(name, stream=name != 'missing_receiver')
        twin = 'tw_' + tag + '_' + name
        twins.append(twin)
        try:
            snap, body = snapshot(instance, name, expiry=10 if name == 'expiry' else 180)
            case['snapshot'], case['reconstruction'] = snap['snapshot'], snap['reconstruction']
            repeated = job('/v1/twins/snapshot', body)
            case['snapshot_idempotent'] = repeated['snapshot']['snapshot_hash'] == snap['snapshot']['snapshot_hash']
            if name == 'expiry':
                time.sleep(11)
            construction = job('/v1/twins/construct', {'twin_id': twin, 'snapshot_id': snap['snapshot']['snapshot_id']}, name + '_construct_request.json')
            case['construction'] = construction
            if name in {'expiry', 'missing_receiver'}:
                case['state'] = construction['state']
                assert construction['state'] == ('stale' if name == 'expiry' else 'unsupported'), construction
            elif name == 'calibration':
                case['bounded_calibration'] = job('/v1/twins/calibrate', {'twin_id': twin,
                    'operation_id': 'calibration_' + tag, 'max_trials': 2, 'duration_s': 15}, name + '_calibrate_request.json')
                case['repeated_calibration'] = job('/v1/twins/calibrate', {'twin_id': twin,
                    'operation_id': 'calibration_' + tag, 'max_trials': 2, 'duration_s': 15})
                case['state'] = case['bounded_calibration']['trials'][0]['state']
                assert case['bounded_calibration'] == case['repeated_calibration']
                # Exercise the installed CLI construction/measurement/reset job paths.
                commands = []
                for action, payload in [('construct', {'twin_id': twin, 'snapshot_id': snap['snapshot']['snapshot_id']}),
                        ('measure', {'twin_id': twin, 'trial_id': case['bounded_calibration']['trials'][0]['trial_id'], 'duration_s': 15})]:
                    request_file = out / ('cli_' + action + '.json')
                    request_file.write_text(json.dumps(payload))
                    result = subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(out / 'config.json'),
                        'twin-' + action, str(request_file)], capture_output=True, text=True, timeout=25, check=True)
                    commands.append({'action': action, 'submission': json.loads(result.stdout)})
                case['cli_commands'] = commands
            elif name == 'drift':
                case['baseline_trial'] = job('/v1/twins/measure', {'twin_id': twin, 'trial_id': 'extra_baseline_' + tag, 'duration_s': 15})
                # Deliberate operator demand change for the drift test; no candidate repair.
                new_run = agent.traffic_start(TrafficStartRequest(instance_id=instance, profiles=[WorkloadProfile(
                    profile_id='background', source_host='h5', target_host='h6', protocol='udp', packet_size=1200,
                    offered_bps=1000000, duration_s=100, warmup_s=0, stream_receiver=True)]))
                case['deliberate_workload_change'] = {'new_traffic_run_id': new_run['run_id'], 'purpose': 'drift verification only'}
                case['status_after_drift'] = http('/v1/twins/' + twin)
                case['obsolete_trial'] = job('/v1/twins/measure', {'twin_id': twin, 'trial_id': 'drift_' + tag, 'duration_s': 15})
                case['destroy'] = job('/v1/twins/destroy', {'twin_id': twin})
                case['traffic_immediately_after_destroy'] = agent.traffic_status(TrafficRunRequest(instance_id=instance, run_id=run_id))['state']
                assert case['traffic_immediately_after_destroy'] == 'running'
                fresh, _ = snapshot(instance, 'refreshed_drift')
                case['fresh_snapshot'] = fresh['snapshot']
                case['state'] = case['obsolete_trial']['state']
                assert case['state'] == 'stale' and fresh['snapshot']['snapshot_hash'] != snap['snapshot']['snapshot_hash']
                cli = subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(out / 'config.json'),
                    'twin-status', twin], capture_output=True, text=True, timeout=25, check=True)
                case['actual_cli_status'] = json.loads(cli.stdout)
            else:
                submission = http('/v1/twins/measure', {'twin_id': twin, 'trial_id': 'cancel_' + tag, 'duration_s': 20})
                time.sleep(1)
                case['cancel_request'] = http('/v1/twins/cancel', {'twin_id': twin})
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    canceled = http('/v1/jobs/' + submission['job_id'])
                    if canceled['state'] in {'failed', 'canceled', 'succeeded'}:
                        break
                    time.sleep(.2)
                case['canceled_job'] = canceled
                case['state'] = 'canceled' if 'canceled' in str(canceled) else 'failed'
                assert case['state'] == 'canceled'
            case['destroy'] = job('/v1/twins/destroy', {'twin_id': twin})
            case['original_after_destroy'] = {'traffic': agent.traffic_status(TrafficRunRequest(instance_id=instance, run_id=run_id))['state'],
                'probe': agent.network_probe(ProbeRequest(instance_id=instance, source_host='h1', target_host='h3'))}
            if name != 'drift':
                assert case['original_after_destroy']['traffic'] == 'running'
        except Exception as exc:  # noqa: BLE001 - retain explicit refusal/failure evidence
            case.update(state='failed', error=str(exc), traceback=traceback.format_exc())
            print(traceback.format_exc(), flush=True)
        finally:
            try:
                job('/v1/twins/destroy', {'twin_id': twin})
            except Exception as cleanup:  # noqa: BLE001
                case['cleanup_error'] = str(cleanup)
            agent.network_cleanup(InstanceRequest(instance_id=instance))
            checkpoint()


if __name__ == '__main__':
    sys.exit(main())
