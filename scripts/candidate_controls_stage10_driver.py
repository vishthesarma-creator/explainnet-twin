#!/usr/bin/env python3
"""Actual cancellation, expiry, external drift and original-target refusal."""
import json
import sys
import time
import urllib.request
from pathlib import Path

from explainnet.agent import AgentClient, AgentUnavailable
from explainnet.config import load_network, load_settings
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    WorkloadProfile,
)
from explainnet.recovery_contracts import AgentRecoveryAction
from explainnet.recovery_spec import POLICY_HASH
from explainnet.storage import Store
from explainnet.twin_contracts import ConstructRequest, TwinRequest
from explainnet.twin_service import TwinService

ROOT = Path(__file__).resolve().parents[1]


def main():
    config, tag = Path(sys.argv[1]), sys.argv[2]
    settings, out = load_settings(config), config.parent
    agent = AgentClient(settings.agent_socket)
    twins = TwinService(Store(settings.database_path), agent, settings.objective)
    prior = json.loads((ROOT / 'artifacts/twin_validation_report.json').read_text())
    baseline = {k: prior['pilot']['baseline'][k] for k in ('window_ids', 'definition_hash')}
    _, policy = twins.pilot_reference(**baseline)
    report = {'stage': 10, 'kind': 'native_controls', 'tag': tag, 'config_file': str(config), 'checks': {},
        'original_repairs_executed': False, 'sealed_test_accessed': False}

    def http(path, body=None):
        request = urllib.request.Request(f'http://127.0.0.1:{settings.port}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    def await_job(job_id):
        until = time.monotonic() + 120
        while time.monotonic() < until:
            record = http('/v1/jobs/' + job_id)
            if record['state'] in {'succeeded', 'failed', 'canceled'}:
                return record
            time.sleep(.2)
        raise TimeoutError('control job polling expired')

    def job(path, body):
        result = await_job(http(path, body)['job_id'])
        if result['state'] != 'succeeded':
            raise RuntimeError(result)
        return result['result']

    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            if http('/v1/health')['worker_live']:
                break
        except Exception as exc:  # noqa: BLE001
            report['checks']['last_startup_retry'] = str(exc)
        time.sleep(.2)
    original = 'original_' + tag + '_controls'
    agent.network_start(NetworkStartRequest(instance_id=original, definition=load_network(settings.topology_file)))
    run = agent.traffic_start(TrafficStartRequest(instance_id=original, profiles=[WorkloadProfile(
        profile_id=p, source_host=a, target_host=b, protocol='udp', packet_size=1200,
        offered_bps=rate, duration_s=900, warmup_s=3, stream_receiver=True, config_version='recovery_observation_v1')
        for p, a, b, rate in [('critical', 'h1', 'h3', 6_000_000), ('bulk', 'h2', 'h4', 5_000_000)]]))
    time.sleep(3)

    def snapshot(name, expiry=900):
        return job('/v1/twins/snapshot', {'instance_id': original, 'request_key': 'key_' + tag + '_' + name,
            'baseline': baseline, 'policy': policy, 'duration_s': 15, 'expiry_s': expiry})['snapshot']

    def request(name, snap):
        return {'operation_id': 'recovery_' + tag + '_' + name, 'snapshot_id': snap['snapshot_id'],
            'twin_id': 'tw_' + tag + '_' + name, 'max_repairs': 2, 'repetitions': 2,
            'max_hypotheses': 2, 'duration_s': 10, 'timeout_s': 700, 'seed': 20261010}

    try:
        fresh = snapshot('cancel')
        before = agent.twin_view(InstanceRequest(instance_id=original))
        body = request('cancel', fresh)
        submitted = http('/v1/recovery/test', body)
        until = time.monotonic() + 50
        while time.monotonic() < until:
            try:
                state = http('/v1/recovery/' + body['operation_id'])
                if state['trials']:
                    break
            except urllib.error.HTTPError:
                pass
            time.sleep(.2)
        time.sleep(8)
        began = time.monotonic()
        canceled = http('/v1/recovery/cancel', {'operation_id': body['operation_id']})
        cancel_ms = (time.monotonic() - began) * 1000
        terminal = await_job(submitted['job_id'])
        assert terminal['state'] == 'canceled', terminal
        actual = http('/v1/recovery/' + body['operation_id'])
        after = agent.twin_view(InstanceRequest(instance_id=original))
        report['checks']['cancellation'] = {'response': canceled, 'elapsed_ms': cancel_ms, 'job': terminal,
            'experiment': actual, 'original_fingerprint_unchanged': before['fingerprint'] == after['fingerprint'],
            'original_run_state': agent.traffic_status(TrafficRunRequest(instance_id=original, run_id=run['run_id']))['state']}
        assert before['fingerprint'] == after['fingerprint']
        assert report['checks']['cancellation']['original_run_state'] == 'running'
        assert job('/v1/jobs/environment-check', {})['agent_status'] == 'available'
        print('actual cancellation confirmed; original still running', flush=True)
        control = {'family': 'no_change', 'changes': [], 'policy_hash': POLICY_HASH}
        try:
            agent.twin_apply_candidate(AgentRecoveryAction(twin_id=original, snapshot_hash=fresh['snapshot_hash'], action=control))
        except AgentUnavailable as exc:
            report['checks']['original_target_refused'] = str(exc)
        else:
            raise AssertionError('root accepted original execution')
        target = 'tw_' + tag + '_guard'
        twins.construct(ConstructRequest(twin_id=target, snapshot_id=fresh['snapshot_id']))
        report['checks']['guard_application'] = agent.twin_apply_candidate(AgentRecoveryAction(
            twin_id=target, snapshot_hash=fresh['snapshot_hash'], action=control))
        try:
            agent.twin_apply_candidate(AgentRecoveryAction(twin_id=target, snapshot_hash=fresh['snapshot_hash'], action=control))
        except AgentUnavailable as exc:
            report['checks']['cumulative_application_refused'] = str(exc)
        else:
            raise AssertionError('root accepted cumulative application')
        report['checks']['guard_cleanup'] = twins.destroy(TwinRequest(twin_id=target))
        expired = snapshot('expiry', 10)
        time.sleep(11)
        expiry = job('/v1/recovery/test', request('expiry', expired))
        assert expiry['state'] == 'stale' and not expiry['trials'], expiry
        report['checks']['expiry'] = expiry
        drift_snap = snapshot('drift')
        drift_request = request('drift', drift_snap)
        assert not job('/v1/recovery/plan', drift_request)['stale_reasons']
        # Explicit adversarial verification stimulus, not a repair. The original
        # workload changes here by design; no candidate trial is run afterward.
        drift = agent.traffic_start(TrafficStartRequest(instance_id=original, profiles=[WorkloadProfile(
            profile_id='external_drift', source_host='h5', target_host='h6', protocol='udp', packet_size=1200,
            offered_bps=1_000_000, duration_s=900, stream_receiver=True, config_version='recovery_observation_v1')]))
        plan = job('/v1/recovery/plan', drift_request)
        refused = job('/v1/recovery/test', drift_request)
        assert plan['stale_reasons'] and refused['state'] == 'stale' and not refused['trials']
        report['checks']['external_workload_drift'] = {'stimulus_run_id': drift['run_id'], 'plan': plan,
            'refusal': refused, 'deliberate_external_change': True, 'repair_applied': False}
        report['status'] = 'passed'
    finally:
        agent.network_cleanup(InstanceRequest(instance_id=original))
        (out / 'controls_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
