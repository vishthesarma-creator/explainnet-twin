"""Durable asynchronous explanations; failures never replace diagnosis/monitoring."""
import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from uuid import uuid4

from explainnet.dataset_contracts import digest
from explainnet.explanation_contracts import ALGORITHM_VERSION, BACKGROUND_VERSION, SCALE
from explainnet.incident_service import IncidentService
from explainnet.link_localization import localize, observed_samples
from explainnet.storage import utc_now


class ExplanationService:
    def __init__(self, store, diagnosis, definition=None, background_limit=24):
        self.store, self.diagnosis, self.definition = store, diagnosis, definition
        settings = diagnosis.telemetry.settings
        self.incidents = IncidentService(store, definition, settings.recovery_windows, settings.stale_after_s)
        self.background_limit = background_limit
        self.cache, self.lock = {}, threading.RLock()
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.thread, self.last_error = None, None

    def request(self, model_id, window_id, mode='recorded'):
        if self.diagnosis._sealed(window_id):
            raise ValueError('test partition sealed until Stage 13')
        record = self.diagnosis.bundles.inspect(model_id)
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (window_id,)).fetchone()
            diag = db.execute('SELECT * FROM diagnoses WHERE window_id=? AND model_id=? AND mode=?', (window_id, model_id, mode)).fetchone()
        if not row:
            raise ValueError('unknown telemetry window')
        window = json.loads(row[0])
        result = json.loads(diag['payload_json']) if diag else None
        recipe = digest({'model_manifest': record['manifest_sha256'], 'background_algorithm': BACKGROUND_VERSION,
            'limit': self.background_limit, 'dataset': record['manifest']['dataset']})
        key = digest({'window_id': window_id, 'window_hash': digest(window), 'model_id': model_id,
            'model_manifest': record['manifest_sha256'], 'diagnosis': result, 'mode': mode, 'background_recipe': recipe,
            'feature_mapping': record['manifest']['transformed_names'], 'algorithm': ALGORITHM_VERSION,
            'shap_version': version('shap'), 'scale': SCALE})
        with self.lock:
            with self.store.connection() as db:
                existing = db.execute('SELECT payload_json FROM explanations WHERE cache_key=?', (key,)).fetchone()
            if existing:
                return json.loads(existing[0]) | {'cached': True}
            reason = ('no persisted eligible diagnosis' if not diag else 'telemetry changed after persisted diagnosis'
                if diag['window_hash'] != digest(window) else 'diagnosis has no selected class'
                if result.get('predicted_class') is None or result['status'] in {'stale', 'insufficient-data'} else None)
            incident_id = self.incidents.observe(window, result, diag['diagnosis_id'], diag['diagnosis_id']) if diag and reason != 'telemetry changed after persisted diagnosis' else None
            payload = {'schema_version': 1, 'explanation_id': 'x' + uuid4().hex, 'window_id': window_id,
                'model_id': model_id, 'diagnosis_id': diag['diagnosis_id'] if diag else None,
                'incident_id': incident_id, 'status': 'unsupported' if reason else 'pending', 'reason': reason,
                'cache_key': key, 'window_hash': digest(window), 'model_manifest_hash': record['manifest_sha256'],
                'background_recipe': recipe, 'background_limit': self.background_limit, 'background_version': None,
                'algorithm_version': ALGORITHM_VERSION, 'output_scale': SCALE, 'mode': mode, 'runtime_ms': None,
                'created_utc': utc_now(), 'created_monotonic_s':time.monotonic(), 'network_changes': False}
            with self.store.connection() as db:
                db.execute('INSERT OR IGNORE INTO explanations VALUES(?,?,?,?,?,?,?,?,?)',
                    (payload['explanation_id'], key, window_id, model_id, payload['diagnosis_id'], incident_id,
                     payload['status'], payload['created_utc'], json.dumps(payload)))
                saved = db.execute('SELECT payload_json FROM explanations WHERE cache_key=?', (key,)).fetchone()
            self.wake.set()
            return json.loads(saved[0])

    def after_diagnosis(self, window, result):
        # This only writes lifecycle/request metadata. SHAP/background/queue evidence
        # are handled by the dedicated thread; never by the telemetry collector.
        self.request(result['model_id'], window['window_id'], result['mode'])

    def get(self, explanation_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM explanations WHERE explanation_id=?', (explanation_id,)).fetchone()
        if not row:
            raise ValueError('unknown explanation')
        return json.loads(row[0])

    def history(self, window_id):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM explanations WHERE window_id=? ORDER BY created_utc', (window_id,))]

    def _runtime(self, payload):
        key = (payload['model_id'], payload['background_recipe'])
        if key in self.cache:
            return self.cache[key]
        from explainnet.explanation_engine import RFExplainer, build_background
        from explainnet.model_dataset import load_measured_dataset
        bundle = (self.diagnosis.active if self.diagnosis.active and self.diagnosis.active['model_id'] == payload['model_id']
            else self.diagnosis.bundles.load(payload['model_id']))
        with self.store.connection() as db:
            old = db.execute('SELECT content_hash,payload_json FROM explanation_backgrounds WHERE recipe_key=?', (payload['background_recipe'],)).fetchone()
        if old:
            background = json.loads(old['payload_json'])
            if old['content_hash'] != background['content_hash']:
                raise ValueError('registered background hash mismatch')
        else:
            train, _validation, hashes = (None, None, None) if bundle.get('training_background') else load_measured_dataset(self.store.path.parent / 'datasets' / bundle['dataset']['batch_id'])
            report = json.loads((self.diagnosis.bundles.root / bundle['model_id'] / 'validation_report.json').read_text())
            background = bundle.get('training_background') or build_background(bundle, train, hashes, report['data_coverage']['estimator_fit_groups'], payload['background_limit'])
            with self.store.connection() as db:
                db.execute('INSERT INTO explanation_backgrounds VALUES(?,?,?,?)',
                    (payload['background_recipe'], bundle['model_id'], background['content_hash'], json.dumps(background, allow_nan=False)))
        runtime = RFExplainer(bundle, background)
        self.cache[key] = runtime
        return runtime

    def process(self, payload):
        start = time.perf_counter()
        try:
            if self.diagnosis._sealed(payload['window_id']):
                raise ValueError('test partition sealed until Stage 13')
            with self.store.connection() as db:
                window = json.loads(db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (payload['window_id'],)).fetchone()[0])
                result = json.loads(db.execute('SELECT payload_json FROM diagnoses WHERE diagnosis_id=?', (payload['diagnosis_id'],)).fetchone()[0])
            samples = observed_samples(self.store, window)
            if digest(window) != payload['window_hash']:
                raise ValueError('telemetry changed while explanation was pending; request a new version')
            trusted = self.diagnosis.bundles.inspect(payload['model_id'])
            if trusted['manifest_sha256'] != payload['model_manifest_hash']:
                raise ValueError('model version changed while explanation was pending')
            directory = self.diagnosis.bundles.root / payload['model_id']
            for name, expected in {'manifest.json': trusted['manifest_sha256'], **trusted['manifest']['files']}.items():
                artifact = directory / name
                if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
                    raise ValueError('trusted model artifact changed')
            from explainnet.explanation_engine import plain_language
            runtime = self._runtime(payload)
            shap_result = runtime.explain(window, result)
            localization = localize(window, self.definition, samples)
            payload = payload | shap_result | {'localization': localization, 'plain_language': plain_language(shap_result, result, localization)}
        except Exception as exc:  # noqa: BLE001 - durable, isolated failure; monitoring remains alive
            payload = payload | {'status': 'failed', 'reason': str(exc)}
        payload['runtime_ms'] = (time.perf_counter() - start) * 1000
        payload['completed_utc'] = utc_now()
        payload['completed_monotonic_s'] = time.monotonic()
        with self.store.connection() as db:
            db.execute("UPDATE explanations SET state=?,payload_json=? WHERE explanation_id=? AND state='pending'",
                (payload['status'], json.dumps(payload, allow_nan=False), payload['explanation_id']))
        return payload

    def _monitor(self):
        # Monitoring still creates observed incidents when no model is activated.
        # Skip dataset collection and sealed/pending test members entirely.
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM dataset_batches WHERE state='running'").fetchone():
                return
            cutoff = (datetime.now(UTC) - timedelta(seconds=self.incidents.stale_after_s)).isoformat()
            rows = db.execute('SELECT w.payload_json,a.payload_json FROM telemetry_windows w JOIN baseline_alerts a USING(window_id) '
                'JOIN telemetry_collectors c ON c.run_id=w.run_id AND c.state=\'running\' '
                'WHERE json_extract(w.payload_json,\'$.at_utc\')>=? AND '
                'NOT EXISTS(SELECT 1 FROM incident_events e WHERE e.event_id=\'monitor:\'||w.window_id) '
                'ORDER BY w.end_monotonic_s DESC LIMIT 50', (cutoff,)).fetchall()
        for row in reversed(rows):
            window, alert = json.loads(row[0]), json.loads(row[1])
            if self.diagnosis._sealed(window['window_id']):
                continue
            if not self.diagnosis.telemetry.status(window['instance_id'])['live']:
                continue
            if self.diagnosis.active is not None and alert['status'] == 'healthy':
                # An activated classifier must agree before baseline-only evidence
                # can resolve its incident. The diagnosis callback owns that gate.
                continue
            self.incidents.observe(window, alert, 'monitor:' + window['window_id'])

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self._monitor()
                with self.store.connection() as db:
                    row = db.execute("SELECT payload_json FROM explanations WHERE state='pending' ORDER BY created_utc LIMIT 1").fetchone()
                if row:
                    self.process(json.loads(row[0]))
                    continue
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - expose storage/monitor error without terminating worker
                self.last_error = str(exc)
            self.wake.wait(1)
            self.wake.clear()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name='read-only-explanations', daemon=False)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(20)
            if self.thread.is_alive():
                raise RuntimeError('explanation worker did not finish before shutdown')

    def status(self):
        return {'worker_live': bool(self.thread and self.thread.is_alive()), 'last_error': self.last_error,
            'loaded_explainers': len(self.cache), 'network_changes': False}
