"""Read-only nested rejection projections; no gate decisions live here."""


def experiment_rejections(experiment):
    details = []
    for trial in experiment.get('trials', []):
        fidelity = trial.get('fidelity') or {}
        for metric in fidelity.get('metrics', []):
            if metric['status'] != 'pass':
                details.append({'stage': 'fidelity', 'trial_id': trial['trial_id'], **metric,
                    'requirement': 'absolute_error <= tolerance; missing is not zero'})
        for group in ('missing_required_metrics', 'contamination', 'stale_reasons'):
            details.extend({'stage': 'fidelity', 'trial_id': trial['trial_id'], 'constraint': group, 'reason': r}
                for r in fidelity.get(group, []))
        if trial.get('error'):
            details.append({'stage': 'trial', 'trial_id': trial['trial_id'], 'reason': trial['error']})
    for row in (experiment.get('recommendation') or {}).get('rows', []):
        for evaluation in row.get('evaluations', []):
            details.extend({'stage': 'candidate', 'candidate_id': row['candidate_id'], 'reason': r}
                for r in evaluation.get('reasons', []))
    details.extend({'stage': 'experiment', 'reason': r} for r in experiment.get('reasons', []))
    return details
