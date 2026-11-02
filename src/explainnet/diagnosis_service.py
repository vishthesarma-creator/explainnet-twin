"""Explicit local training and read-only inference; durable completed-window deduplication."""
import fcntl
import json
import threading
from uuid import uuid4

from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json, export_dataset
from explainnet.dataset_repository import DatasetRepository
from explainnet.model_bundle import BundleRepository
from explainnet.storage import utc_now


class DiagnosisService:
    def __init__(self, store, telemetry, artifact_dir=None):
        self.store, self.telemetry = store, telemetry
        self.bundles = BundleRepository(store)
        self.active = None
        self.lock = threading.RLock()
        self.stop_event, self.thread = threading.Event(), None
        self.last_live_error = None
        self.artifact_dir = artifact_dir
        self.on_diagnosis, self.explanation_error = None, None

    def train(self, batch_id, profile='stage7'):
        self.bundles.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.bundles.root / 'training.lock').open('a+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('another explicit model-training operation owns the lock') from exc
            return self._train(batch_id, profile)

    def _train(self, batch_id, profile='stage7'):
        batch = DatasetRepository(self.store).batch(batch_id)
        if not batch or batch['state'] != 'completed':
            raise ValueError('measured dataset is incomplete or not ready; training refused')
        from explainnet.model_dataset import load_measured_dataset
        from explainnet.model_training import train_models
        exported = export_dataset(self.store, batch_id)
        if not exported['quality']['dataset_ready']:
            raise ValueError('dataset quality gates prevent training')
        directory = self.store.path.parent / 'datasets' / batch_id
        train, validation, hashes = load_measured_dataset(directory)
        if profile == 'completion3':
            if hashes['dataset_version'] != 'completion3_v1' or self.artifact_dir is None:
                raise ValueError('Completion3 requires its prospectively declared cohort/protocol')
            protocol = json.loads((self.artifact_dir.parent / 'protocol.json').read_text())
            declared = digest({k:v for k,v in protocol.items() if k != 'protocol_hash'})
            if declared != protocol['protocol_hash'] or protocol['training']['profile'] != profile:
                raise ValueError('Completion3 protocol integrity/profile mismatch')
            schedule = json.loads((self.artifact_dir.parent / 'schedule.json').read_text())
            if digest(schedule) != batch['schedule_hash']:
                raise ValueError('Completion3 measured schedule differs from prospective declaration')
            hashes['protocol_hash'] = declared
            hashes['collection_application_config_hash'] = batch['config_hash']
        for previous in self.bundles.list():
            if previous['manifest']['dataset']['manifest_sha256'] == hashes['manifest_sha256']:
                raise ValueError('dataset already trained; reuse existing immutable version instead of repeated training')
        bundle, report = train_models(train, validation, hashes, self.telemetry.settings, self.telemetry.objective, profile=profile)
        if profile == 'completion3':
            from explainnet.explanation_engine import build_background
            bundle['training_background'] = build_background(bundle, train, hashes, report['data_coverage']['estimator_fit_groups'])
            report['training_background'] = {k:v for k,v in bundle['training_background'].items() if k != 'matrix'}
        record = self.bundles.publish(bundle, report, validation.X)
        report['artifact_paths'] = {'bundle_directory': record['directory'],
            'validation_report': str(self.bundles.root / bundle['model_id'] / 'validation_report.json')}
        if self.artifact_dir is not None:
            atomic_json(self.artifact_dir / 'model_validation_report.json', report)
        # Diagnosis records refer to stored measured windows; test remains sealed.
        with self.lock:
            for window, result in zip(validation.windows, report['validation_diagnoses'], strict=True):
                with self.store.connection() as db:
                    actual = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (window['window_id'],)).fetchone()
                self._persist(json.loads(actual[0]), result)
        return {'bundle': record, 'validation_report': report}

    def activate(self, model_id):
        bundle = self.bundles.load(model_id)
        with self.lock:
            with self.store.connection() as db:
                db.execute('INSERT INTO model_activation VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET model_id=excluded.model_id', (model_id,))
            self.active = bundle
        self.store.audit('model-loading', 'model_activated', {'model_id': model_id}, subject_id=model_id)
        return {'active_model_id': model_id, 'network_changes': False}

    def start(self):
        with self.store.connection() as db:
            row = db.execute('SELECT model_id FROM model_activation WHERE singleton=1').fetchone()
        if row:
            try:
                self.active = self.bundles.load(row[0])
            except (ValueError, OSError) as exc:
                self.last_live_error = str(exc)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name='read-only-diagnosis', daemon=False)
        self.thread.start()

    def _sealed(self, window_id):
        with self.store.connection() as db:
            row = db.execute('SELECT partition FROM dataset_members WHERE window_id=?', (window_id,)).fetchone()
            pending = db.execute("SELECT 1 FROM dataset_attempts a JOIN telemetry_windows w ON "
                "json_extract(a.payload_json,'$.collector_run_id')=w.run_id "
                "WHERE w.window_id=? AND json_extract(a.payload_json,'$.partition')='test' LIMIT 1", (window_id,)).fetchone()
        return bool((row and row[0] == 'test') or pending)

    def _persist(self, window, result):
        with self.store.connection() as db:
            db.execute('INSERT OR IGNORE INTO diagnoses VALUES(?,?,?,?,?,?,?)',
                ('g' + uuid4().hex, window['window_id'], result['model_id'], result['mode'], utc_now(),
                 digest(window), json.dumps(result, allow_nan=False)))
            row = db.execute('SELECT payload_json FROM diagnoses WHERE window_id=? AND model_id=? AND mode=?',
                (window['window_id'], result['model_id'], result['mode'])).fetchone()
        saved = json.loads(row[0])
        if self.on_diagnosis:
            try:
                self.on_diagnosis(window, saved)
                self.explanation_error = None
            except Exception as exc:  # noqa: BLE001 - explanations cannot invalidate a saved diagnosis
                self.explanation_error = str(exc)
        return saved

    def diagnose(self, model_id, window_id, mode='recorded'):
        if self._sealed(window_id):
            raise ValueError('test partition sealed until Stage 13')
        with self.lock:
            with self.store.connection() as db:
                row = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (window_id,)).fetchone()
                previous = db.execute('SELECT payload_json,window_hash FROM diagnoses WHERE window_id=? AND model_id=? AND mode=?',
                    (window_id, model_id, mode)).fetchone()
                alert = db.execute('SELECT payload_json FROM baseline_alerts WHERE window_id=?', (window_id,)).fetchone()
            if not row:
                raise ValueError('unknown telemetry window')
            window = json.loads(row[0])
            live = self.telemetry.status(window['instance_id'])['live'] if mode == 'live' else False
            if previous:
                output = json.loads(previous[0])
                output['deduplicated'] = True
                if previous[1] != digest(window):
                    output.update(status='uncertain', reasons=['stored telemetry window changed after diagnosis; record retained, no repeated processing'])
                if mode == 'live':
                    from datetime import UTC, datetime
                    age = (datetime.now(UTC) - datetime.fromisoformat(window['at_utc'])).total_seconds()
                    if not live or age > self.telemetry.settings.stale_after_s:
                        output.update(status='stale', freshness='stale', reasons=['stored live diagnosis observation is now stale'])
                return output
            bundle = self.active if self.active and self.active['model_id'] == model_id else self.bundles.load(model_id)
            from explainnet.model_policy import infer
            result = infer(bundle, window, self.telemetry.settings, self.telemetry.objective, mode=mode,
                live=live, baseline=json.loads(alert[0]) if alert else None)
            if mode == 'recorded' and result['status'] == 'insufficient-data':
                return result  # Pending windows can be retried after actual receiver finalization.
            return self._persist(window, result)

    def _loop(self):
        while not self.stop_event.wait(2):
            if self.active is None:
                continue
            try:
                # Before accepted membership exists, a collector may belong to a reserved test episode.
                # No dataset collector is scored live; only completed train/validation saved windows are eligible.
                with self.store.connection() as db:
                    collecting = db.execute("SELECT 1 FROM dataset_batches WHERE state='running'").fetchone()
                if collecting:
                    continue
                for session in self.telemetry.repository.collectors():
                    if not self.telemetry.status(session['instance_id'])['live']:
                        continue
                    with self.store.connection() as db:
                        rows = db.execute('SELECT w.window_id FROM telemetry_windows w WHERE w.run_id=? '
                            'AND w.complete=1 AND w.inference_ready=1 '
                            'AND NOT EXISTS(SELECT 1 FROM dataset_members m WHERE m.window_id=w.window_id AND m.partition=\'test\') '
                            'AND NOT EXISTS(SELECT 1 FROM diagnoses d WHERE d.window_id=w.window_id AND d.model_id=? AND d.mode=\'live\') '
                            'ORDER BY w.end_monotonic_s LIMIT 20', (session['run_id'], self.active['model_id'])).fetchall()
                    for row in rows:
                        self.diagnose(self.active['model_id'], row[0], 'live')
                self.last_live_error = None
            except Exception as exc:  # noqa: BLE001 - expose model failure; never mutate networking
                self.last_live_error = str(exc)

    def status(self):
        return {'active_model_id': self.active['model_id'] if self.active else None,
            'live_error': self.last_live_error, 'explanation_error': self.explanation_error,
            'network_changes': False, 'bundles': self.bundles.list()}

    def history(self, window_id):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM diagnoses WHERE window_id=? ORDER BY created_utc', (window_id,))]

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(20)
            if self.thread.is_alive():
                raise RuntimeError('diagnosis worker did not finish before shutdown')
