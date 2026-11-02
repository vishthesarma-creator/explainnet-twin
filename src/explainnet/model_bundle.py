"""Immutable atomic bundles, loadable only through the local generated-artifact registry."""
import fcntl
import hashlib
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from explainnet.dataset_contracts import digest
from explainnet.model_contracts import CLASS_ORDER, FEATURE_HASH, FEATURE_ORDER, UNITS
from explainnet.storage import utc_now
from explainnet.topology.spec import identifier


def validate_bundle(bundle):
    import numpy as np

    from explainnet.model_training import dependency_versions
    if (bundle['schema_version'] != 1 or bundle['feature_order'] != list(FEATURE_ORDER)
            or bundle['feature_units'] != UNITS or bundle['feature_schema_hash'] != FEATURE_HASH
            or bundle['class_order'] != list(CLASS_ORDER) or bundle['dependencies'] != dependency_versions()):
        raise ValueError('incompatible model schema, order, class map or dependencies')
    classifier = bundle['classifier']
    if set(classifier[-1].classes_) != set(CLASS_ORDER):
        raise ValueError('incompatible RF class ordering')
    pre = classifier[0]
    if classifier[-1].n_features_in_ != len(pre.transformed_names_):
        raise ValueError('incompatible transformed representation')
    if (bundle['calibrator'] is not None and
            bundle['calibrator'].estimator.estimator is not classifier):
        raise ValueError('calibration underlying RF is not the identified classifier')
    if not np.isfinite(bundle['anomaly_threshold']):
        raise ValueError('invalid anomaly threshold')
    background = bundle.get('training_background')
    if bundle.get('training_profile') == 'completion3':
        from explainnet.service_requirements import VERSION
        protocol = bundle['dataset'].get('protocol_hash', '')
        topology = bundle['dataset'].get('topology_hash')
        if (not background or len(protocol) != 64 or any(c not in '0123456789abcdef' for c in protocol)
                or not topology or bundle.get('supported_topology_hashes') != [topology]
                or bundle.get('service_contract_version') != VERSION):
            raise ValueError('incomplete completion3 protocol/domain/service/background binding')
    if background and (background.get('partition') != 'train' or background.get('model_id') != bundle['model_id']
            or background.get('dataset') != bundle['dataset']
            or background.get('content_hash') != digest({k:v for k,v in background.items() if k!='content_hash'})):
        raise ValueError('incompatible immutable training-only SHAP background')


class BundleRepository:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent / 'models'

    def inspect(self, model_id):
        identifier(model_id)
        with self.store.connection() as db:
            row = db.execute('SELECT payload_json FROM model_bundles WHERE model_id=?', (model_id,)).fetchone()
        if not row:
            raise ValueError('unknown trusted locally generated bundle')
        return json.loads(row[0])

    def list(self):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM model_bundles ORDER BY created_utc DESC')]

    def publish(self, bundle, report, verification_X):
        import joblib
        import numpy as np

        from explainnet.model_policy import ordered_probabilities
        validate_bundle(bundle)
        identifier(bundle['model_id'])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'publish.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            final = self.root / bundle['model_id']
            if final.exists():
                raise ValueError('immutable model version already exists')
            staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=self.root))
            artifact = staging / 'bundle.joblib'
            joblib.dump(bundle, artifact, compress=3)
            saved = joblib.load(artifact)
            validate_bundle(saved)
            for key in ('classifier', 'calibrator'):
                if bundle[key] is not None and not np.array_equal(ordered_probabilities(bundle[key], verification_X),
                                                                  ordered_probabilities(saved[key], verification_X)):
                    raise ValueError('bundle roundtrip changed probabilities')
            before = bundle['isolation_forest'].score_samples(bundle['anomaly_preprocessing'].transform(verification_X))
            after = saved['isolation_forest'].score_samples(saved['anomaly_preprocessing'].transform(verification_X))
            if not np.array_equal(before, after):
                raise ValueError('bundle roundtrip changed anomaly scores')
            (staging / 'validation_report.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
            manifest = {k: bundle[k] for k in ('schema_version', 'model_id', 'feature_order', 'feature_units',
                'feature_schema_hash', 'class_order', 'policy', 'anomaly_threshold', 'dataset', 'dependencies', 'seed', 'selected_parameters')}
            pre = bundle['classifier'][0]
            manifest.update(created_utc=utc_now(), trust='generated locally by explicit training; never load uploaded pickle',
                training_profile=bundle.get('training_profile','stage7'),
                raw_classifier='classifier.named_steps.random_forest', transformed_preprocessing='classifier.named_steps.preprocessing',
                transformed_names=pre.transformed_names_, original_mapping=pre.original_mapping_,
                calibration_ready=bundle['calibrator'] is not None,
                files={name: hashlib.sha256((staging / name).read_bytes()).hexdigest()
                       for name in ('bundle.joblib', 'validation_report.json')})
            for key in ['supported_topology_hashes','service_contract_version']:
                if key in bundle: manifest[key] = bundle[key]
            if 'runtime_dependencies' in bundle: manifest['runtime_dependencies'] = bundle['runtime_dependencies']
            if bundle.get('training_background'):
                manifest['training_background_sha256'] = bundle['training_background']['content_hash']
            (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n')
            for path in staging.iterdir():
                with path.open('rb') as handle:
                    os.fsync(handle.fileno())
                path.chmod(0o400)
            staging.chmod(0o500)
            os.rename(staging, final)
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            manifest_hash = hashlib.sha256((final / 'manifest.json').read_bytes()).hexdigest()
            record = {'model_id': bundle['model_id'], 'directory': str(final), 'manifest_sha256': manifest_hash, 'manifest': manifest}
            with self.store.connection() as db:
                db.execute('INSERT INTO model_bundles VALUES(?,?,?,?)',
                    (bundle['model_id'], manifest['created_utc'], manifest_hash, json.dumps(record)))
            self.store.audit('model-training', 'model_bundle_published', {'model_id': bundle['model_id'],
                'manifest_sha256': manifest_hash, 'dataset_hash': digest(bundle['dataset'])}, subject_id=bundle['model_id'])
            return record

    def load(self, model_id):
        import joblib

        from explainnet.model_training import dependency_versions
        record = self.inspect(model_id)
        directory = self.root / model_id
        if (directory.is_symlink() or directory.resolve().parent != self.root.resolve()
                or any((directory / name).is_symlink() for name in ('manifest.json', 'bundle.joblib', 'validation_report.json'))):
            raise ValueError('untrusted bundle path')
        manifest_bytes = (directory / 'manifest.json').read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != record['manifest_sha256']:
            raise ValueError('trusted model manifest changed')
        manifest = json.loads(manifest_bytes)
        if manifest['dependencies'] != dependency_versions():
            raise ValueError('incompatible dependency versions')
        binary = None
        for name, expected in manifest['files'].items():
            if name not in {'bundle.joblib', 'validation_report.json'}:
                raise ValueError('unsupported model artifact')
            data = (directory / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('trusted bundle artifact changed')
            if name == 'bundle.joblib':
                binary = data
        if binary is None:
            raise ValueError('model binary missing')
        bundle = joblib.load(BytesIO(binary))
        validate_bundle(bundle)
        if bundle['model_id'] != model_id:
            raise ValueError('model identity mismatch')
        return bundle
