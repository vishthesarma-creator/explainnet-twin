"""Stage 13 frozen, read-only held-out evaluation; never a live diagnosis input."""
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from explainnet.dataset_contracts import digest
from explainnet.dataset_export import atomic_json
from explainnet.link_localization import localize, observed_samples
from explainnet.model_bundle import BundleRepository
from explainnet.model_contracts import CLASS_ORDER
from explainnet.model_features import feature_array
from explainnet.model_policy import infer, ordered_probabilities
from explainnet.model_training import classification, detection, reliability
from explainnet.storage import utc_now
from explainnet.telemetry_monitor import evaluate


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(store, model_id, configuration, output):
    """Write once before any test inputs are loaded; conflicting resume is refused."""
    registry = BundleRepository(store)
    record = registry.inspect(model_id)
    bundle = registry.load(model_id)
    cfg = json.loads(Path(configuration).read_text())
    if bundle.get('training_profile') != cfg['training_profile'] or cfg['test_tuning_permitted']:
        raise ValueError('evaluation requires the predeclared Stage 13 training profile')
    directory = store.path.parent / 'datasets' / bundle['dataset']['batch_id']
    manifest = json.loads((directory / 'manifest.json').read_text())
    if not manifest['dataset_ready'] or file_hash(directory / 'manifest.json') != bundle['dataset']['manifest_sha256']:
        raise ValueError('dataset differs from the frozen trained source')
    value = {'schema_version':1,'model_id':model_id,'model_manifest_sha256':record['manifest_sha256'],
        'dataset_manifest_sha256':bundle['dataset']['manifest_sha256'],
        'config':cfg,'configuration_sha256':file_hash(configuration),
        'evaluator_sha256':file_hash(__file__),
        'test_access':'Explicit Stage 13 offline evaluation only; backend live/test isolation remains enforced'}
    path = Path(output) / 'frozen_evaluation.json'
    if path.exists():
        previous = json.loads(path.read_text())
        if {k:v for k,v in previous.items() if k != 'frozen_utc'} != value:
            raise ValueError('frozen evaluation changed; no repeated test-driven configuration allowed')
        return previous
    value['frozen_utc'] = utc_now()
    atomic_json(path,value)
    store.audit('stage13-evaluation','evaluation_frozen',value,subject_id=model_id)
    return value


def episode_bootstrap(labels, probabilities, episodes, seed, repetitions):
    """Stratify classes and resample whole episodes, retaining within-episode correlation."""
    episodes = np.asarray(episodes)
    by_class = {c:sorted(set(episodes[labels == c])) for c in CLASS_ORDER}
    if min(map(len,by_class.values())) < 2:
        return {'estimated':False,'reason':'Fewer than two independent episodes per class'}
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(repetitions):
        chosen = [e for c in CLASS_ORDER for e in rng.choice(by_class[c],size=len(by_class[c]),replace=True)]
        indices = np.concatenate([np.flatnonzero(episodes == e) for e in chosen])
        values.append(classification(labels[indices],probabilities[indices])['macro_f1'])
    return {'estimated':True,'unit':'whole episodes; stratified by class','repetitions':repetitions,
        'seed':seed,'macro_f1_95_percentile_interval':np.quantile(values,[.025,.975]).tolist(),
        'limitation':'Only two held-out episodes per class, sharing one family; interval does not represent broad network/fault diversity.'}


def summarize_predictions(labels, probabilities, episodes, decisions, cfg):
    labels, probabilities, episodes = np.asarray(labels), np.asarray(probabilities), np.asarray(episodes)
    unique = sorted(set(episodes))
    episode_y, episode_p = [], []
    for e in unique:
        selected = episodes == e
        if len(set(labels[selected])) != 1:
            raise ValueError('episode labels disagree')
        episode_y.append(labels[selected][0])
        episode_p.append(probabilities[selected].mean(axis=0))
    supported = np.asarray([d['status'] == 'supported' for d in decisions])
    return {'windows':len(labels),'episodes':len(unique),'class_window_counts':dict(Counter(labels.tolist())),
        'class_episode_counts':dict(Counter(episode_y)),
        'window_classification':classification(labels,probabilities),
        'episode_classification':classification(np.asarray(episode_y),np.asarray(episode_p)),
        'episode_prediction':'Mean frozen class probabilities across each episode; one vote per episode',
        'calibration':{**reliability(labels,probabilities),
            'log_loss':float(-np.mean(np.log(np.clip(probabilities[np.arange(len(labels)),
                [CLASS_ORDER.index(label) for label in labels]],1e-15,1))))},
        'abstention':{'coverage_fraction':float(supported.mean()),'unknown_fraction':float(1-supported.mean()),
            'status_counts':dict(Counter(d['status'] for d in decisions)),
            'supported_metrics':classification(labels[supported],probabilities[supported]) if supported.any() else None},
        'incident_detection':detection(labels,np.asarray([d.get('incident',False) for d in decisions])),
        'uncertainty':episode_bootstrap(labels,probabilities,episodes,cfg['seed'],cfg['bootstrap_repetitions'])}


def evaluate_test(store, frozen, settings, output):
    output = Path(output)
    if frozen['evaluator_sha256'] != file_hash(__file__):
        raise ValueError('evaluator changed after freeze')
    registry = BundleRepository(store)
    record = registry.inspect(frozen['model_id'])
    if record['manifest_sha256'] != frozen['model_manifest_sha256']:
        raise ValueError('model changed after freeze')
    bundle = registry.load(frozen['model_id'])
    directory = store.path.parent / 'datasets' / bundle['dataset']['batch_id']
    if file_hash(directory/'manifest.json') != frozen['dataset_manifest_sha256']:
        raise ValueError('dataset changed after freeze')
    manifest = json.loads((directory/'manifest.json').read_text())
    for name,info in manifest['files'].items():
        if file_hash(directory/name) != info['sha256']:
            raise ValueError('dataset artifact changed: '+name)
    splits = json.loads((directory/'splits.json').read_text())
    if any(set(splits['test'][field]) & set(splits[p][field]) for p in ('train','validation')
           for field in ('window_ids','episode_ids','family_ids')):
        raise ValueError('held-out split overlap')
    with store.connection() as db:
        batch = json.loads(db.execute('SELECT payload_json FROM dataset_batches WHERE batch_id=?',(manifest['batch_id'],)).fetchone()[0])
        windows = []
        for wid in splits['test']['window_ids']:
            row = db.execute('SELECT w.payload_json,m.window_hash,m.partition FROM telemetry_windows w '
                'JOIN dataset_members m USING(window_id) WHERE w.window_id=?',(wid,)).fetchone()
            window = json.loads(row[0])
            if row[2] != 'test' or digest(window) != row[1]:
                raise ValueError('held-out membership or observation changed')
            windows.append(window)
    raw = ordered_probabilities(bundle['classifier'],feature_array([w['features'] for w in windows]))
    probabilities = ordered_probabilities(bundle['calibrator'],feature_array([w['features'] for w in windows])) if bundle['calibrator'] is not None else raw
    predictions = []
    # The label and injector tables are deliberately read only AFTER predictions
    # have been saved. No truth is passed to infer, rules or localization.
    for episode in splits['test']['episode_ids']:
        with store.connection() as db:
            ids = {r[0] for r in db.execute('SELECT window_id FROM dataset_members WHERE episode_id=? AND partition=?',(episode,'test'))}
        selected = sorted((i for i,w in enumerate(windows) if w['window_id'] in ids),key=lambda i:windows[i]['start_monotonic_s'])
        alerts = evaluate([windows[i] for i in selected],settings.telemetry,settings.objective)
        for i,alert in zip(selected,alerts,strict=True):
            w = windows[i]
            decision = infer(bundle,w,settings.telemetry,settings.objective,baseline=alert)
            location = localize(w,batch['definition'],observed_samples(store,w))
            predictions.append({'index':i,'window_id':w['window_id'],'episode_id':episode,
                'at_utc':w['at_utc'],'decision':decision,'rule_baseline':alert,'localization':location})
    predictions.sort(key=lambda r:r['index'])
    saved = {'model_id':bundle['model_id'],'split':'test','topology_switches':len(batch['definition']['switches']),
        'measurement_source':'Measured main dataset; frozen offline replay','predictions':predictions}
    atomic_json(output/'test_predictions.json',saved)
    labels = {r['window_id']:r for r in map(json.loads,(directory/'labels.jsonl').read_text().splitlines())}
    y = np.asarray([labels[w['window_id']]['label'] for w in windows])
    episodes = [p['episode_id'] for p in predictions]
    results = summarize_predictions(y,probabilities,episodes,[p['decision'] for p in predictions],frozen['config'])
    results['raw_classifier'] = classification(y,raw)
    results['rule_baseline'] = detection(y,np.asarray([p['rule_baseline']['status']=='alert' for p in predictions]))
    outcomes, delays = [], []
    for episode in sorted(set(episodes)):
        ep_predictions = [p for p in predictions if p['episode_id']==episode]
        with store.connection() as db:
            attempt = json.loads(db.execute("SELECT payload_json FROM dataset_attempts WHERE episode_id=? AND state='completed'",(episode,)).fetchone()[0])
            truth_row = db.execute('SELECT payload_json FROM ground_truth WHERE run_id=?',(attempt['main_traffic']['run_id'],)).fetchone()
            truth = json.loads(truth_row[0]) if truth_row else {}
        expected = truth.get('intended_location')
        detected = next((p for p in sorted(ep_predictions,key=lambda p:p['at_utc']) if p['decision'].get('incident')),None)
        start = truth.get('activated_utc')
        available = None
        if detected:
            observed = windows[detected['index']]
            with store.connection() as db:
                rows = db.execute('SELECT payload_json FROM telemetry_samples WHERE sample_id IN ('+
                    ','.join('?' for _ in observed['sample_ids'])+')',observed['sample_ids']).fetchall()
            stamps = [json.loads(r[0]).get('available_utc',json.loads(r[0])['at_utc']) for r in rows]
            available = max([observed['at_utc'],*stamps],key=datetime.fromisoformat)
        delay = {'episode_id':episode,'fault_start_utc':start,'detected_window_utc':detected['at_utc'] if detected else None,
            'window_replay_delay_ms':(datetime.fromisoformat(detected['at_utc'])-datetime.fromisoformat(start)).total_seconds()*1000 if detected and start and truth.get('fault_label')!='healthy' else None,
            'evidence_available_utc':available,
            'evidence_availability_replay_delay_ms':(datetime.fromisoformat(available)-datetime.fromisoformat(start)).total_seconds()*1000 if available and start and truth.get('fault_label')!='healthy' else None,
            'online_detection_delay_ms':None,'source':'Offline replay; observation-window and recorded evidence-availability times, not an actual online detector timestamp'}
        delays.append(delay)
        for p in ep_predictions:
            status,candidates = p['localization']['status'],p['localization']['candidate_set']
            if truth.get('fault_label') == 'healthy':
                positive = any(r['score']>0 for r in p['localization']['ranking'])
                outcome = 'incorrect' if positive and status=='ranked' else 'ambiguous' if positive else 'abstained'
            else:
                outcome = ('truth_unavailable' if not expected else 'ambiguous' if status=='ambiguous' else
                    'abstained' if status!='ranked' else 'correct' if expected in candidates else 'incorrect')
            outcomes.append({'window_id':p['window_id'],'episode_id':episode,'outcome':outcome,
                'truth_class':truth.get('fault_label'),
                'contains_intended_location':expected in candidates if expected else None})
    results.update(split='test',model_id=bundle['model_id'],probability_status='calibrated' if bundle['calibrator'] is not None else 'raw',
        topology_switches=len(batch['definition']['switches']),measurement_source=saved['measurement_source'],
        prediction_sha256=file_hash(output/'test_predictions.json'),
        localization={'method':'observed_link_heuristic_v1; separate from trained classifier',
            'window_counts':dict(Counter(o['outcome'] for o in outcomes)),'cases':outcomes},
        detection_delays=delays,inference_latency_ms={key:float(value) for key,value in
            [('mean',np.mean([p['decision']['inference_ms'] for p in predictions])),
             ('p95',np.quantile([p['decision']['inference_ms'] for p in predictions],.95))]},
        limitations=['Correlated windows; ten held-out episodes from five families only.',
            'Validation selected the model, calibration and anomaly threshold; validation scores are development results.',
            'Online detection delay unavailable; replay window delay reported separately. No test tuning.'])
    atomic_json(output/'held_out_metrics.json',results)
    store.audit('stage13-evaluation','held_out_evaluation_completed',{'model_id':bundle['model_id'],
        'prediction_sha256':results['prediction_sha256'],'windows':len(windows)},subject_id=bundle['model_id'])
    return results
