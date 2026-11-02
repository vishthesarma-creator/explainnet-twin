#!/usr/bin/env python3
"""Summarize saved real evidence and preserve the existing DB during migration."""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from explainnet.config import load_settings
from explainnet.storage import Store
from explainnet.twin_spec import validate_snapshot

ROOT = Path(__file__).resolve().parents[1]


def database_state(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        tables = ['runs', 'ground_truth', 'jobs', 'telemetry_samples', 'telemetry_windows', 'dataset_members',
            'dataset_batches', 'model_bundles', 'explanations', 'incidents', 'snapshots']
        return {'schema_version': db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],
            'counts': {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables},
            'members_digest': hashlib.sha256(json.dumps(db.execute('SELECT window_id,partition,window_hash FROM dataset_members ORDER BY window_id').fetchall()).encode()).hexdigest(),
            'dataset_states': db.execute('SELECT batch_id,state FROM dataset_batches ORDER BY batch_id').fetchall(),
            'partitions': dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition'))}


def main():
    path = ROOT / 'artifacts/twin_validation_report.json'
    report = json.loads(path.read_text())
    assert report['status'] == 'packet_batch_finished'
    canonical = load_settings(ROOT / 'artifacts/stage6/runtime/config.json').database_path
    before = database_state(canonical)
    Store(canonical).initialize()
    after = database_state(canonical)
    preserved = all(before[k] == after[k] for k in ('counts', 'members_digest', 'dataset_states', 'partitions'))
    assert preserved
    report['storage_migration'] = {'path': str(canonical), 'before': before, 'after': after,
        'prior_records_preserved': preserved, 'sealed_test_measurements_read': False}
    cleanup = {}
    for directory in sorted((ROOT / 'artifacts/stage9').iterdir()):
        file = directory / 'cleanup.json'
        if file.exists():
            cleanup[directory.name] = json.loads(file.read_text())
    report['cleanup_verification'] = cleanup
    assert all(v['owned_bridges_removed'] and v['preexisting_bridges_preserved'] for v in cleanup.values())
    stage9_data = Path(json.loads(Path(report['config_file']).read_text())['data_dir']) / 'explainnet.sqlite3'
    with sqlite3.connect(f'file:{stage9_data}?mode=ro', uri=True) as db:
        snapshots = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM twin_snapshots')]
        for snapshot in snapshots:
            validate_snapshot(snapshot)
        report['persisted_evidence'] = {'database': str(stage9_data), 'snapshot_hashes_verified': len(snapshots),
            'trial_states': dict(db.execute('SELECT state,count(*) FROM twin_trials GROUP BY state')),
            'raw_sources': dict(db.execute('SELECT source,count(*) FROM telemetry_samples GROUP BY source')),
            'job_states': dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state')),
            'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0]}
    report['implementation'] = {'package_version': '0.9.0', 'real_network_engine_reused': True,
        'operator_snapshot_allowlist': True, 'typed_agent_jobs_api_cli_storage': True,
        'bounded_sequential_hypotheses': True, 'metrics_adjusted': False, 'capacity_fitted': False,
        'repairs_executed': False, 'production_model_available': False}
    report['summary'] = {name: {'status': case['state'],
        'trial_statuses': [t['state'] for t in case.get('trials', [])],
        'error': case.get('error')} for name, case in report['cases'].items()}
    report['stage10_eligibility'] = {'scope': 'limited isolated twin experimentation with new current snapshots',
        'eligible_conditions': ['measured healthy workload', 'measured added latency hypotheses'],
        'ineligible_conditions': ['saturation', 'loss', 'tested QoS fault', 'missing evidence', 'expiry', 'drift', 'host contamination'],
        'full_production_pipeline_ready': False,
        'reasons': ['Stage 6 main collection incomplete; production Stage 7 model and measured Stage 8 SHAP absent',
            'Fidelity has failed or insufficient classes; passing results are workload/hypothesis specific']}
    elapsed, resources = [], []
    for case in report['cases'].values():
        trials = case.get('trials', []) + ([case['baseline_trial']] if 'baseline_trial' in case else [])
        trials += case.get('bounded_calibration', {}).get('trials', [])
        for trial in trials:
            if 'elapsed_ms' in trial:
                elapsed.append(trial['elapsed_ms'])
            for side in ('original', 'twin'):
                if side in trial:
                    resources.append({k: trial[side]['features'][k] for k in ('cpu_busy_fraction', 'memory_used_fraction')})
    report['overhead'] = {'matched_capture_elapsed_ms': elapsed,
        'job_submission_ms': report['checks']['job_submission_ms'], 'vm_resource_observations': resources,
        'maximum_live_twins': 1, 'measurement_duration_s': 15,
        'publication_optimization': 'Index wholly contained current-window receiver intervals; retain full native stream in raw frames',
        'outer_windows_host_resources_measured': False}
    report['status'] = 'implemented_with_limited_fidelity'
    report['finalized_utc'] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'migration_preserved': preserved,
        'snapshot_hashes_verified': len(snapshots), 'summary': report['summary']}))


if __name__ == '__main__':
    main()
