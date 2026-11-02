"""Read-only measured localization/reporting; SHAP only with an existing usable bundle.

No training or network calls. Test inputs are never selected. A running collection
is left on its loaded schema; migration is refused while that batch owns the lab.
"""
import argparse
import json
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

from explainnet.config import load_network, load_settings
from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.diagnosis_service import DiagnosisService
from explainnet.explanation_service import ExplanationService
from explainnet.link_localization import localize, observed_samples
from explainnet.localization_evaluation import evaluate_saved_predictions
from explainnet.storage import Store, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--model-id')
    parser.add_argument('--output', type=Path, default=Path('artifacts/explanation_validation_report.json'))
    args = parser.parse_args()
    settings = load_settings(args.config)
    store = Store(settings.database_path)
    definition = load_network(settings.topology_file) if settings.topology_file else None
    with store.connection() as db:
        batches = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM dataset_batches ORDER BY rowid DESC')]
        batch = next((b for b in batches if b.get('schedule', {}).get('purpose') == 'main'), batches[0] if batches else None)
        models = db.execute('SELECT model_id FROM model_bundles ORDER BY created_utc DESC').fetchall()
        counts = {r[0]: r[1] for r in db.execute('SELECT partition,COUNT(*) FROM dataset_members WHERE batch_id=? GROUP BY partition', (batch['batch_id'] if batch else '',))}
        migration = db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        # Fixed selection: earliest accepted ready window per eligible episode,
        # without looking at labels, scenario recipes or hidden locations.
        rows = db.execute("SELECT w.payload_json FROM dataset_members m JOIN telemetry_windows w USING(window_id) "
            "WHERE m.partition IN ('train','validation') AND w.inference_ready=1 AND "
            "NOT EXISTS(SELECT 1 FROM dataset_members m2 JOIN telemetry_windows w2 USING(window_id) "
            "WHERE m2.episode_id=m.episode_id AND w2.end_monotonic_s<w.end_monotonic_s) ORDER BY m.episode_id").fetchall()
    measured_cases = []
    for row in rows:
        window = json.loads(row[0])
        samples = observed_samples(store, window)
        start = time.perf_counter()
        result = localize(window, definition, samples)
        measured_cases.append({'window_id': window['window_id'], 'window_hash': digest(window),
            'localization': result, 'runtime_ms': (time.perf_counter() - start) * 1000,
            'source': 'actual accepted measured telemetry; no model/SHAP used'})
    prediction_path = args.output.parent / 'stage8' / 'localization_predictions.json'
    atomic_json(prediction_path, {'created_utc': utc_now(), 'selection': 'earliest accepted window per eligible episode; no labels used', 'cases': measured_cases})
    evaluation = evaluate_saved_predictions(store, prediction_path)
    atomic_json(prediction_path.with_name('localization_evaluation.json'), evaluation)
    report = {'schema_version': 1, 'at_utc': utc_now(), 'stage': 8, 'status': 'interfaces_implemented_measured_shap_blocked',
        'model_id': None, 'usable_model_exists': bool(models), 'dataset_state': batch.get('state') if batch else None,
        'batch_id': batch.get('batch_id') if batch else None, 'accepted_windows_by_partition': counts,
        'source_database_migration': migration, 'source_database_migrated': False,
        'blockers': ['Measured collection/training incomplete; no usable production model bundle'],
        'actual_measured_shap_cases': [], 'additivity_checks': None, 'shap_runtime_ms': None,
        'neighboring_explanation_stability': None, 'uncertain_or_insufficient_measured_shap_case': None,
        'localization': {'cases': len(measured_cases), 'predictions': str(prediction_path),
            'evaluation_path': str(prediction_path.with_name('localization_evaluation.json')),
            'outcome_counts': dict(Counter(c['outcome'] for c in evaluation['cases'])),
            'truth_classes_available': sorted({label for c in evaluation['cases'] for label in c['truth_classes']}),
            'measured_runtime_ms': {'max': max((c['runtime_ms'] for c in measured_cases), default=None)},
            'parameters_tuned': False, 'evaluation': evaluation},
        'test_partition': 'sealed; no test windows explained, localized or evaluated', 'stage9_ready': False,
        'limitations': ['Unit SHAP checks are software evidence, not measured model validation',
            'Train localization cases are descriptive checks, not independent generalization evidence',
            'Scores are heuristic suspects; end-to-end delay/loss can leave multiple candidates'],
        'software_verification': None}
    model_id = args.model_id or (models[0]['model_id'] if models else None)
    software = args.output.parent / 'stage8' / 'software_verification.json'
    if software.exists():
        report['software_verification'] = json.loads(software.read_text())
    applied = args.output.parent / 'stage8' / 'applied_migration.json'
    if applied.exists():
        applied_report = json.loads(applied.read_text())
        report['source_database_migrated'] = applied_report['after_version'] > applied_report['before_version']
        report['migration_verification'] = {k: v for k, v in applied_report.items() if k != 'tables'}
    supervisor_path = args.config.parent / 'supervisor.json'
    if supervisor_path.exists():
        supervisor = json.loads(supervisor_path.read_text())
        report['collection_supervisor'] = {k: supervisor.get(k) for k in ('state', 'error', 'completed_episodes', 'accepted_windows', 'cleanup_preserved_bridges', 'agent_socket_present')}
    if models and model_id:
        if batch and batch['state'] == 'running':
            raise ValueError('stop/completed supervisor required before schema migration or measured SHAP validation')
        store.initialize()
        telemetry = SimpleNamespace(settings=settings.telemetry, objective=settings.objective, status=lambda _: {'live': False})
        diagnosis = DiagnosisService(store, telemetry)
        service = ExplanationService(store, diagnosis, definition)
        from explainnet.model_dataset import load_measured_dataset
        _, validation, _ = load_measured_dataset(store.path.parent / 'datasets' / batch['batch_id'])
        cases = []
        for stub in validation.windows:
            wid = stub['window_id']
            diagnosis.diagnose(model_id, wid, 'recorded')
            request = service.request(model_id, wid)
            explanation = service.process(request) if request['status'] == 'pending' else request
            cases.append(explanation)
        # Retrieve an actually insufficient measured window from a validation
        # collector if present. No measurements or feature values are changed.
        with store.connection() as db:
            incomplete = db.execute("SELECT w.window_id FROM telemetry_windows w JOIN dataset_attempts a ON "
                "json_extract(a.payload_json,'$.collector_run_id')=w.run_id "
                "WHERE json_extract(a.payload_json,'$.partition')='validation' AND w.inference_ready=0 ORDER BY w.end_monotonic_s LIMIT 1").fetchone()
        if incomplete:
            extra = diagnosis.diagnose(model_id, incomplete[0], 'recorded')
            report['uncertain_or_insufficient_measured_shap_case'] = {'diagnosis': extra,
                'explanation': service.request(model_id, incomplete[0])}
        report.update(model_id=model_id, actual_measured_shap_cases=cases, source_database_migrated=report['source_database_migrated'] or migration < 7,
            blockers=[], status='measured_shap_checked', additivity_checks=[{'window_id': c['window_id'],
                'error': c.get('additivity_absolute_error'), 'status': c['status']} for c in cases])
        report['neighboring_explanation_stability'] = neighboring_stability(store, cases)
        report['shap_runtime_ms'] = [c['runtime_ms'] for c in cases]
        report['validation_cases_by_reference_class'] = dict(Counter(validation.y.tolist()))
        report['stage9_ready'] = (bool(cases) and all(c['status'] == 'ready' for c in cases)
            and bool(report['neighboring_explanation_stability']['comparisons'])
            and bool(report['uncertain_or_insufficient_measured_shap_case'] or any(c.get('diagnosis_status') == 'uncertain' for c in cases)))
        if not report['stage9_ready']:
            report['blockers'] = ['Measured explanation validation incomplete: inspect case statuses, neighboring stability and uncertainty coverage']
            report['status'] = 'measured_shap_partially_checked'
    atomic_json(args.output, report)
    print(json.dumps({'report': str(args.output), 'status': report['status'], 'model_id': report['model_id'], 'localization_outcomes': report['localization']['outcome_counts'], 'stage9_ready': report['stage9_ready']}))


def neighboring_stability(store, cases):
    """Descriptive changes, with comparable path/class and adjacent observed windows."""
    grouped = {}
    for case in cases:
        if case['status'] != 'ready':
            continue
        with store.connection() as db:
            w = json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (case['window_id'],)).fetchone()[0])
        grouped.setdefault(w['run_id'], []).append((w, case))
    comparisons = []
    for series in grouped.values():
        series.sort(key=lambda item: item[0]['end_monotonic_s'])
        for (a, x), (b, y) in pairwise(series):
            same = x['explained_class'] == y['explained_class'] and a.get('context', {}).get('selected_paths') == b.get('context', {}).get('selected_paths')
            if abs(b['start_monotonic_s'] - a['end_monotonic_s']) >= .001 or not same:
                continue
            left, right = {c['transformed_feature'] for c in x['top_features']}, {c['transformed_feature'] for c in y['top_features']}
            comparisons.append({'windows': [a['window_id'], b['window_id']], 'explained_class': x['explained_class'],
                'top_feature_jaccard': len(left & right) / len(left | right) if left | right else 1,
                'contribution_l1_change': sum(abs(p['contribution'] - q['contribution']) for p, q in zip(x['contributions'], y['contributions'], strict=True)),
                'raw_output_change': y['underlying_model_output'] - x['underlying_model_output'],
                'changed_observations': {n: [a['features'][n], b['features'][n]] for n in a['features'] if a['features'][n] != b['features'][n]}})
    return {'comparisons': comparisons, 'interpretation': 'Descriptive changes; no stability target or tuning. Shared missingness and measurement changes can alter attribution.'}


if __name__ == '__main__':
    main()
