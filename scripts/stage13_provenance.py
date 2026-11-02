"""Post hoc dependency receipt and prospective guard; never score or tune test data."""
import hashlib
import json
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage13'
MODULES=('evaluation','model_policy','model_features','model_training','telemetry_monitor',
    'link_localization','model_contracts','model_bundle')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(settings):
    frozen=json.loads((OUT/'frozen_evaluation.json').read_text())
    dataset=Path(settings.data_dir)/'datasets/db5a15991774142f0a8ef871522face4d'
    model=Path(settings.data_dir)/'models'/frozen['model_id']
    paths=[ROOT/'src/explainnet'/(name+'.py') for name in MODULES]
    paths += [ROOT/'config/evaluation_stage13.json',dataset/'manifest.json',model/'manifest.json',
        model/'bundle.joblib',OUT/'frozen_evaluation.json',OUT/'held_out_metrics.json',
        OUT/'test_predictions.json',OUT/'backend_shap.json']
    return {'files':{str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):sha(p) for p in paths},
        'telemetry':settings.telemetry.model_dump(),'objective':settings.objective.model_dump(),
        'model_id':frozen['model_id'],'original_frozen_utc':frozen['frozen_utc']}


def verify(settings):
    path=OUT/'posthoc_provenance.json'
    if not path.exists():
        raise ValueError('Existing test results require the explicit post hoc provenance receipt before reuse')
    prior=json.loads(path.read_text())
    if prior['snapshot']!=snapshot(settings):
        raise ValueError('Scientific dependencies/settings/artifacts changed; original test results retained without rescoring')
    return prior


def main():
    settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
    path=OUT/'posthoc_provenance.json'
    if path.exists():
        verify(settings)
    else:
        atomic_json(path,{'schema_version':1,'recorded_utc':utc_now(),
            'kind':'post_hoc_dependency_receipt',
            'limitation':'Recorded after the October 16 test. Imported modules/settings were not all bound by the original freeze; this receipt does not retroactively claim they were frozen then.',
            'test_rescored':False,'test_tuning_permitted':False,'snapshot':snapshot(settings)})
    print(json.dumps({'status':'verified','test_rescored':False,'receipt':str(path)}))


if __name__=='__main__': main()
