"""Persistent observed incidents with append-only evidence and fresh recovery gates."""
import json
from datetime import UTC, datetime
from uuid import uuid4

from explainnet.dataset_contracts import digest
from explainnet.link_localization import affected_path
from explainnet.storage import utc_now
from explainnet.telemetry_storage import reject_ground_truth


class IncidentService:
    def __init__(self, store, definition=None, recovery_windows=2, stale_after_s=30):
        self.store, self.definition = store, definition
        self.recovery_windows, self.stale_after_s = recovery_windows, stale_after_s

    def observe(self, window, result, source_id, diagnosis_id=None, now=None, context_token=None):
        reject_ground_truth(window)
        path = affected_path(window, self.definition)
        mode = result.get('mode', 'live')
        context = window.get('context', {})
        identity = (context.get('traffic_run_ids') or context_token or window['run_id']) if mode == 'live' else window['run_id']
        key = digest({'instance': window['instance_id'], 'collector': identity,
            'agent_epoch': context.get('agent_epoch'),
            'flow': path['flow'], 'path': path['path_name'],
            'forwarding_version': window.get('context', {}).get('forwarding_version'), 'mode': mode})
        when = datetime.fromisoformat(window['at_utc'])
        now = now or datetime.now(UTC)
        fresh = (mode == 'live' and 0 <= (now - when).total_seconds() <= self.stale_after_s
            and result.get('freshness', 'fresh') == 'fresh' and result['status'] not in {'stale', 'insufficient-data'}
            and window['complete'] and window['inference_ready'])
        bad = bool(result.get('incident') or result.get('alert_latched'))
        healthy = (fresh and not bad and not result.get('violations') and not result.get('service_violations')
            and result['status'] in {'healthy', 'supported'}
            and result.get('predicted_class', 'healthy') == 'healthy' and not result.get('anomalous', False))
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old_event = db.execute('SELECT incident_id FROM incident_events WHERE event_id=?', (source_id,)).fetchone()
            if old_event:
                return old_event[0]
            row = db.execute("SELECT payload_json FROM incident_state WHERE context_key=? AND state='open' ORDER BY last_observation_utc DESC LIMIT 1", (key,)).fetchone()
            if not row:
                # Late model/cause evidence for an already resolved interval is
                # history of that incident, not a new incident in the past.
                row = db.execute("SELECT payload_json FROM incident_state WHERE context_key=? AND state='resolved' "
                    "AND json_extract(payload_json,'$.observed_start_utc')<=? "
                    "AND json_extract(payload_json,'$.resolved_utc')>=? ORDER BY last_observation_utc DESC LIMIT 1",
                    (key, window['at_utc'], window['at_utc'])).fetchone()
            if not row and (not bad or not fresh and mode != 'recorded'):
                return None
            if row:
                incident = json.loads(row[0])
            else:
                incident = {'schema_version': 1, 'incident_id': 'i' + uuid4().hex, 'context_key': key,
                    'run_id': window['run_id'], 'instance_id': window['instance_id'], 'path': path, 'mode': mode,
                    'state': 'open', 'observed_start_utc': window['at_utc'], 'observed_update_utc': window['at_utc'],
                    'last_window_id': None, 'last_end_monotonic_s': None, 'healthy_streak': 0, 'resolution_evidence': [],
                    'resolved_utc': None, 'probable_cause': None, 'severity': 'unknown', 'service_status': 'unknown'}
                db.execute('INSERT INTO incidents VALUES(?,?,?,?)', (incident['incident_id'], window['run_id'], utc_now(), json.dumps(incident)))
            newer = incident['state'] == 'open' and when >= datetime.fromisoformat(incident['observed_update_utc'])
            new_window = window['window_id'] != incident['last_window_id']
            if newer:
                contiguous = (incident['last_end_monotonic_s'] is not None and
                    abs(window['start_monotonic_s'] - incident['last_end_monotonic_s']) < .001)
                if new_window:
                    if healthy:
                        incident['healthy_streak'] = incident['healthy_streak'] + 1 if contiguous else 1
                        incident['resolution_evidence'] = (incident['resolution_evidence'] if contiguous else []) + [window['window_id']]
                    else:
                        incident['healthy_streak'], incident['resolution_evidence'] = 0, []
                elif not healthy:
                    # A later diagnosis can contradict a same-window baseline recovery.
                    incident['healthy_streak'], incident['resolution_evidence'] = 0, []
                incident.update(observed_update_utc=window['at_utc'], last_window_id=window['window_id'],
                    last_end_monotonic_s=window['end_monotonic_s'])
                if result.get('predicted_class'):
                    incident['probable_cause'] = result['predicted_class']
                violation = bool(result.get('violations') or result.get('service_violations'))
                incident['service_status'] = 'degraded' if fresh and violation else 'healthy' if healthy else 'unknown'
                incident['severity'] = 'service_violation' if violation else 'anomaly' if bad else 'unknown'
                if incident['healthy_streak'] >= self.recovery_windows:
                    incident.update(state='resolved', resolved_utc=window['at_utc'])
            event = {'window_id': window['window_id'], 'diagnosis_id': diagnosis_id, 'source_id': source_id,
                'observation_utc': window['at_utc'], 'fresh': fresh, 'applied_to_lifecycle': newer,
                'result': result, 'state_after_observation': incident['state']}
            db.execute('INSERT INTO incident_events VALUES(?,?,?,?,?,?)',
                (source_id, incident['incident_id'], window['window_id'], diagnosis_id, window['at_utc'], json.dumps(event, allow_nan=False)))
            db.execute('INSERT INTO incident_state VALUES(?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET '
                'state=excluded.state,last_observation_utc=excluded.last_observation_utc,payload_json=excluded.payload_json',
                (incident['incident_id'], key, incident['state'], incident['observed_update_utc'], json.dumps(incident)))
            db.execute('UPDATE incidents SET payload_json=? WHERE id=?', (json.dumps(incident), incident['incident_id']))
            return incident['incident_id']

    def get(self, incident_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM incident_state WHERE incident_id=?', (incident_id,)).fetchone()
            if not row:
                raise ValueError('unknown observed incident')
            result = json.loads(row[0])
            result['history'] = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM incident_events WHERE incident_id=? ORDER BY observation_utc,rowid', (incident_id,))]
            result['explanations'] = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM explanations WHERE incident_id=? ORDER BY created_utc', (incident_id,))]
            return result

    def list(self, instance_id=None):
        with self.store.connection() as db:
            rows = db.execute('SELECT payload_json FROM incident_state ORDER BY last_observation_utc DESC').fetchall()
        return [p for r in rows if (p := json.loads(r[0])) and (instance_id is None or p['instance_id'] == instance_id)]
