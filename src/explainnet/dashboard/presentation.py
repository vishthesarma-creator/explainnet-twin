"""Truthful display transformations; no diagnosis, scoring or repair decisions."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from explainnet.dashboard.client import ApiError


def value(number, unit='', digits=2):
    if number is None:
        return 'Unavailable'
    return f'{number:,.{digits}f} {unit}'.strip()


def readiness(status):
    if not status:
        return [('Backend', 'Unavailable'), ('Dataset', 'Unknown'), ('Trained model', 'Unknown'),
            ('SHAP explanations', 'Unknown'), ('Twin', 'Unknown')]
    return [('Backend', 'Connected'), ('Dataset', 'Ready' if status['dataset']['ready'] else 'Incomplete'),
        ('Trained model', 'Active' if status['models']['active_model_id'] else 'Not activated' if status['models']['registered_count'] else 'Unavailable'),
        ('SHAP explanations', f"{status['explanations']['ready_count']} ready" if status['explanations']['ready_count'] else 'Unavailable'),
        ('Twin', 'Gated per experiment')]


def measurement_window(collector, windows):
    """Prefer the current collection's ended window while its next one accumulates.

    Never skip a completed window because of its quality. Stopped collections
    retain their final partial window and its unavailable measurements.
    """
    if not windows:
        return None
    current = (collector.get('session') or {}).get('run_id')
    if current:
        windows = [w for w in windows if w.get('run_id') == current]
        if not windows:
            return None
    newest = windows[0]
    if collector.get('live'):
        return next((w for w in windows if w.get('run_id') == newest.get('run_id')
            and w.get('complete')), newest)
    return newest


def telemetry_freshness(collector, window, now=None):
    if not window:
        return 'No measurements'
    current = (collector.get('session') or {}).get('run_id')
    if current and current != window.get('run_id'):
        return 'Historical / stale'
    now = now or datetime.now(UTC)
    try:
        age = (now - datetime.fromisoformat(window['at_utc'])).total_seconds()
    except (KeyError, ValueError):
        return 'Timestamp unavailable'
    if not collector.get('live') or not 0 <= age <= 30:
        return 'Historical / stale'
    return 'Fresh' if window.get('complete') and window.get('inference_ready') else 'Incomplete / unsuitable'


def begin_intent(state, slot, path, payload, confirmations):
    """Latch before network I/O; reruns/repeated clicks reuse the same receipt."""
    if not all(confirmations):
        raise ValueError('Complete every required confirmation.')
    fingerprint = hashlib.sha256(json.dumps([path, payload], sort_keys=True).encode()).hexdigest()
    existing = state.get(slot)
    if existing:
        if existing['fingerprint'] != fingerprint:
            raise ValueError('This control already has a request. Review it before preparing another intent.')
        return existing, False
    receipt = {'key': 'ui' + uuid4().hex, 'fingerprint': fingerprint, 'path': path, 'state': 'submitting'}
    receipt['payload'] = payload
    state[slot] = receipt
    return receipt, True


def send_intent(client, state, slot, path, payload, confirmations, direct=False):
    receipt, fresh = begin_intent(state, slot, path, payload, confirmations)
    if not fresh:
        return receipt
    try:
        response = client.request(path, 'POST', payload, receipt['key']) if direct else client.submit(path, payload, receipt['key'])
        receipt.update(state='acknowledged', result=response, job_id=response.get('job_id'))
    except ApiError as exc:
        receipt.update(state='unknown' if exc.kind in {'timeout', 'unavailable', 'invalid_response'} else 'rejected', error=str(exc))
    return receipt


def retry_intent(client, receipt):
    """Explicit user retry only, with the same durable backend idempotency key."""
    if receipt['state'] != 'unknown':
        raise ValueError('Only an unresolved submission can be retried.')
    receipt['state'] = 'submitting'
    try:
        response = client.submit(receipt['path'], receipt['payload'], receipt['key'])
        receipt.update(state='acknowledged', result=response, job_id=response['job_id'])
    except ApiError as exc:
        receipt.update(state='unknown' if exc.kind in {'timeout', 'unavailable', 'invalid_response'} else 'rejected', error=str(exc))
    return receipt


def candidate_rows(experiment):
    ranks = {r['candidate_id']: r for r in experiment.get('recommendation', {}).get('rows', [])}
    rows = []
    for candidate in experiment.get('candidates', []):
        rank = ranks.get(candidate['candidate_id'], {})
        trials = [t for t in experiment.get('trials', []) if t.get('candidate_id') == candidate['candidate_id']]
        measured = [t['window']['features'] for t in trials if t.get('state') == 'measured' and t.get('window')]
        rtts = [m['rtt_mean_ms'] for m in measured if m.get('rtt_mean_ms') is not None]
        rates = [m['critical_goodput_bps'] for m in measured if m.get('critical_goodput_bps') is not None]
        rows.append({'Candidate': candidate['candidate_id'], 'Treatment': candidate['action']['family'],
            'Twin RTT mean (ms)': sum(rtts) / len(rtts) if rtts else None,
            'Twin delivered (bps)': sum(rates) / len(rates) if rates else None,
            'Measured trials': len(measured), 'Action cost': candidate.get('expected_disruption'),
            'Feasible': bool(candidate.get('feasibility')) if candidate.get('feasibility') is not None else None,
            'Qualifies': rank.get('qualifies'), 'Conservative score': rank.get('conservative_score'),
            'Reasons': '; '.join(candidate.get('reasons', []) + [reason for e in rank.get('evaluations', []) for reason in e.get('reasons', [])])})
    for rejected in experiment.get('rejected', []):
        rows.append({'Candidate': 'Not admitted', 'Treatment': rejected['action']['family'], 'Feasible': False,
            'Reasons': rejected.get('reason', 'Rejected by backend')})
    return rows
