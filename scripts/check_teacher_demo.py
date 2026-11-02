"""Bounded healthy lab check using existing API operations; never injects or repairs.

Use the separate Stage 14 supervisor for the qualified observed-only fault case.
This helper provides novice-friendly startup, current inference checks and scoped
cleanup for only the original instance recorded in its own receipt.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from explainnet.config import load_settings
from explainnet.model_bundle import BundleRepository
from explainnet.storage import Store

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / 'artifacts/teacher_demo/latest_live_check.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'artifacts/stage6/runtime/config.json')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError('Run this API helper with the ordinary user application venv, not root')
    cfg = load_settings(args.config)

    def http(path, body=None):
        request = urllib.request.Request(f'http://127.0.0.1:{cfg.port}' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', 'Idempotency-Key': 'teacher' + uuid4().hex})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def job(path, body):
        receipt = http(path, body)
        end = time.monotonic() + 130
        print('Submitted ' + path + ' job ' + receipt['job_id'], flush=True)
        while time.monotonic() < end:
            state = http('/v1/jobs/' + receipt['job_id'])
            if state['state'] in {'succeeded', 'failed', 'canceled', 'interrupted'}:
                if state['state'] != 'succeeded':
                    raise RuntimeError(str(state.get('error') or state['state']))
                return state['result']
            time.sleep(.5)
        raise TimeoutError('Unknown job outcome; inspect receipt. No mutation was retried.')

    control = http('/v1/lab/control')
    if control['auto_enabled'] or control['allow_observed_only'] or control.get('active_workflow_id'):
        raise ValueError('Stop automation/finish any workflow and clear the observed-only exception before this healthy check')
    if args.cleanup:
        if not LATEST.exists():
            print('No healthy-check receipt exists; nothing to clean.'); return
        saved = json.loads(LATEST.read_text())
        if saved['config_hash'] != cfg.config_hash or not saved['instance_id'].startswith('teacher_'):
            raise ValueError('Healthy-check receipt/config mismatch; no resource changed')
        instance = saved['instance_id']
        # Kept actions require deliberate Undo/inspection before teardown.
        if http('/v1/dashboard/reversible/' + instance).get('available'):
            raise ValueError('This original has a kept action. Inspect/Undo it before cleanup.')
        try:
            live = http('/v1/networks/' + instance)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            print('Recorded original no longer exists; nothing to clean.'); return
        if live.get('state') == 'stopped':
            print('Recorded original already stopped; nothing to clean.'); return
        job('/v1/telemetry/stop', {'instance_id': instance})
        job('/v1/laboratory/scenarios/reset', {'instance_id': instance})
        job('/v1/networks/cleanup', {'instance_id': instance})
        saved.update(cleaned_utc=datetime.now(UTC).isoformat(), final_control=http('/v1/lab/control'))
        LATEST.write_text(json.dumps(saved, indent=2) + '\n')
        print('Cleaned only ' + instance); return

    tag = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:4]
    out = ROOT / 'artifacts/teacher_demo/healthy_checks' / tag
    out.mkdir(parents=True)
    sources = ['artifacts/stage13/dataset_audit.json', 'artifacts/stage13/held_out_metrics.json',
        'artifacts/stage13/frozen_evaluation.json', 'artifacts/stage13/posthoc_provenance.json',
        'artifacts/evaluation_validation_report.json', 'artifacts/integration_validation_report.json',
        'config/recovery_policy_v1.json', 'config/evaluation_stage13.json', 'artifacts/stage6/runtime/config.json']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    models = BundleRepository(Store(cfg.database_path))
    model_id = http('/v1/models')['active_model_id']
    bundle = models.load(model_id)
    instance = 'teacher_' + uuid4().hex[:12]
    result = {'started_utc': datetime.now(UTC).isoformat(), 'instance_id': instance,
        'config_hash': cfg.config_hash, 'config': str(args.config.resolve()), 'model_id': model_id,
        'bundle_compatible': True, 'calibration_ready': bundle['calibrator'] is not None,
        'source_hashes_before': hashes, 'status': 'running', 'fault_injected': False, 'repair_attempted': False,
        'workload': 'Canonical healthy_v1: 2,000,000 bps critical UDP and 5,000,000 bps bulk TCP, 100 seconds',
        'receipt': str(out / 'report.json')}

    def save():
        text = json.dumps(result, indent=2, allow_nan=False) + '\n'
        (out / 'report.json').write_text(text)
        LATEST.write_text(text)

    began = time.monotonic()
    try:
        result['construction'] = job('/v1/networks/start', {'instance_id': instance}); save()
        result['connectivity'] = job('/v1/networks/probe', {'instance_id': instance, 'source_host': 'h1', 'target_host': 'h3'})
        if not result['connectivity']['passed']:
            raise ValueError('Owned source connectivity failed')
        result['traffic'] = job('/v1/traffic/start', {'instance_id': instance, 'profile_ids': ['critical', 'bulk'],
            'duration_s': 100, 'stream_receiver': True})
        result['collector'] = job('/v1/telemetry/start', {'instance_id': instance, 'duration_s': 120})
        end = time.monotonic() + 50
        while time.monotonic() < end:
            windows = http('/v1/telemetry/' + instance + '/windows?ready_only=true')['windows']
            if windows:
                break
            time.sleep(1)
        else:
            raise ValueError('No quality-suitable window in bounded healthy check')
        window = windows[0]
        result['fresh_window'] = window
        result['diagnosis'] = job('/v1/models/infer', {'model_id': model_id, 'window_id': window['window_id'], 'mode': 'live'})
        explanation = job('/v1/explanations/request', {'model_id': model_id, 'window_id': window['window_id'], 'mode': 'live'})
        end = time.monotonic() + 45
        while explanation['status'] == 'pending' and time.monotonic() < end:
            time.sleep(.5)
            explanation = http('/v1/explanations/' + explanation['explanation_id'])
        result['current_explanation'] = explanation
        result['final_control'] = http('/v1/lab/control')
        result['source_hashes_unchanged'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
        result['status'] = 'healthy_check_completed'
        print(json.dumps({'instance_id': instance, 'window_id': window['window_id'], 'rtt_ms': window['features']['rtt_mean_ms'],
            'critical_bps': window['features']['critical_goodput_bps'], 'diagnosis_status': result['diagnosis'].get('status'),
            'explanation_status': explanation['status'], 'report': result['receipt']}, indent=2), flush=True)
        print('Healthy traffic ends after 100 seconds; collector after 120. Use --cleanup for this recorded original.', flush=True)
    except Exception as exc:
        result.update(status='failed', error=str(exc))
        raise
    finally:
        result['elapsed_ms'] = (time.monotonic() - began) * 1000
        save()


if __name__ == '__main__':
    main()
