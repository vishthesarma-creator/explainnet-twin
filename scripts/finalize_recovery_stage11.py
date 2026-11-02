"""Summarize all native attempts and separate unit fixtures from packet evidence."""
import json
import sqlite3
import statistics
from datetime import UTC, datetime
from pathlib import Path

from explainnet.telemetry_math import receiver_records
from explainnet.workflow_spec import WORKFLOW_HASH, WORKFLOW_POLICY

ROOT = Path(__file__).resolve().parents[1]


def disruption(folder, action, source_run_id):
    if action.get('transient_disruption'):
        return action['transient_disruption']
    # Earlier genuine successes predate explicit root monotonic bounds. Derive
    # them only when surrounding measured paired clocks agree within 250 ms.
    run = folder / 'root_archive/runs' / source_run_id / 'result.json'
    if not run.exists() or not action.get('application'):
        return {'status': 'unavailable', 'metrics': None, 'reason': 'native archive/application timing unavailable'}
    ids = [action['pre_window']['run_id']] + [p['window']['run_id'] for p in action['post_windows']]
    with sqlite3.connect(f'file:{folder / "data/explainnet.sqlite3"}?mode=ro', uri=True) as db:
        points = [json.loads(row[0]) for rid in ids for row in db.execute(
            "SELECT payload_json FROM telemetry_samples WHERE run_id=? AND source='network_agent'", (rid,))]
    offsets = [datetime.fromisoformat(p['at_utc']).timestamp() - p['monotonic_s'] for p in points]
    applied = action['application']
    begin, end = applied.get('application_started_monotonic_s'), applied.get('application_ended_monotonic_s')
    method = 'explicit root monotonic application bounds; native launch anchor for receiver intervals'
    if begin is None and (not offsets or max(offsets) - min(offsets) > .25):
        return {'status': 'unavailable', 'metrics': None, 'reason': 'surrounding clock pairs missing/discontinuous'}
    if begin is None:
        begin = datetime.fromisoformat(applied['applying_utc']).timestamp() - statistics.median(offsets)
        end = begin + applied['application_elapsed_ms'] / 1000
        method = 'UTC application receipt mapped through surrounding measured paired clocks; native launch anchor for receiver intervals'
    native = json.loads(run.read_text())
    native['state'] = 'running'  # It was verified running at the historical action.
    terminal_errors = {}
    for profile in native['profiles']:
        profile['receiver_clock_anchor'] = profile['client_launch_clock']
        if profile.get('server_json', {}).get('error'):
            terminal_errors[profile['parameters']['profile_id']] = profile['server_json'].pop('error')
    point = points[-1] | {'at_utc': native['ended_utc'], 'completed_runs': [], 'active_receiver_runs': [native]}
    rows = [x for x in receiver_records(point, 'audit' + action['action_id']) if x['valid']
        and x['start_monotonic_s'] < end and x['end_monotonic_s'] > begin]
    metrics = {}
    for row in rows:
        value = metrics.setdefault(row['source_host'] + '->' + row['target_host'],
            {'bytes': 0, 'duration_s': 0, 'packets': 0, 'lost_packets': 0})
        for key in value:
            value[key] += row[key]
    for value in metrics.values():
        value['goodput_bps'] = 8 * value['bytes'] / value['duration_s']
        value['loss_fraction'] = value['lost_packets'] / value['packets'] if value['packets'] else None
    return {'status': 'measured' if rows else 'unavailable', 'metrics': metrics or None, 'native_intervals': rows,
        'application_started_monotonic_s': begin, 'application_ended_monotonic_s': end,
        'clock_pair_spread_s': max(offsets) - min(offsets),
        'later_native_termination_errors': terminal_errors,
        'method': method,
        'resolution': 'whole native intervals overlapping application, no sub-interval or zero-disruption claim'}


def main():
    folders = sorted((ROOT / 'artifacts/stage11').iterdir(), key=lambda p: p.stat().st_mtime)
    attempts = [{'directory': str(p), 'report': json.loads((p / 'report.json').read_text())}
        for p in folders if p.is_dir() and (p / 'report.json').exists()]
    report = {'stage': 11, 'implementation': {'version': '0.11.0', 'workflow_policy': WORKFLOW_POLICY,
        'workflow_policy_hash': WORKFLOW_HASH, 'original_execution': 'verified owned laboratory reroutes only',
        'production_model_available': False, 'auto_default_disabled': True, 'observed_only_exception_explicit': True},
        'attempts': attempts, 'summary': {}, 'actions': [], 'cleanup': {}, 'storage': {}, 'refusals': [],
        'sealed_test_measurements_read': False, 'models_retrained': False, 'dashboard_implemented': False}
    for item in attempts:
        p = Path(item['directory'])
        r = item['report']
        for name, w in r.get('cases', {}).items():
            if w.get('state') == 'refused':
                report['refusals'].append({'case': name, 'workflow_id': w['workflow_id'], 'reasons': w.get('reasons'), 'directory': str(p)})
            if name in {'assisted', 'auto'} and w.get('state') == 'succeeded':
                a = w['action_result']
                assert len(a['post_windows']) >= 2 and all(x['evaluation']['eligible'] for x in a['post_windows'])
                assert a['application']['fault_preserved'] and a['application']['workload_preserved']
                report['summary'][name] = {'state': 'succeeded', 'directory': str(p), 'workflow_id': w['workflow_id'],
                    'action_id': a['action_id'], 'pre_rtt_mean_ms': a['pre_window']['features']['rtt_mean_ms'],
                    'post_rtt_mean_ms': [x['observed_rtt_mean_ms'] for x in a['post_windows']],
                    'twin_predicted_rtt_ms': a['post_windows'][0]['predicted_rtt_mean_ms'],
                    'delivered_bps': [x['window']['features']['critical_goodput_bps'] for x in a['post_windows']],
                    'application_elapsed_ms': a['application']['application_elapsed_ms'],
                    'elapsed_ms': a['elapsed_ms'], 'workflow_elapsed_ms': w.get('elapsed_ms'),
                    'transient_disruption': disruption(p, a, r['checks']['source_run_id']),
                    'fault_preserved': True, 'workload_preserved': True}
            if name in {'verification_rollback', 'partial_rollback', 'restart_reconciled'} and w.get('state') == 'rolled_back':
                report['summary'][name] = {'state': 'rolled_back', 'directory': str(p), 'workflow_id': w['workflow_id'],
                    'reasons': w.get('reasons', []), 'interrupted': w.get('interrupted', False),
                    'restored_rtt_mean_ms': r.get('checks', {}).get('restart_restoration_window' if name == 'restart_reconciled'
                        else name + '_window', {}).get('features', {}).get('rtt_mean_ms')}
        if (p / 'cleanup.json').exists():
            cleanup = json.loads((p / 'cleanup.json').read_text())
            assert cleanup['owned_bridges_removed'] and cleanup['preexisting_bridges_preserved']
            report['cleanup'][p.name] = cleanup
        db_path = p / 'data/explainnet.sqlite3'
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
            report['storage'][p.name] = {'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
                'action_states': dict(db.execute('SELECT state,count(*) FROM lab_action_state GROUP BY state')),
                'workflow_states': dict(db.execute('SELECT state,count(*) FROM recovery_workflows GROUP BY state'))}
            source_journal = p / 'root_archive' / ('instance_original_' + p.name + '.json')
            if source_journal.exists():
                report['storage'][p.name]['source_lab_final_state'] = json.loads(source_journal.read_text())['state']
            assert report['storage'][p.name]['integrity_check'] == 'ok'
            actions = [json.loads(x[0]) for x in db.execute('SELECT payload_json FROM lab_action_state')]
            for a in actions:
                a['evidence_directory'] = str(p)
                a['derived_disruption_audit'] = disruption(p, a, r['checks']['source_run_id'])
                for name in ('verification_rollback', 'partial_rollback', 'restart_reconciled'):
                    item = report['summary'].get(name)
                    if item and item['workflow_id'] == a['workflow_id']:
                        restored = a.get('rollback', {})
                        item.update(action_id=a['action_id'], switch_acknowledgements=len(restored.get('steps', [])),
                            restored_connectivity=restored.get('restoration_probe', {}).get('passed'),
                            impairment_digest_preserved=bool(restored.get('before', {}).get('impairment_digest')) and restored.get('restoration', {}).get('impairment_digest') == restored['before']['impairment_digest'],
                            transient_disruption=a['derived_disruption_audit'])
                report['actions'].append(a)
            control = db.execute('SELECT payload_json FROM recovery_control').fetchone()
            assert not control or not json.loads(control[0])['auto_enabled']
    report['migration'] = json.loads((ROOT / 'artifacts/stage11/storage_migration.json').read_text())
    report['software_verification'] = json.loads((ROOT / 'artifacts/stage11/software_checks.json').read_text())
    prior = json.loads((ROOT / 'artifacts/candidate_validation_report.json').read_text())
    report['per_fault'] = {'latency': {'coverage': report['summary'], 'condition': 'permitted 8 Mbps critical / 5 Mbps bulk UDP train latency configuration'},
        **{name: {'status': 'unsupported_for_original_repair', 'reason': prior['summary'][name]['historical_state'],
            'prior_packet_evidence': 'artifacts/candidate_validation_report.json', 'original_repair_attempted': False}
            for name in ('saturation', 'loss', 'qos')}}
    required = {'assisted', 'auto', 'verification_rollback', 'partial_rollback', 'restart_reconciled'}
    report['status'] = 'implemented_with_limited_actual_coverage' if required <= report['summary'].keys() else 'implemented_with_incomplete_actual_verification'
    report['limitations'] = ['Production dataset/model/SHAP gates remain incomplete; observed-only laboratory opt-in was explicit.',
        'Original measured success is limited to the permitted latency UDP condition; saturation/loss/QoS and tested TCP latency remain unqualified.',
        'Forwarding uses per-switch bundles and can disrupt packets; native overlap intervals do not resolve sub-interval loss.',
        'Earlier driver failures retain their failed/interrupted records. Their source labs were destroyed by the test owner; cleanup is not reported as rollback.',
        'SQLite I/O failure on DrvFS and premature restart polling were measured, fixed, and retained as failed attempts.']
    report['stage12_eligibility'] = {'interface_implementation_may_begin': True, 'production_pipeline_ready': False,
        'must_display': ['missing production model/SHAP', 'conditional latency-only original coverage',
            'observed-only exception and explicit mode', 'stale/refused/rollback/degraded status'],
        'historical_actions_not_permission_for_new_actuation': True}
    report['commands'] = ['sudo env PYTHONPATH=src python3 scripts/check_recovery_stage11.py',
        'sudo env PYTHONPATH=src python3 scripts/check_recovery_stage11.py continuation',
        'sudo env PYTHONPATH=src python3 scripts/check_recovery_stage11.py failures',
        'sudo env PYTHONPATH=src python3 scripts/check_recovery_stage11.py interrupted',
        '.venv/bin/python -m explainnet.cli --config CONFIG lab-mode MODE.json',
        '.venv/bin/python -m explainnet.cli --config CONFIG lab-apply APPLY.json',
        '.venv/bin/python -m explainnet.cli --config CONFIG lab-stop',
        '.venv/bin/python -m explainnet.cli --config CONFIG lab-undo UNDO.json']
    report['finalized_utc'] = datetime.now(UTC).isoformat()
    (ROOT / 'artifacts/recovery_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'cases': {k: v['state'] for k, v in report['summary'].items()},
        'cleanup_runs': len(report['cleanup'])}))


if __name__ == '__main__':
    main()
