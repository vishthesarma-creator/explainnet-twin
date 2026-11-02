"""Separate evaluation of already-saved predictions; never an inference input."""
import hashlib
import json
from pathlib import Path


def evaluate_saved_predictions(store, prediction_path):
    data = Path(prediction_path).read_bytes()
    predictions = json.loads(data)
    outcomes = []
    # Experimental truth is read only here, after the caller atomically saves all
    # predictions. No score/parameters are changed by this evaluation.
    with store.connection() as db:
        for prediction in predictions['cases']:
            membership = db.execute('SELECT partition FROM dataset_members WHERE window_id=?', (prediction['window_id'],)).fetchone()
            if not membership or membership[0] == 'test':
                raise ValueError('evaluation requires eligible train/validation predictions; test remains sealed')
            window = json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (prediction['window_id'],)).fetchone()[0])
            truths = []
            for run_id in window.get('context', {}).get('traffic_run_ids', []):
                row = db.execute('SELECT payload_json FROM ground_truth WHERE run_id=?', (run_id,)).fetchone()
                if row:
                    truth = json.loads(row[0])
                    truths.append({'fault_label': truth['fault_label'], 'intended_location': truth.get('intended_location'),
                        'affected_directions': truth.get('affected_directions', [])})
            labels = sorted({t['fault_label'] for t in truths})
            expected = sorted({t['intended_location'] for t in truths if t['intended_location']})
            candidates = prediction['localization']['candidate_set']
            status = prediction['localization']['status']
            outcomes.append({'window_id': prediction['window_id'], 'partition': membership[0], 'truth_classes': labels,
                'intended_locations': expected, 'saved_candidate_set': candidates, 'prediction_status': status,
                'outcome': 'truth_unavailable' if not truths else 'healthy_no_fault_location' if not expected
                    else 'ambiguous_contains_truth' if status == 'ambiguous' and set(expected) & set(candidates)
                    else 'ambiguous_misses_truth' if status == 'ambiguous'
                    else 'ranked_matches_intended' if set(expected) & set(candidates) else 'ranked_incorrect',
                'limitation': 'Intended injector location is an experimental reference, not proof of a physical cause'})
    return {'prediction_file_sha256': hashlib.sha256(data).hexdigest(), 'cases': outcomes,
        'evaluation_order': 'predictions atomically persisted before separate ground-truth lookup',
        'test_partition': 'sealed; excluded', 'localization_probability': None}
