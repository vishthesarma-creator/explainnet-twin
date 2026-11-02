"""Stage 13 software fixtures; never experimental packet evidence."""
import json
from unittest.mock import patch

import numpy as np
import pytest

from explainnet.evaluation import summarize_predictions
from explainnet.model_contracts import CLASS_ORDER
from explainnet.storage import Store
from explainnet.telemetry_storage import TelemetryRepository
from explainnet.topology.spec import runtime_switch_name, scale_definition


def test_native_arrival_one_flush_idempotent_and_recoverable(tmp_path):
    store = Store(tmp_path / 'e.sqlite3')
    store.initialize()
    store.insert_record('runs', 'r1', {'created_utc':'2026-10-16T00:00:00+00:00'}, config_hash='fixture')
    repo = TelemetryRepository(store)
    records = [{'sample_id':f'i{i}', 'run_id':'r1', 'source':'iperf_receiver_interval',
        'at_utc':'2026-10-16T00:00:00+00:00', 'value':i} for i in range(100)]
    with patch('explainnet.telemetry_storage.os.fsync') as fsync:
        assert repo.ingest_many(records) == 100
        assert fsync.call_count == 1
        assert repo.ingest_many(records) == 0
        assert fsync.call_count == 1
    path = repo.directory / 'r1.jsonl'
    previous = path.read_bytes()
    with pytest.raises(ValueError, match='different contents'):
        repo.ingest_many([records[0] | {'value':999}])
    assert path.read_bytes() == previous
    # Simulate an fsynced append whose index transaction was interrupted.
    extra = records[0] | {'sample_id':'new'}
    with path.open('ab') as output:
        output.write(json.dumps(extra).encode()+b'\n'+b'{partial')
    assert repo.recover('r1') == {'recovered':1, 'partial_tail_bytes':8}
    assert len(repo.samples('r1')) == 101
    with store.connection() as db:
        for offset, payload in db.execute('SELECT raw_offset,payload_json FROM telemetry_samples'):
            assert json.loads(path.read_bytes()[offset:].splitlines()[0]) == json.loads(payload)


def test_native_arrival_rejects_cross_collector_and_unbounded(tmp_path):
    store = Store(tmp_path / 'e.sqlite3')
    store.initialize()
    repo = TelemetryRepository(store)
    with pytest.raises(ValueError, match='one collector'):
        repo.ingest_many([{'run_id':'a'},{'run_id':'b'}])
    with pytest.raises(ValueError, match='2048'):
        repo.ingest_many([{}]*2049)


def test_metric_class_order_and_episode_uncertainty():
    y = [c for c in CLASS_ORDER for _ in range(4)]
    p = np.repeat(np.eye(5),4,axis=0)
    episodes = [c+str(i//2) for c in CLASS_ORDER for i in range(4)]
    result = summarize_predictions(y,p,episodes,[{'status':'supported','incident':c!='healthy'} for c in y],
        {'seed':12,'bootstrap_repetitions':20})
    assert result['windows'] == 20 and result['episodes'] == 10
    assert result['window_classification']['accuracy'] == 1
    assert result['calibration']['log_loss'] == 0
    assert result['calibration']['multiclass_brier_sum'] == 0
    assert result['uncertainty']['macro_f1_95_percentile_interval'] == [1,1]


@pytest.mark.parametrize('size',[5,10,15])
def test_scale_definition_and_linux_interface_bounds(size):
    from pathlib import Path

    import yaml
    base = yaml.safe_load(Path('config/topology.yaml').read_text())
    scaled = scale_definition(base,size)
    assert len(scaled['switches']) == size
    assert scaled['pairs'][0]['paths']['primary'] == base['pairs'][0]['paths']['primary']
    assert len(scaled['pairs'][0]['paths']['alternative']) == size-2
    for s in scaled['switches']:
        assert len((runtime_switch_name('a1b2c3',s)+'-eth9').encode()) <= 15
    assert len({runtime_switch_name('a1b2c3',s) for s in scaled['switches']}) == size


def test_stage13_training_uses_only_train_preprocessing_and_validation_calibration(monkeypatch):
    from test_models import group_fixture, measurements, window

    from explainnet.contracts import ServiceObjective
    from explainnet.model_dataset import Partition
    from explainnet.model_features import feature_array
    from explainnet.model_training import train_models
    from explainnet.telemetry_contracts import TelemetrySettings
    train = group_fixture()
    train.X = feature_array([measurements() for _ in train.y])
    labels = np.asarray([c for c in CLASS_ORDER for _ in range(12)])
    val_windows = [window() for _ in labels]
    for i,w in enumerate(val_windows):
        w['window_id'] = 'validation'+str(i)
        w['start_monotonic_s'] = i*10
        w['features']['rtt_mean_ms'] = 100
    validation = Partition(feature_array([w['features'] for w in val_windows]),labels,
        np.asarray(['validation_'+c for c in labels]),np.asarray([c+str(i//6) for i,c in enumerate(labels)]),val_windows)
    monkeypatch.setattr('explainnet.model_training.CANDIDATES',[{'max_depth':2,'min_samples_leaf':2,'max_features':'sqrt'}])
    bundle,report = train_models(train,validation,{'manifest_sha256':'fixture'},TelemetrySettings(),ServiceObjective(),profile='stage13')
    pre = bundle['classifier'][0]
    assert pre.sample_count_ == len(train.y)
    assert pre.statistics_[pre.feature_names_.index('rtt_mean_ms')] == measurements()['rtt_mean_ms']
    assert report['calibration']['ready'] and report['calibration']['fit_examples'] == 60
    assert report['data_coverage']['calibration_partition'] == 'validation'
    assert not set(report['data_coverage']['estimator_fit_groups']) & set(report['data_coverage']['calibration_groups'])


def test_completed_async_explanation_is_rechecked_without_weakening_gate(tmp_path):
    from types import SimpleNamespace

    from test_workflow import coordinator
    c = coordinator(tmp_path)
    c._mode_gate = lambda _: {'allow_observed_only':False}
    c._save = lambda _: None
    w = {'state':'recommended','diagnosis':{'status':'supported','model_id':'m'},
        'explanation':{'status':'pending','explanation_id':'x','window_id':'w'},'experiment_id':'e'}
    c.worker.explanations.get = lambda _: {'status':'ready','model_id':'other','window_id':'w'}
    with pytest.raises(ValueError,match='lineage'):
        c._eligible(w,False)
    c.worker.explanations.get = lambda _: {'status':'ready','model_id':'m','window_id':'w'}
    c.recovery = SimpleNamespace(get=lambda _: {'state':'uncertain'})
    with pytest.raises(ValueError,match='poor-fidelity'):
        c._eligible(w,False)
    assert w['explanation']['status'] == 'ready'


def test_evaluation_freeze_is_write_once_and_blocks_modified_evaluator(tmp_path,monkeypatch):
    from types import SimpleNamespace

    from explainnet.evaluation import evaluate_test, file_hash, freeze
    data = tmp_path/'datasets'/'batch'
    data.mkdir(parents=True)
    (data/'manifest.json').write_text(json.dumps({'dataset_ready':True}))
    store = SimpleNamespace(path=tmp_path/'db.sqlite3',audit=lambda *a,**kw:None)
    bundle = {'training_profile':'stage13','dataset':{'batch_id':'batch','manifest_sha256':file_hash(data/'manifest.json')}}
    registry = SimpleNamespace(inspect=lambda _: {'manifest_sha256':'trusted'},load=lambda _:bundle)
    monkeypatch.setattr('explainnet.evaluation.BundleRepository',lambda _:registry)
    cfg = tmp_path/'configuration.json'
    cfg.write_text(json.dumps({'training_profile':'stage13','test_tuning_permitted':False}))
    saved = freeze(store,'m',cfg,tmp_path/'out')
    assert freeze(store,'m',cfg,tmp_path/'out') == saved
    cfg.write_text(json.dumps({'training_profile':'stage13','test_tuning_permitted':False,'changed':True}))
    with pytest.raises(ValueError,match='frozen evaluation changed'):
        freeze(store,'m',cfg,tmp_path/'out')
    with pytest.raises(ValueError,match='evaluator changed'):
        evaluate_test(store,saved|{'evaluator_sha256':'changed'},None,tmp_path/'out')


def test_full_frozen_evaluator_saves_predictions_before_labels(tmp_path,monkeypatch):
    """Tiny explicit software fixture, never a measured quality/accuracy claim."""
    from pathlib import Path
    from types import SimpleNamespace

    import yaml
    from test_models import fitted_unit_bundle, window

    from explainnet.contracts import ServiceObjective
    from explainnet.dataset_contracts import digest
    from explainnet.dataset_repository import DatasetRepository
    from explainnet.evaluation import evaluate_test, file_hash, freeze
    from explainnet.model_bundle import BundleRepository
    from explainnet.telemetry_contracts import TelemetrySettings
    store=Store(tmp_path/'e.sqlite3'); store.initialize()
    batch={'batch_id':'fixture','state':'completed','schedule_hash':'unit','owner_pid':1,
        'definition':yaml.safe_load(Path('config/topology.yaml').read_text())}
    repo=DatasetRepository(store); repo.save_batch(batch)
    splits={p:{'window_ids':[],'episode_ids':[],'family_ids':[]} for p in ('train','validation','test')}
    labels=[]
    for c in CLASS_ORDER:
        for repetition in range(2):
            ident=c+str(repetition)
            w=window()|{'window_id':'w'+ident,'run_id':'r'+ident,'sample_ids':[],
                'context':{'selected_paths':{'critical':'primary'}}}
            store.insert_record('runs',w['run_id'],{},config_hash='fixture')
            with store.connection() as db:
                db.execute('INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?)',
                    (w['window_id'],w['run_id'],w['instance_id'],10,1,1,json.dumps(w)))
                db.execute('INSERT INTO ground_truth VALUES(?,?)',(w['run_id'],json.dumps({'fault_label':c,
                    'intended_location':None if c=='healthy' else 's2->s3','activated_utc':w['at_utc']})))
            attempt={'attempt_id':'a'+ident,'batch_id':'fixture','episode_id':ident,'state':'completed',
                'main_traffic':{'run_id':w['run_id']}}
            repo.save_attempt(attempt)
            with store.connection() as db:
                db.execute('INSERT INTO dataset_members VALUES(?,?,?,?,?,?,?)',
                    (w['window_id'],'fixture',ident,c,'test',attempt['attempt_id'],digest(w)))
            for key,value in [('window_ids',w['window_id']),('episode_ids',ident),('family_ids',c)]:
                if value not in splits['test'][key]: splits['test'][key].append(value)
            labels.append({'window_id':w['window_id'],'label':c})
    data=tmp_path/'datasets/fixture'; data.mkdir(parents=True)
    (data/'splits.json').write_text(json.dumps(splits))
    (data/'labels.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in labels))
    manifest={'dataset_ready':True,'batch_id':'fixture','files':{p.name:{'sha256':file_hash(p)} for p in data.iterdir()}}
    (data/'manifest.json').write_text(json.dumps(manifest))
    bundle,X=fitted_unit_bundle(); bundle.update(training_profile='stage13',dataset={'batch_id':'fixture','manifest_sha256':file_hash(data/'manifest.json')})
    BundleRepository(store).publish(bundle,{},X)
    cfg=tmp_path/'config.json'; cfg.write_text(json.dumps({'training_profile':'stage13','test_tuning_permitted':False,
        'seed':12,'bootstrap_repetitions':10}))
    out=tmp_path/'evaluation'
    frozen=freeze(store,bundle['model_id'],cfg,out)
    original=Path.read_text
    def guarded(path,*args,**kwargs):
        if path==data/'labels.jsonl': assert (out/'test_predictions.json').exists()
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    result=evaluate_test(store,frozen,SimpleNamespace(telemetry=TelemetrySettings(),objective=ServiceObjective()),out)
    assert result['windows']==10 and result['episodes']==10 and result['split']=='test'
    assert result['prediction_sha256']==file_hash(out/'test_predictions.json')


def test_pending_test_measurements_are_excluded_before_decode(tmp_path):
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient
    from test_dashboard import settings

    from explainnet.api import create_app
    cfg=settings(tmp_path); store=Store(cfg.database_path); store.initialize()
    with store.connection() as db:
        db.execute("INSERT INTO runs VALUES('run',?,'fixture','{}')",(datetime.now(UTC).isoformat(),))
        db.execute("INSERT INTO dataset_batches VALUES('batch','planned','fixture',1,'{}')")
        db.execute('INSERT INTO dataset_attempts VALUES(?,?,?,?,?)',('attempt','batch','episode','running',
            json.dumps({'collector_run_id':'run','partition':'test'})))
        # Deliberately unparseable fixture: exclusion must happen inside SQL,
        # before JSON decoding even when accepted membership is still absent.
        db.execute('INSERT INTO telemetry_windows VALUES(?,?,?,?,?,?,?)',('sealed','run','source',10,1,1,'SEALED'))
    client=TestClient(create_app(cfg))
    assert client.get('/v1/dashboard/windows/sealed').status_code==404
    assert client.get('/v1/dashboard/telemetry/source').json()['windows']==[]
    assert client.get('/v1/dashboard/telemetry-sources').json()['records']==[]
