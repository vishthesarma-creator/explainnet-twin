"""Manual teacher-demo stages in the existing qualified store; never auto-cleans.

Only `fault` injects. Only the dashboard applies a repair. `cleanup` is explicit.
No classifier is disabled and no eligibility, freshness or fidelity gate changes.
"""
import argparse
import json
import os
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.app_launcher import owned
from explainnet.config import load_network, load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import Store
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'artifacts/stage14/rehearsals/bb745a91/config.json'
LATEST = ROOT / 'artifacts/teacher_demo/interactive/session.json'
TERMINAL = {'recommended', 'succeeded', 'refused', 'failed', 'rolled_back', 'interrupted'}


def teardown_allowed(control, actions):
    if control.get('degraded') or control.get('cleanup_pending_workflow_ids'):
        raise ValueError('Coordinator reconciliation/owned twin cleanup required before teardown.')
    if control.get('active_workflow_id') or control.get('monitor_active') or control.get('unsettled_action_ids'):
        raise ValueError('A workflow/monitor is active; cancel it and wait for verification/rollback first.')
    if any(a.get('state') in {'succeeded', 'applying', 'verifying', 'rolling_back', 'interrupted'}
            or a.get('degraded') for a in actions):
        raise ValueError('Inspect the action and use Undo Last Lab Action before cleanup; no teardown performed.')


class Session:
    def __init__(self):
        if os.geteuid() == 0:
            raise ValueError('Run with the ordinary-user application venv; the agent is separate.')
        self.cfg = load_settings(CONFIG)
        self.store = Store(self.cfg.database_path)
        launch = json.loads((self.cfg.runtime_dir / 'app_launcher.json').read_text())
        self.url = f'http://127.0.0.1:{self.cfg.port}'
        if (launch['config_hash'] != self.cfg.config_hash or launch['config'] != str(CONFIG)
                or launch['dashboard_api_url'] != self.url
                or not all(owned(launch['components'].get(k)) for k in ('backend', 'dashboard'))
                or '--server.port=8502' not in launch['components']['dashboard']['argv']):
            raise ValueError('Managed API/UI identity or configuration mismatch. No laboratory operation submitted.')
        environment = (Path('/proc') / str(launch['components']['dashboard']['identity']['pid']) / 'environ').read_bytes().split(b'\0')
        if ('EXPLAINNET_API_URL=' + self.url).encode() not in environment:
            raise ValueError('Running dashboard environment targets a different API; no operation submitted.')
        self.binding = {'config': str(CONFIG), 'config_hash': self.cfg.config_hash, 'api_url': self.url,
            'dashboard_url': 'http://127.0.0.1:8502', 'database': str(self.cfg.database_path),
            'backend_identity': launch['components']['backend']['identity'],
            'dashboard_identity': launch['components']['dashboard']['identity'], 'owned_processes_verified': True}
        self.data = json.loads(LATEST.read_text()) if LATEST.exists() else None

    def http(self, route, body=None, key=None):
        req = urllib.request.Request(self.url + route, data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', 'Idempotency-Key': key or 'teach' + uuid4().hex})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def save(self):
        self.data['updated_utc'] = datetime.now(UTC).isoformat()
        atomic_json(LATEST, self.data)
        atomic_json(Path(self.data['receipt']), self.data)

    def job(self, route, body):
        pending = [j for j in self.data.get('jobs', []) if j.get('route') == route and j.get('body') == body
            and j.get('submission_state') in {'submitting', 'unknown'}]
        if pending:
            raise ValueError('Prior submission outcome unresolved. Inspect /v1/dashboard/submissions/' + pending[-1]['request_key'] + '; no new mutation submitted.')
        intent = {'route': route, 'body': body, 'request_key': 'teach' + uuid4().hex, 'submission_state': 'submitting'}
        self.data.setdefault('jobs', []).append(intent)
        self.save()
        try:
            submitted = self.http(route, body, intent['request_key'])
        except Exception:
            intent['submission_state'] = 'unknown'
            self.save()
            raise
        intent.update(job_id=submitted['job_id'], submission_state='acknowledged')
        self.save()
        print(route + ' → ' + submitted['job_id'], flush=True)
        end = time.monotonic() + 130
        while time.monotonic() < end:
            result = self.http('/v1/jobs/' + submitted['job_id'])
            stored = self.store.get_job(submitted['job_id'])
            if not stored or stored['id'] != result['id']:
                raise ValueError('HTTP job is absent from configured SQLite store; stopped without retry.')
            if result['state'] == 'succeeded':
                intent['execution_state'] = 'succeeded'
                self.save()
                return result['result']
            if result['state'] in {'failed', 'canceled', 'interrupted'}:
                raise RuntimeError(str(result.get('error') or result['state']))
            time.sleep(.5)
        raise TimeoutError('Job outcome unknown. Inspect the saved job ID; no mutation was retried.')

    def current(self):
        if (not self.data or self.data['config_hash'] != self.cfg.config_hash
                or not self.data['instance_id'].startswith('teachlive_')):
            raise ValueError('No matching owned demo-session receipt.')
        return self.data['instance_id']

    def idle(self):
        control = self.http('/v1/lab/control')
        if (control['auto_enabled'] or control.get('active_workflow_id') or control.get('monitor_active')
                or control.get('unsettled_action_ids') or control.get('degraded') or control.get('cleanup_pending_workflow_ids')):
            raise ValueError('Automatic mode/active workflow present; inspect it before starting another operation.')
        return control

    def healthy_traffic(self):
        instance = self.current()
        self.idle()
        with self.store.connection() as db:
            actions = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM lab_action_state WHERE instance_id=?', (instance,))]
        teardown_allowed(self.http('/v1/lab/control'), actions)
        if self.data.get('ground_truth'):
            raise ValueError('Fault was introduced; do not renew healthy traffic during a repair demonstration.')
        journal = self.http('/v1/laboratory/scenarios/' + instance).get('laboratory_journal') or {}
        if journal.get('state') not in {None, 'stopped'}:
            raise ValueError('Privileged owner reports an unsettled/active scenario; healthy renewal prohibited.')
        reconciled = self.job('/v1/laboratory/reconcile', {'instance_id': instance})
        known_run = (self.data.get('healthy_traffic') or {}).get('run_id')
        if any(r['state'] == 'running' and r['run_id'] != known_run for r in reconciled.get('runs', [])):
            raise ValueError('Untracked owned traffic is still running (possibly a lost acknowledgement). Inspect it before renewal; no duplicate traffic started.')
        if self.data.get('healthy_traffic'):
            self.job('/v1/telemetry/stop', {'instance_id': instance})
            run_id = self.data['healthy_traffic']['run_id']
            # A failed reply does not imply a failed mutation. Read the owned
            # root state first; cache writes occur only in the explicit reconcile job.
            actual = self.http('/v1/traffic/' + instance + '/' + run_id)
            state = actual['state']
            if actual['instance_id'] != instance or actual['run_id'] != run_id:
                raise ValueError('Traffic reconciliation target mismatch; no new traffic started.')
            self.data.setdefault('renewal_reconciliations', []).append({
                'at_utc': datetime.now(UTC).isoformat(), 'run_id': run_id,
                'cached_state': self.data['healthy_traffic'].get('state'), 'actual_state': state,
                'ended_utc': actual.get('ended_utc'), 'stop_required': state == 'running'})
            self.save()
            if state == 'running':
                self.job('/v1/traffic/stop', {'instance_id': instance, 'run_id': run_id})
            elif state not in {'succeeded', 'failed', 'canceled', 'interrupted'}:
                raise ValueError('Unknown traffic state; inspect before retrying renewal.')
        self.data['healthy_traffic'] = self.job('/v1/traffic/start', {
            'instance_id': instance, 'profile_ids': ['critical', 'bulk'], 'stream_receiver': True})
        self.data['collector'] = self.job('/v1/telemetry/start', {'instance_id': instance, 'duration_s': 600})
        self.data['traffic_expected_expiry_utc'] = (datetime.fromisoformat(
            self.data['healthy_traffic']['created_utc']) + timedelta(seconds=900)).isoformat()
        self.data['collector_expected_expiry_utc'] = (datetime.fromisoformat(
            self.data['collector']['session']['started_utc']) + timedelta(seconds=600)).isoformat()
        self.data['state'] = 'healthy_running'
        self.save()

    def prepare(self):
        self.idle()
        resume = False
        if self.data and self.http('/v1/networks/' + self.current())['state'] == 'running':
            resume = self.data['state'] == 'preparing' or (
                self.data['state'] == 'healthy_running' and self.data.get('policy') and not self.data.get('reference'))
            if not resume:
                raise ValueError('A session is already running. Use status or renew; no second network created.')
        if self.http('/v1/models').get('active_model_id'):
            raise ValueError('This qualified observed-only store has an active classifier; none was disabled.')
        if not resume:
            tag = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:6]
            directory = LATEST.parent / 'sessions' / tag
            directory.mkdir(parents=True)
            self.data = {'started_utc': datetime.now(UTC).isoformat(), 'instance_id': 'teachlive_' + uuid4().hex[:10],
                'config_hash': self.cfg.config_hash, 'binding': self.binding, 'receipt': str(directory / 'session.json'),
                'auto_cleanup': False, 'inference_mode': 'observed-only store; opt-in required at recommend', 'state': 'preparing'}
            self.save()
        directory = Path(self.data['receipt']).parent
        instance = self.current()
        self.data['construction'] = (self.http('/v1/networks/' + instance) if resume else
            self.job('/v1/networks/start', {'instance_id': instance}))
        self.data['connectivity'] = self.job('/v1/networks/probe', {
            'instance_id': instance, 'source_host': 'h1', 'target_host': 'h3'})
        if not self.data['connectivity']['passed']:
            raise ValueError('Owned original connectivity failed; state retained for inspection.')
        if not self.data.get('healthy_traffic'):
            self.healthy_traffic()
        else:
            self.data['collector'] = self.http('/v1/dashboard/telemetry/' + instance + '?limit=1')['collector']
            self.data['traffic_expected_expiry_utc'] = (datetime.fromisoformat(
                self.data['healthy_traffic']['created_utc']) + timedelta(seconds=900)).isoformat()
            self.data['collector_expected_expiry_utc'] = (datetime.fromisoformat(
                self.data['collector']['session']['started_utc']) + timedelta(seconds=600)).isoformat()
        if not self.data.get('policy'):
            time.sleep(4)
            twins = TwinService(self.store, AgentClient(self.cfg.agent_socket), self.cfg.objective)
            pilots = [twins.capture(instance, 10)['window'] for _ in range(2)]
            baseline = {'window_ids': [w['window_id'] for w in pilots],
                'definition_hash': digest(load_network(self.cfg.topology_file).model_dump())}
            _, policy = twins.pilot_reference(**baseline)
            self.data.update(pilots=pilots, baseline=baseline, policy=policy)
        baseline, policy = self.data['baseline'], self.data['policy']
        atomic_json(directory / 'baseline.json', baseline)
        atomic_json(directory / 'policy.json', policy)
        self.data['reference'] = self.job('/v1/telemetry/reference', {'window_id': baseline['window_ids'][-1]})
        self.data['state'] = 'healthy_running'
        self.save()

    def fault(self):
        instance = self.current()
        self.idle()
        if self.data.get('ground_truth') or not self.data.get('policy'):
            raise ValueError('Fault already submitted or healthy baseline unqualified; no fault retry.')
        self.job('/v1/telemetry/stop', {'instance_id': instance})
        self.job('/v1/traffic/stop', {'instance_id': instance, 'run_id': self.data['healthy_traffic']['run_id']})
        scenario = {'schema_version': 1, 'config_version': 'recovery_observation_v1', 'kind': 'latency',
            'severity': 'high', 'warmup_s': 3, 'measurement_s': 900, 'bidirectional': False, 'variation_ms': 0,
            'high_utilization': False, 'traffic_profile': 'moderate', 'critical_bps': 8000000,
            'bulk_protocol': 'udp', 'packet_size': 1200, 'seed': 20261019}
        # Separate setup only. Neither this recipe nor its receipt enters baseline/policy/workflow inference.
        self.data['ground_truth'] = {'submitted_utc': datetime.now(UTC).isoformat(), 'recipe': scenario}
        self.save()
        self.data['ground_truth']['receipt'] = self.job('/v1/laboratory/scenarios/start', {
            'instance_id': instance, 'scenario': scenario})
        self.data['collector'] = self.job('/v1/telemetry/start', {'instance_id': instance, 'duration_s': 600})
        self.data['collector_expected_expiry_utc'] = (datetime.fromisoformat(
            self.data['collector']['session']['started_utc']) + timedelta(seconds=600)).isoformat()
        self.data['traffic_expected_expiry_utc'] = (datetime.now(UTC) + timedelta(seconds=900)).isoformat()
        self.data['state'] = 'fault_running'
        self.save()

    def recommend(self, observed_only):
        instance = self.current()
        self.idle()
        if not observed_only or self.http('/v1/models').get('active_model_id'):
            raise ValueError('Explicit --observed-only opt-in and a genuinely untrained demo store are required.')
        if not self.data.get('ground_truth') or self.data.get('workflow_id'):
            raise ValueError('Introduce the supported fault first. A submitted workflow is never silently retried.')
        self.job('/v1/lab/mode', {'mode': 'recommend', 'allow_observed_only': True})
        workflow_id = 'w' + uuid4().hex
        body = {'instance_id': instance, 'workflow_id': workflow_id, 'request_key': 'k' + uuid4().hex,
            'baseline': self.data['baseline'], 'policy': self.data['policy'],
            'max_hypotheses': 2, 'max_repairs': 1, 'timeout_s': 900}
        self.data['workflow_id'] = workflow_id
        atomic_json(Path(self.data['receipt']).parent / 'workflow_request.json', body)
        self.job('/v1/lab/workflow', body)
        previous = None
        end = time.monotonic() + 920
        while time.monotonic() < end:
            result = self.http('/v1/lab/workflows/' + workflow_id)
            if result['state'] != previous:
                print(workflow_id + ': ' + result['state'], flush=True)
                previous = result['state']
            if result['state'] in TERMINAL:
                self.data['workflow'] = result
                self.save()
                return
            time.sleep(1)
        raise TimeoutError('Workflow still running; inspect its ID. No apply/cleanup/retry was attempted.')

    def status(self):
        instance = self.current()
        data = self.http('/v1/dashboard/telemetry/' + instance + '?limit=4')
        current_run = (data['collector'].get('session') or {}).get('run_id')
        window = next((w for w in data['windows'] if w.get('complete') and w['run_id'] == current_run), None)
        if window:
            with self.store.connection() as db:
                row = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (window['window_id'],)).fetchone()
            if not row or json.loads(row[0]) != window:
                raise ValueError('Dashboard window does not match configured SQLite evidence store.')
        workflow = self.http('/v1/lab/workflows/' + self.data['workflow_id']) if self.data.get('workflow_id') else {}
        report = {'binding': self.binding, 'instance_id': instance, 'network': self.http('/v1/networks/' + instance)['state'],
            'control': self.http('/v1/lab/control'), 'collector': data['collector'], 'window': window,
            'same_store_window_verified': bool(window), 'workflow_id': self.data.get('workflow_id'),
            'workflow_state': workflow.get('state'), 'incident_id': workflow.get('incident_id'),
            'experiment_id': workflow.get('experiment_id'), 'diagnosis': workflow.get('diagnosis'),
            'reasons': workflow.get('reasons'),
            'traffic_expected_expiry_utc': self.data.get('traffic_expected_expiry_utc'),
            'collector_expected_expiry_utc': self.data.get('collector_expected_expiry_utc')}
        self.data['last_status'] = report
        self.save()
        print(json.dumps({k: v for k, v in report.items() if k != 'window'} | {
            'window_id': (window or {}).get('window_id'), 'features': (window or {}).get('features')}, indent=2))

    def cleanup(self):
        instance = self.current()
        with self.store.connection() as db:
            actions = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM lab_action_state WHERE instance_id=?', (instance,))]
        teardown_allowed(self.http('/v1/lab/control'), actions)
        self.job('/v1/laboratory/reconcile', {'instance_id': instance})
        self.job('/v1/lab/mode', {'mode': 'recommend', 'allow_observed_only': False})
        self.job('/v1/telemetry/stop', {'instance_id': instance})
        if self.http('/v1/networks/' + instance)['state'] == 'running':
            journal = self.http('/v1/laboratory/scenarios/' + instance).get('laboratory_journal') or {}
            if journal.get('state') not in {None, 'stopped'}:
                self.job('/v1/laboratory/scenarios/reset', {'instance_id': instance})
        self.job('/v1/networks/cleanup', {'instance_id': instance})
        self.data.update(state='cleaned', cleaned_utc=datetime.now(UTC).isoformat())
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'renew', 'status', 'fault', 'recommend', 'cleanup'])
    parser.add_argument('--observed-only', action='store_true')
    args = parser.parse_args()
    session = Session()
    if args.stage == 'prepare':
        session.prepare()
    elif args.stage == 'renew':
        session.healthy_traffic()
    elif args.stage == 'fault':
        session.fault()
    elif args.stage == 'recommend':
        session.recommend(args.observed_only)
    elif args.stage == 'cleanup':
        session.cleanup()
    session.status()


if __name__ == '__main__':
    main()
