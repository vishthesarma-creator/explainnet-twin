"""Read-only stage-2 evidence collation; never starts a lab, fits, or scores tests."""
import hashlib
import json
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/completion_stage2'
MODEL = 'm20261016T074751_a92c0db8f44e'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected(value, keys):
    return {k: value.get(k) for k in keys}


def measurement(window):
    return selected(window, ['window_id','run_id','instance_id','at_utc','duration_s','complete','inference_ready',
        'start_monotonic_s','end_monotonic_s','feature_schema_version','feature_schema_hash','data_quality','features','per_flow','context'])


def finding(diag):
    return selected(diag, ['model_id','window_id','mode','status','predicted_class','confidence','margin',
        'raw_probabilities','calibrated_probabilities','probability_status','class_order','anomaly_score',
        'anomaly_threshold','anomalous','service_contract_version','service_evidence','unsupported_features',
        'reasons','freshness','inference_ms'])


def explanation(value):
    return selected(value, ['explanation_id','model_id','window_id','diagnosis_id','incident_id','status','reason',
        'model_manifest_hash','background_recipe','background_version','algorithm_version','output_scale',
        'base_value','underlying_model_output','reconstructed_output','additivity_absolute_error','contributions','top_features',
        'plain_language','runtime_ms','created_utc','completed_utc'])


def case_summary(path, db):
    case = read(path); w = case.get('workflow') or {}; exp = w.get('candidate_result') or {}
    summary = selected(case, ['name','reference_fault','mode','instance_id','model_id','model_manifest_sha256',
        'state','error','finished','started_utc','ended_utc','elapsed_ms','workflow_id',
        'automatic_explicitly_requested','ground_truth_used_for_inference','source_episode_unit','trial_unit','cleanup'])
    summary['source_artifact'] = str(path.relative_to(ROOT))
    summary['source_sha256'] = sha(path)
    summary['preliminary_diagnosis'] = finding(case.get('trained_observation', {}).get('diagnosis') or {})
    summary['preliminary_explanation'] = explanation(case.get('trained_observation', {}).get('explanation') or {})
    summary['observation'] = measurement(case.get('observation') or {})
    summary['workflow'] = selected(w, ['workflow_id','state','error','reasons','incident_id','snapshot_id','experiment_id',
        'elapsed_ms','timings_ms','lifetime_budget','measurement_protocol','service_requirements','rejection_details'])
    summary['workflow']['diagnosis'] = finding(w.get('diagnosis') or {})
    summary['workflow']['explanation'] = explanation(w.get('explanation') or {})
    summary['workflow']['pre_windows'] = [measurement(p) for p in w.get('pre_windows', [])]
    if w.get('workflow_id'):
        actual = db.execute('SELECT state FROM recovery_workflows WHERE workflow_id=?',(w['workflow_id'],)).fetchone()
        summary['workflow']['final_backend_state'] = actual[0] if actual else None
    if w.get('snapshot_id'):
        row = db.execute('SELECT payload_json FROM twin_snapshots WHERE snapshot_id=?', (w['snapshot_id'],)).fetchone()
        if row:
            s = json.loads(row[0])
            summary['snapshot'] = selected(s, ['schema_version','snapshot_id','snapshot_hash','at_utc','expires_utc',
                'original_instance_id','service_requirements','measurement_protocol','provenance','localization','baseline','diagnosis'])
            summary['snapshot']['window'] = measurement(s['window'])
    # Recover the unsuitable captured observation even if the old coordinator
    # refused before appending it to pre_windows. Select only this source episode.
    rows = db.execute('SELECT payload_json FROM telemetry_windows WHERE instance_id=? ORDER BY end_monotonic_s',
        (case['instance_id'],)).fetchall()
    summary['source_capture_windows'] = [measurement(value) for row in rows
        if (value := json.loads(row[0])).get('run_id','').startswith('t9')]
    summary['unsuitable_source_windows'] = [value for value in summary['source_capture_windows']
        if not value.get('inference_ready') or any(value['features'].get(k) is None for k in ['rtt_mean_ms','rtt_p95_ms'])]
    summary['experiment'] = selected(exp, ['operation_id','state','reasons','error','request','policy_version','policy_hash',
        'lineage','hypotheses','unresolved_hypotheses','untried_directions','retained_ambiguity','randomized_order',
        'seed','candidates','rejected','feasible_repair_count','failures','twin_construction_ms','elapsed_ms','cleanup','rejection_details'])
    summary['experiment']['recommendation'] = exp.get('recommendation')
    summary['experiment']['trials'] = [selected(t, ['trial_id','candidate_id','hypothesis_id','repetition','family',
        'state','error','reasons','reset_ms','reset','capture_id','original_unchanged','fidelity',
        'candidate_application_ms','paired_capture_rpc_ms','capture_elapsed_ms','materialization_ms','elapsed_ms'])
        | {'original': measurement(t.get('original_window') or {}), 'twin':measurement(t.get('window') or {})}
        for t in exp.get('trials', [])]
    action = case.get('original_action') or {}
    summary['original_action'] = selected(action, ['action_id','state','automated','error','rollback_error','degraded',
        'lineage','elapsed_ms','verification_ms','logical_diff','connectivity','rollback','undo'])
    if action.get('action_id'):
        actual = db.execute('SELECT state FROM lab_action_state WHERE action_id=?',(action['action_id'],)).fetchone()
        summary['original_action']['final_backend_state'] = actual[0] if actual else None
    summary['original_action']['post_windows'] = [selected(p, ['evaluation','predicted_rtt_mean_ms','observed_rtt_mean_ms'])
        | {'window':measurement(p['window'])} for p in action.get('post_windows', [])]
    summary['original_action']['application'] = selected(action.get('application') or {},
        ['application_started_monotonic_s','application_ended_monotonic_s','application_elapsed_ms','state','logical_diff'])
    disruption = action.get('transient_disruption') or {}
    summary['original_action']['transient_disruption'] = selected(disruption, ['status','reason','metrics','resolution'])
    summary['undo'] = selected(case.get('undo') or {}, ['state','action_id','error','undo'])
    return summary


def get(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def main():
    profile = read(ROOT / 'artifacts/stage6/runtime/config.json')
    data = Path(profile['data_dir']) if 'data_dir' in profile else Path('/home/USER/.local/share/explainnet/stage13/data')
    database = data / 'explainnet.sqlite3'
    db = sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True)
    model = data / 'models' / MODEL
    manifest, validation = read(model/'manifest.json'), read(model/'validation_report.json')
    prior = read(ROOT/'artifacts/completion_stage1_validation.json')
    preservation = []
    for row in prior['preservation']:
        p = Path(row['file'])
        if not p.is_absolute(): p = ROOT / str(p).replace('\\','/')
        preservation.append({'file':str(p), 'before_sha256':row['sha256'], 'after_sha256':sha(p),
            'unchanged':sha(p) == row['sha256']})
    for name, expected in read(OUT/'frozen_evidence_hashes.json').items():
        p = ROOT / name.replace('\\','/')
        preservation.append({'file':name,'before_sha256':expected,'after_sha256':sha(p),'unchanged':sha(p)==expected,
            'access':'bytes hashed only; no test scoring/interpretation'})
    backgrounds = [selected(json.loads(r[0]), ['version','model_id','partition','scope','window_ids','groups',
        'episodes','content_hash','selection','seed','limit']) for r in db.execute(
        'SELECT payload_json FROM explanation_backgrounds WHERE model_id=?', (MODEL,))]
    assert all(b['partition'] == 'train' and set(b['groups']) <= set(validation['data_coverage']['estimator_fit_groups'])
        for b in backgrounds)
    attempts = []
    for group in ['main','verified']:
        for name in ['healthy','latency','loss','saturation','qos','automatic_latency']:
            p = OUT / group / (name+'.json')
            if p.exists(): attempts.append(case_summary(p, db) | {'verification_set':group})
    tests = []
    for p in OUT.glob('*.xml'):
        suites = ET.parse(p).getroot()
        for s in suites.iter('testsuite'):
            tests.append({'artifact':str(p.relative_to(ROOT)), **s.attrib})
    native_history = read(ROOT/'artifacts/recovery_validation_report.json')
    complete = all(any(a['verification_set']=='verified' and a['name']==name and a['finished'] for a in attempts)
        for name in ['healthy','latency','loss','saturation','qos'])
    assisted = next((a for a in attempts if a['verification_set']=='verified' and a['name']=='latency'), {})
    if assisted.get('original_action',{}).get('state') == 'succeeded':
        complete &= any(a['verification_set']=='verified' and a['name']=='automatic_latency' and a['finished'] for a in attempts)
    report = {'schema_version':1,'stage':'completion_prompt_2','at_utc':datetime.now(UTC).isoformat(),
        'status':'implemented_with_open_qualification_blockers' if complete else 'verification_in_progress',
        'training':False,'new_dataset_campaign':False,
        'sealed_test_scoring':False,'observed_only_fallback':False,'original_review_targets_not_closed':True,
        'profiles':{key:get(f'http://127.0.0.1:{port}/v1/config') | {'control':get(f'http://127.0.0.1:{port}/v1/lab/control'),
            'models':get(f'http://127.0.0.1:{port}/v1/models')} for key,port in [('trained',38223),('observed-only',43989)]},
        'prerequisite_report':'artifacts/completion_stage1_validation.json', 'prerequisite_software':tests,
        'preservation':preservation,'preservation_all_pass':all(p['unchanged'] for p in preservation),
        'frozen_model':{'model_id':MODEL,'feature_order':manifest['feature_order'],'feature_units':manifest['feature_units'],
            'feature_schema_hash':manifest['feature_schema_hash'],'class_order':manifest['class_order'],
            'anomaly_threshold':manifest['anomaly_threshold'],'policy':manifest['policy'],
            'hashes':{name:sha(model/name) for name in ['bundle.joblib','manifest.json','validation_report.json']},
            'development_validation_anomaly':validation['validation']['anomaly'],
            'development_original_policy_abstention':validation['validation']['abstention'],
            'development_threshold_selection':validation['validation']['threshold_selection'],
            'preprocessing':validation['preprocessing'],'training_only_backgrounds':backgrounds},
        'attempts':attempts,'units':{'source_episode':'one independent original construction per set/condition',
            'trial':'fresh twin construction measurement; two repeats per candidate/hypothesis; not independent packets'},
        'historical_rollback':{'artifact':'artifacts/recovery_validation_report.json','mode':'observed-only; no compatible active model then',
            'not_trained_acceptance':True,'cases':{k:selected(native_history['summary'][k],
                ['state','directory','workflow_id','action_id','error']) for k in ['verification_rollback','partial_rollback','restart_reconciled']}},
        'investigations':{name:str((OUT/name).relative_to(ROOT)) for name in ['historical_fidelity.json',
            'investigation_legacy_setup_failure.json','investigation_legacy.json','investigation_warm.json',
            'qos_restore_inspection.json','verified/protocol_amendment.json','verified/sampling_bound_erratum.json',
            'native_capture_timings.json','reconciliation/qos_scoped_teardown.json']},
        'limitations':['One new source episode per condition per declared implementation set, not final effectiveness statistics',
            'Legacy/warm historical-outlier investigation has two controls per phase; no reproduced physical cause',
            'Original action allowlist remains reroute only','No full corpus/ablation/5-10-15-switch campaign or redesigned dashboard',
            'Inference latency alone is not the integrated less-than-ten-second decision target']}
    report['source_changes_from_checkpoint'] = [name for name, expected in read(OUT/'checkpoint.json')['files'].items()
        if (ROOT/name).exists() and sha(ROOT/name) != expected]
    new_sources = ['src/explainnet/service_requirements.py','src/explainnet/rejection_details.py',
        'config/service_requirements_v2.json','config/recovery_policy_v2.json','config/workflow_policy_v2.json',
        'scripts/completion_stage2.py','scripts/completion_stage2_investigate.py','scripts/record_completion_stage2.py',
        'scripts/record_stage2_native.py','scripts/check_completion_stage2_reads.py','scripts/check_completion_stage2_final.py',
        'tests/test_completion_stage2.py','docs/SERVICE_REQUIREMENTS.md','docs/COMPLETION_TRACEABILITY.md','docs/COMPLETION_STAGE2.md']
    report['source_version'] = {'recoverable_checkpoint':'artifacts/completion_stage2/checkpoint.json',
        'native_deployment_declaration':'artifacts/completion_stage2/verified/protocol_amendment.json',
        'final_file_sha256':{name:sha(ROOT/name) for name in sorted(set(report['source_changes_from_checkpoint']+new_sources))},
        'post_packet_episode_changes':'Additional timing fields, unsuitable-window retention, low-demand consistency fixture/correction (all actual critical demands were >=2Mbps), report/status helpers; final software tests and idle ordinary API/UI reload completed.'}
    report['authoritative_final_software'] = [t for t in tests if t['artifact'].endswith('final_acceptance.xml')]
    for key, name in [('final_state','final_state.json'),('dashboard_reads','dashboard_reads.json')]:
        path = OUT/name
        if path.exists(): report[key] = read(path)
    report['deployment_scope'] = 'Trained owner/API/UI deployed; unrelated observed-only owner/backend not restarted and retains its earlier loaded workflow_v1 policy.'
    native_times = OUT/'native_capture_timings.json'
    if native_times.exists(): report['native_capture_timings'] = read(native_times)
    per_fault = {}
    for name in ['healthy','latency','loss','saturation','qos','automatic_latency']:
        matches = [a for a in attempts if a['name']==name]
        if not matches: continue
        last = matches[-1]; e = last['experiment']; trials = e['trials']
        per_fault[name] = {'latest_set':last['verification_set'],'state':last['state'],
            'diagnosis':last['workflow']['diagnosis'] if last['workflow']['diagnosis'].get('status') else last['preliminary_diagnosis'],
            'explanation':last['workflow']['explanation'] if last['workflow']['explanation'].get('status') else last['preliminary_explanation'],
            'control_statuses':[t['fidelity']['status'] for t in trials if t.get('fidelity')],
            'feasible_repairs':len(e.get('candidates') or [])-1 if e.get('candidates') else None,
            'measured_repair_candidates':len({t['candidate_id'] for t in trials if t['family']!='no_change' and t['state']=='measured'}),
            'measured_repair_trials':sum(t['family']!='no_change' and t['state']=='measured' for t in trials),
            'recommendation_state':(e.get('recommendation') or {}).get('status'),
            'original_action_state':last['original_action'].get('state'),'post_windows':len(last['original_action']['post_windows']),
            'final_backend_action_state':last['original_action'].get('final_backend_state'),
            'rejection_details':last['workflow'].get('rejection_details'),'error':last['workflow'].get('error') or last.get('error'),
            'reasons':last['workflow'].get('reasons'),'historical_attempts':len(matches)}
    report['per_fault'] = per_fault
    dest = ROOT/'artifacts/completion_stage2_validation.json'
    dest.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'artifact':str(dest),'attempts':len(attempts),'preservation':report['preservation_all_pass'],
        'per_fault':{k:selected(v,['state','control_statuses','measured_repair_candidates','original_action_state','error'])
            for k,v in per_fault.items()}}, indent=2))


if __name__ == '__main__': main()
