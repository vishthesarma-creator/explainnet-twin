"""Safety regression fixtures for saved scientific evidence, not quality estimates."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


def script(name):
    spec=importlib.util.spec_from_file_location(name,Path('scripts')/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_saved_score_reuse_rejects_dependency_or_settings_change(tmp_path,monkeypatch):
    module=script('stage13_provenance')
    monkeypatch.setattr(module,'OUT',tmp_path)
    original={'files':{'model_policy.py':'old'},'objective':{'max_rtt_ms':100}}
    (tmp_path/'posthoc_provenance.json').write_text(json.dumps({'snapshot':original}))
    monkeypatch.setattr(module,'snapshot',lambda _: original)
    assert module.verify(None)['snapshot']==original
    monkeypatch.setattr(module,'snapshot',lambda _: original|{'objective':{'max_rtt_ms':200}})
    with pytest.raises(ValueError,match='changed'):
        module.verify(None)


def test_reuse_requires_intended_batch_profile_and_frozen_version(tmp_path,monkeypatch):
    module=script('evaluate_stage13')
    monkeypatch.setattr(module,'OUT',tmp_path)
    wrong={'model_id':'wrong','manifest':{'training_profile':'stage7','dataset':{'batch_id':module.BATCH}}}
    correct={'model_id':'correct','manifest_sha256':'trusted','manifest':{
        'training_profile':'stage13','dataset':{'batch_id':module.BATCH}}}
    repository=Mock()
    repository.list.return_value=[wrong,correct]
    monkeypatch.setattr(module,'BundleRepository',lambda _: repository)
    assert module.train(None,None)==correct
    repository.load.assert_called_once_with('correct')
    (tmp_path/'frozen_evaluation.json').write_text(json.dumps({'model_id':'other','model_manifest_sha256':'trusted'}))
    with pytest.raises(ValueError,match='frozen'):
        module.train(None,None)
    repository.list.return_value=[wrong]
    with pytest.raises(ValueError,match='dataset/profile'):
        module.train(None,None)
