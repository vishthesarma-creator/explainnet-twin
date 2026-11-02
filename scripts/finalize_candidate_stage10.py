"""Verify and summarize preserved native evidence; never read sealed measurements."""
import json
import sqlite3
import statistics
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from explainnet.recovery_spec import POLICY, POLICY_HASH
from explainnet.twin_spec import validate_snapshot

ROOT = Path(__file__).resolve().parents[1]


def spread(values):
    return {'count': len(values), 'min': min(values) if values else None,
        'mean': statistics.mean(values) if values else None, 'max': max(values) if values else None,
        'range': max(values) - min(values) if values else None}


def main():
    directories = sorted((ROOT / 'artifacts/stage10').iterdir(), key=lambda p: p.stat().st_mtime)
    runs = [(p, json.loads((p / 'report.json').read_text())) for p in directories if (p / 'report.json').exists()]
    main_dir, report = next((p, r) for p, r in reversed(runs) if 'latency_udp' in r.get('cases', {}))
    controls = [(p, json.loads((p / 'controls_report.json').read_text())) for p in directories if (p / 'controls_report.json').exists()]
    assert controls and controls[-1][1]['status'] == 'passed'
    report['native_controls'] = controls[-1][1]
    report['earlier_attempts'] = [{'evidence_directory': str(p), 'report': r} for p, r in runs if p != main_dir]
    report['implementation'] = {'package_version': version('explainnet-twin'), 'policy_version': POLICY['version'],
        'policy_hash': POLICY_HASH, 'typed_logical_action_families': POLICY['families'],
        'root_execution_scope': 'verified twin only', 'original_actions_available': False,
        'repetitions': 2, 'maximum_hypotheses': 2, 'freshness_disabled': False,
        'snapshot_expiry_extended_during_job': False, 'model_retrained': False}
    report['native_preservation_evidence_units'] = {'tc_netem_delay_options': 'seconds',
        'tc_class_rate_and_ceil': 'bytes/second', 'normalized_objective': 'milliseconds, bits/second, loss fractions'}
    report['storage_migration'] = json.loads((ROOT / 'artifacts/stage10/storage_migration.json').read_text())
    report['software_verification'] = json.loads((ROOT / 'artifacts/stage10/software_checks.json').read_text())
    summary, resources = {}, []
    for name, case in report['cases'].items():
        snapshot = validate_snapshot(case['snapshot'])
        experiment = case['experiment']
        assert experiment['snapshot_hash'] == snapshot['snapshot_hash']
        measured = [t for t in experiment['trials'] if t.get('capture_id')]
        assert all(t['original_unchanged'] for t in measured)
        assert all(t['application']['fault_preserved'] and t['application']['workload_preserved'] for t in measured)
        tokens = [t['reset']['runtime_token'] for t in experiment['trials'] if t.get('reset')]
        assert len(tokens) == len(set(tokens)), 'trial runtime was not freshly reset'
        preserved = case['original_preservation']
        assert all(preserved[k] for k in ('same_fingerprint', 'same_runtime_token', 'same_workload',
            'all_trial_configuration_digests_unchanged'))
        assert preserved['run_state_before'] == preserved['run_state_after'] == 'running'
        groups = {}
        for candidate in experiment['candidates']:
            trials = [t for t in measured if t['candidate_id'] == candidate['candidate_id']]
            groups[candidate['candidate_id']] = {'family': candidate['action']['family'], 'logical_diff': candidate['logical_diff'],
                'rtt_mean_ms': spread([t['window']['features']['rtt_mean_ms'] for t in trials
                    if t['window']['features']['rtt_mean_ms'] is not None]),
                'critical_goodput_bps': spread([t['window']['features']['critical_goodput_bps'] for t in trials
                    if t['window']['features']['critical_goodput_bps'] is not None])}
        for trial in measured:
            for key in ('original_window', 'window'):
                resources.append({k: trial[key]['features'][k] for k in ('cpu_busy_fraction', 'memory_used_fraction')})
        summary[name] = {'historical_state': case['state'], 'trial_count': len(experiment['trials']),
            'control_states': [t.get('fidelity', {}).get('status') for t in experiment['trials'] if t['family'] == 'no_change'],
            'outcome_spreads': groups, 'ranking': experiment.get('recommendation'),
            'elapsed_ms': experiment.get('elapsed_ms'), 'original_unchanged_while_running': True,
            'current_validity': 'historical only; verification source cleaned up; new current snapshot required'}
    report['summary'] = summary
    cleanup = {p.name: json.loads((p / 'cleanup.json').read_text()) for p in directories if (p / 'cleanup.json').exists()}
    assert all(c['preexisting_bridges_preserved'] and c['owned_bridges_removed'] for c in cleanup.values())
    report['cleanup_verification'] = cleanup
    databases = {}
    for p in directories:
        config = p / 'config.json'
        if not config.exists():
            continue
        path = Path(json.loads(config.read_text())['data_dir']) / 'explainnet.sqlite3'
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            for row in db.execute('SELECT payload_json FROM twin_snapshots'):
                validate_snapshot(json.loads(row[0]))
            databases[p.name] = {'database': str(path), 'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
                'recovery_states': dict(db.execute('SELECT state,count(*) FROM recovery_experiments GROUP BY state')),
                'snapshot_count': db.execute('SELECT count(*) FROM twin_snapshots').fetchone()[0],
                'native_raw_sample_count': db.execute('SELECT count(*) FROM telemetry_samples').fetchone()[0]}
            assert databases[p.name]['integrity_check'] == 'ok'
    report['persisted_evidence'] = databases
    report['resource_observations'] = {'max_mean_vm_cpu_busy_fraction': max(r['cpu_busy_fraction'] for r in resources),
        'max_mean_vm_memory_used_fraction': max(r['memory_used_fraction'] for r in resources),
        'outer_windows_pressure_measured': False}
    report['verification_commands'] = [
        'sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py latency',
        'sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py latency_udp healthy saturation loss qos',
        'sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py controls',
        '.venv/bin/python -m pytest -q', '.venv/bin/python -m explainnet.cli --config CONFIG recovery-get OPERATION_ID']
    report['stage11_eligibility'] = {'scope': 'limited assisted original-network verification implementation for fresh validated latency conditions',
        'currently_executable_recommendations': False, 'full_production_pipeline_ready': False,
        'requires': ['new current snapshot and repeated eligible twin comparison', 'Stage 11 original verification and rollback',
            'completion of Stage 6 collection and measured Stage 7/8 model/SHAP gates for production'],
        'ineligible_conditions': ['tested saturation', 'tested loss', 'tested QoS', 'tested TCP latency workload',
            'missing evidence', 'unresolved hypotheses', 'expiry', 'drift', 'host contamination']}
    report.update(status='implemented_with_limited_validation', finalized_utc=datetime.now(UTC).isoformat())
    (ROOT / 'artifacts/candidate_validation_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'summary': {k: v['historical_state'] for k, v in summary.items()},
        'cleanup_runs': len(cleanup), 'databases': len(databases), 'package_version': report['implementation']['package_version']}))


if __name__ == '__main__':
    main()
