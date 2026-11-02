#!/usr/bin/env python3
"""Actual observed recovery demonstration; laboratory truth used only for setup."""
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.config import load_network, load_settings
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    WorkloadProfile,
)
from explainnet.storage import Store
from explainnet.twin_service import TwinService
from explainnet.workflow_contracts import LabStimulus

ROOT = Path(__file__).resolve().parents[1]


def main():
    config, tag = Path(sys.argv[1]), sys.argv[2]
    settings, out = load_settings(config), config.parent
    agent = AgentClient(settings.agent_socket)
    store = Store(settings.database_path)
    twins = TwinService(store, agent, settings.objective)
    old = json.loads((ROOT / 'artifacts/twin_validation_report.json').read_text())
    baseline = {k: old['pilot']['baseline'][k] for k in ('window_ids', 'definition_hash')}
    _, policy = twins.pilot_reference(**baseline)
    assert policy == old['pilot']['policy']
    report = {'stage': 11, 'status': 'running', 'tag': tag, 'config_file': str(config), 'app_uid': os.geteuid(),
        'cases': {}, 'checks': {}, 'errors': [], 'sealed_test_measurements_read': False,
        'production_model_available': False, 'observed_only_lab_exception_explicit': True}
    original = 'original_' + tag
    replacement = None

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        (ROOT / 'artifacts/recovery_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')

    def http(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{settings.port}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)

    def await_job(job_id):
        until = time.monotonic() + 120
        while time.monotonic() < until:
            result = http('/v1/jobs/' + job_id)
            if result['state'] in {'succeeded', 'failed', 'canceled'}:
                return result
            time.sleep(.25)
        raise TimeoutError('bounded job wait')

    def job(path, body):
        start = time.monotonic()
        commands = {'/v1/lab/mode': 'lab-mode', '/v1/lab/apply': 'lab-apply', '/v1/lab/undo': 'lab-undo'}
        if path in commands:
            payload_file = out / ('cli_' + uuid4().hex + '.json')
            payload_file.write_text(json.dumps(body))
            command = [str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(config), commands[path], str(payload_file)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
            submission = json.loads(result.stdout)
            report['checks'].setdefault('actual_cli_commands', []).append(command)
        else:
            submission = http(path, body)
        report['checks'].setdefault('submission_ms', []).append((time.monotonic() - start) * 1000)
        result = await_job(submission['job_id'])
        if result['state'] != 'succeeded':
            raise RuntimeError(result)
        return result['result']

    def request(name, max_hypotheses=2):
        return {'instance_id': original, 'workflow_id': 'w' + uuid4().hex, 'request_key': 'k' + uuid4().hex,
            'baseline': baseline, 'policy': policy, 'max_repairs': 1, 'max_hypotheses': max_hypotheses, 'timeout_s': 900}

    def wait_workflow(workflow_id, states, limit=930):
        until = time.monotonic() + limit
        previous = None
        while time.monotonic() < until:
            value = http('/v1/lab/workflows/' + workflow_id)
            progress = value['state']
            if progress == 'validating':
                try:
                    exp = http('/v1/recovery/' + value['experiment_id'])
                    progress += ': ' + exp['progress']
                except urllib.error.HTTPError:
                    pass
            if progress != previous:
                print(workflow_id + ': ' + progress, flush=True)
                previous = progress
            if value['state'] in states:
                return value
            if value['state'] in {'failed', 'refused', 'rolled_back'} and value['state'] not in states:
                raise RuntimeError(value.get('reasons') or value.get('error') or value['state'])
            time.sleep(.5)
        raise TimeoutError('bounded workflow polling expired')

    def start(name, hypotheses=2):
        body = request(name, hypotheses)
        (out / (name + '_workflow_request.json')).write_text(json.dumps(body, indent=2))
        job('/v1/lab/workflow', body)
        return body

    def cooldown():
        print('bounded cooldown before next experiment', flush=True)
        end = time.monotonic() + 122
        while time.monotonic() < end:
            time.sleep(1)

    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            if http('/v1/health')['worker_live']:
                break
        except Exception as exc:  # noqa: BLE001
            report['checks']['startup_retry'] = str(exc)
        time.sleep(.2)
    agent.network_start(NetworkStartRequest(instance_id=original, definition=load_network(settings.topology_file)))
    run = agent.traffic_start(TrafficStartRequest(instance_id=original, profiles=[WorkloadProfile(
        profile_id=p, source_host=a, target_host=b, protocol='udp', packet_size=1200, offered_bps=rate,
        duration_s=2400, warmup_s=3, stream_receiver=True, config_version='workflow_observation_v1')
        for p, a, b, rate in [('critical', 'h1', 'h3', 8_000_000), ('bulk', 'h2', 'h4', 5_000_000)]]))
    report['checks']['source_run_id'] = run['run_id']
    time.sleep(3)
    try:
        report['healthy_measurements'] = [twins.capture(original, 10)['window'] for _ in range(2)]
        body = start('healthy')
        report['cases']['healthy'] = wait_workflow(body['workflow_id'], {'refused'})
        assert 'service acceptable' in str(report['cases']['healthy']['reasons'])
        # Only this separate driver knows the selected train laboratory recipe.
        schedule = json.loads((ROOT / 'config/datasets/main_v1.json').read_text())
        chosen = next(e for e in schedule['episodes'] if e['partition'] == 'train' and e['episode_id'] == 'main_latency_f2_r0')
        (out / 'ground_truth.json').write_text(json.dumps(chosen, indent=2))
        agent.lab_test_stimulus(LabStimulus(instance_id=original, recipe=chosen['scenario']))
        selection = sys.argv[3:]
        if not selection:
            # Real stop during twin validation: no original actuation follows.
            job('/v1/lab/mode', {'mode': 'lab-auto-repair', 'allow_observed_only': True})
            body = start('stop')
            wait_workflow(body['workflow_id'], {'validating'})
            began = time.monotonic()
            stopped = http('/v1/lab/automation/stop', {})
            report['checks']['stop_ms'] = (time.monotonic() - began) * 1000
            report['checks']['stop_response'] = stopped
            report['cases']['stopped'] = wait_workflow(body['workflow_id'], {'refused', 'interrupted'})
            save()
            # One actual omitted hypothesis produces uncertainty, not a repair.
            body = start('uncertain', 1)
            report['cases']['uncertain'] = wait_workflow(body['workflow_id'], {'refused'})
            assert report['cases']['uncertain']['candidate_result']['state'] == 'uncertain'
            save()
            body = start('assisted')
            recommended = wait_workflow(body['workflow_id'], {'recommended'})
            report['cases']['assisted_recommendation'] = recommended
            job('/v1/lab/mode', {'mode': 'assisted-repair', 'allow_observed_only': True})
            apply = {'workflow_id': body['workflow_id'], 'action_id': 'a' + uuid4().hex, 'request_key': 'k' + uuid4().hex}
            (out / 'assisted_apply_request.json').write_text(json.dumps(apply, indent=2))
            job('/v1/lab/apply', apply)
            report['cases']['assisted'] = wait_workflow(body['workflow_id'], {'succeeded'})
            report['checks']['duplicate_apply'] = job('/v1/lab/apply', apply)
            assert report['checks']['duplicate_apply']['idempotent']
            # Undo restores forwarding while the original impairment/demand continue.
            undo = {'instance_id': original, 'action_id': apply['action_id'], 'request_key': 'u' + uuid4().hex}
            (out / 'undo_request.json').write_text(json.dumps(undo, indent=2))
            report['checks']['undo'] = job('/v1/lab/undo', undo)
            report['checks']['after_undo_window'] = twins.capture(original, 10)['window']
            assert report['checks']['after_undo_window']['features']['rtt_mean_ms'] > 20
            # Old recommendation/version cannot be applied twice under a new ID.
            job('/v1/lab/apply', apply | {'action_id': 'a' + uuid4().hex, 'request_key': 'k' + uuid4().hex})
            report['checks']['stale_application'] = wait_workflow(body['workflow_id'], {'refused'})
            blocked = await_job(http('/v1/lab/workflow', request('cooldown'))['job_id'])
            assert blocked['state'] == 'failed' and 'cooldown' in blocked['error']
            report['checks']['cooldown'] = blocked
            save()
            cooldown()
        else:
            body = {'workflow_id': None}
        if selection not in (['failures'], ['interrupted']):
            # Autonomous thread is triggered by the continuous receiver-aware sampler.
            job('/v1/telemetry/start', {'instance_id': original, 'duration_s': 600})
            job('/v1/lab/mode', {'mode': 'lab-auto-repair', 'allow_observed_only': True})
            previous_id = http('/v1/lab/control').get('active_workflow_id')
            watch = request('auto')
            job('/v1/lab/automation/start', watch)
            until = time.monotonic() + 60
            auto_id = None
            while time.monotonic() < until:
                ctl = http('/v1/lab/control')
                if ctl.get('active_workflow_id') != previous_id:
                    auto_id = ctl.get('active_workflow_id')
                    if auto_id:
                        break
                time.sleep(.5)
            if not auto_id:
                raise TimeoutError('continuous observed telemetry did not trigger automation')
            report['cases']['auto'] = wait_workflow(auto_id, {'succeeded'})
            time.sleep(12)
            report['checks']['healthy_after_auto_no_repeat'] = http('/v1/lab/control')['active_workflow_id'] == auto_id
            http('/v1/lab/automation/stop', {})
            job('/v1/telemetry/stop', {'instance_id': original})
            auto_action = report['cases']['auto']['action_id']
            report['checks']['auto_undo'] = job('/v1/lab/undo', {'instance_id': original, 'action_id': auto_action, 'request_key': 'u' + uuid4().hex})
            save()
            cooldown()
        for name, hook in [('verification_rollback', 'verification_failure'), ('partial_rollback', 'partial_failure'),
                ('interrupted', 'interrupt_after_apply')]:
            if selection == ['interrupted'] and name != 'interrupted':
                continue
            body = start(name)
            wait_workflow(body['workflow_id'], {'recommended'})
            job('/v1/lab/mode', {'mode': 'assisted-repair', 'allow_observed_only': True})
            action = {'workflow_id': body['workflow_id'], 'action_id': 'a' + uuid4().hex, 'request_key': 'k' + uuid4().hex, 'test_hook': hook}
            job('/v1/lab/apply', action)
            report['cases'][name] = wait_workflow(body['workflow_id'], {'interrupted' if name == 'interrupted' else 'rolled_back'})
            report['checks'][name + '_window'] = twins.capture(original, 10)['window']
            save()
            if name != 'interrupted':
                cooldown()
            else:
                # Kill only the supervisor-recorded API process, after verifying identity.
                identity = json.loads((out / 'api_pid.json').read_text())
                stat = Path('/proc/' + str(identity['pid']) + '/stat').read_text().split(')', 1)[1].split()[19]
                cmdline = Path('/proc/' + str(identity['pid']) + '/cmdline').read_bytes()
                assert stat == identity['start_ticks'] and str(config).encode() in cmdline
                os.kill(identity['pid'], signal.SIGKILL)
                time.sleep(1)
                replacement = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'explainnet.cli', '--config', str(config), 'serve'],
                    cwd=ROOT, stdout=(out / 'restarted_api.log').open('w'), stderr=subprocess.STDOUT)
                ready_until = time.monotonic() + 60
                while time.monotonic() < ready_until:
                    try:
                        if http('/v1/health')['worker_live']:
                            break
                    except urllib.error.URLError:
                        pass
                    if replacement.poll() is not None:
                        raise RuntimeError('restarted API exited; inspect restarted_api.log')
                    time.sleep(.25)
                else:
                    raise TimeoutError('restarted API readiness deadline expired')
                restored = wait_workflow(body['workflow_id'], {'rolled_back'}, 60)
                report['cases']['restart_reconciled'] = restored
                report['checks']['restart_control'] = http('/v1/lab/control')
                assert not report['checks']['restart_control']['auto_enabled']
                report['checks']['restart_restoration_window'] = twins.capture(original, 10)['window']
        report['checks']['final_control'] = http('/v1/lab/automation/stop', {})
        report['checks']['original_final_run'] = agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=run['run_id']))['state']
        assert report['checks']['original_final_run'] == 'running'
        report['status'] = 'packet_batch_finished'
    except Exception as exc:  # noqa: BLE001 - retain every failed actual attempt
        report['status'] = 'failed'
        report['errors'].append({'error': str(exc), 'traceback': traceback.format_exc()})
        print(traceback.format_exc(), flush=True)
    finally:
        try:
            http('/v1/lab/automation/stop', {})
        except Exception as exc:  # noqa: BLE001
            report['checks']['stop_cleanup_error'] = str(exc)
        if replacement:
            replacement.terminate()
            replacement.wait(timeout=100)
        try:
            agent.network_cleanup(InstanceRequest(instance_id=original))
        except Exception as exc:  # noqa: BLE001
            report['checks']['original_cleanup_error'] = str(exc)
        save()
    return 0 if report['status'] == 'packet_batch_finished' else 1


if __name__ == '__main__':
    sys.exit(main())
