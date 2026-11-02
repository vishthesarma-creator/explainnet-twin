"""Compact read-only runtime inspection; writes only requested stage-3 reports."""
import csv
import hashlib
import json
import sqlite3
import statistics
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from explainnet.application_profiles import ROOT
from explainnet.storage import utc_now

OUT=ROOT/'artifacts/completion_stage3'


def load(path, fallback=None):
    return json.loads(path.read_text()) if path.exists() else fallback


def record():
    protocol=load(OUT/'protocol.json'); cfg=load(OUT/'runtime/config.json')
    supervisor=load(OUT/'runtime/supervisor.json',{})
    pipeline=load(OUT/'pipeline.json',{})
    batches=[]; models=[];control=None
    database=Path(cfg['data_dir'])/'explainnet.sqlite3'
    if database.exists():
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
            for row in db.execute('SELECT payload_json FROM dataset_batches ORDER BY rowid'):
                b=json.loads(row[0]); bid=b['batch_id']; schedule=b['schedule']
                accepted=db.execute('SELECT count(*) FROM dataset_members WHERE batch_id=?',(bid,)).fetchone()[0]
                classes=dict(db.execute("SELECT json_extract(a.payload_json,'$.main_reset_receipt.laboratory_journal.configuration.kind'),count(*) "
                    "FROM dataset_members m JOIN dataset_attempts a USING(attempt_id) WHERE m.batch_id=? GROUP BY 1",(bid,)))
                attempts=[json.loads(r[0]) for r in db.execute("SELECT json_object('episode',episode_id,'state',state,'elapsed_s',json_extract(payload_json,'$.elapsed_s'),"
                    "'error',json_extract(payload_json,'$.error'),'rejected',json_array_length(json_extract(payload_json,'$.rejected_windows'))) FROM dataset_attempts WHERE batch_id=?",(bid,))]
                done=[a for a in attempts if a['state']=='completed']; durations=[a['elapsed_s'] for a in done if a['elapsed_s'] is not None]
                mean=statistics.mean(durations) if durations else None
                rejected=sum(a['rejected'] or 0 for a in attempts)
                manifest=load(Path(b.get('manifest_path') or '/nonexistent'),{})
                batches.append({'batch_id':bid,'purpose':schedule['purpose'],'state':b['state'],'phase':b.get('phase'),
                    'current_episode':b.get('current_episode'),'error':b.get('error'),'accepted_windows':accepted,
                    'expected_windows':sum(e['target_windows'] for e in schedule['episodes']),
                    'completed_episodes':len(done),'expected_episodes':len(schedule['episodes']),
                    'declared_families':len({e['family_id'] for e in schedule['episodes']}),'class_counts':classes,
                    'represented_families':db.execute('SELECT count(DISTINCT family_id) FROM dataset_members WHERE batch_id=?',(bid,)).fetchone()[0],
                    'represented_families_by_partition':dict(db.execute('SELECT partition,count(DISTINCT family_id) FROM dataset_members WHERE batch_id=? GROUP BY partition',(bid,))),
                    'failed_attempts':sum(a['state']=='failed' for a in attempts),'running_attempts':sum(a['state']=='running' for a in attempts),
                    'partitions':dict(db.execute('SELECT partition,count(*) FROM dataset_members WHERE batch_id=? GROUP BY partition',(bid,))),
                    'dataset_ready':bool(manifest.get('dataset_ready')),'rejected_windows':rejected,'steady_acceptance_fraction_of_all_windows':accepted/(accepted+rejected) if accepted+rejected else None,
                    'completed_attempt_fraction':len(done)/len(attempts) if attempts else None,
                    'mean_completed_episode_s':mean,'estimated_remaining_s':(len(schedule['episodes'])-len(done))*mean if mean else None,
                    'attempts':attempts,'manifest':b.get('manifest_path'),'schedule_hash':b['schedule_hash']})
            models=[{'model_id':r[0],'created_utc':r[1]} for r in db.execute('SELECT model_id,created_utc FROM model_bundles')]
            row=db.execute('SELECT payload_json FROM recovery_control WHERE singleton=1').fetchone()
            control=json.loads(row[0]) if row else None
    main=next((b for b in batches if b['purpose']=='expansion'),None)
    pilot=next((b for b in batches if b['purpose']=='pilot'),None)
    collection_start=pipeline.get('collection_started_monotonic_s')
    elapsed=time.monotonic()-collection_start if collection_start is not None else None
    if main and elapsed is not None and elapsed>=0 and main['completed_episodes']:
        cadence=elapsed/main['completed_episodes']
        main.update(collection_elapsed_monotonic_s=elapsed,observed_seconds_per_completed_episode_including_audit=cadence,
            estimated_remaining_s=(600-main['completed_episodes'])*max(cadence,main['mean_completed_episode_s'] or 0),
            ETA_limitation='Observed cadence includes elapsed current attempt/audits; expanding full audits, failures and shared host load can extend runtime.')
    if main and main['state']!='running':
        main.update(estimated_remaining_s=None,ETA_limitation='Campaign is stopped/blocked; no active completion ETA. Exhausted attempts require explicit protocol/quality reconciliation, not a blind restart.')
    state=pipeline.get('state') or ('blocked' if pilot and pilot['state'] in {'failed','canceled','interrupted'}
        else 'pilot_qualified' if pilot and pilot['state']=='completed' else 'pilot_running')
    frozen=load(OUT/'evaluation/pipeline_freeze.json')
    metrics=load(OUT/'evaluation/completion3_metrics.json')
    labs=load(OUT/'labs/report.json')
    preserved=[]
    for p in protocol['preservation_checks']:
        path=Path(p['file'].replace('\\','/'))
        if not path.is_absolute(): path=ROOT/path
        expected=p['before_sha256']
        preserved.append({'file':str(path),'unchanged':hashlib.sha256(path.read_bytes()).hexdigest()==expected})
    report={'schema_version':1,'stage':'completion_prompt_3','status':state,'at_utc':utc_now(),
        'protocol_hash':protocol['protocol_hash'],'protocol':'artifacts/completion_stage3/protocol.json',
        'dataset_ready':bool(main and main['state']=='completed' and main['accepted_windows']==3600 and main['dataset_ready']),
        'accepted_windows':main['accepted_windows'] if main else 0,'expected_windows':3600,
        'completed_episodes':main['completed_episodes'] if main else 0,'expected_episodes':600,
        'partitions':main['partitions'] if main else {},'dataset_audit':{'pilot':pilot,'cohort':main},
        'model_metadata':{'new_models':models,'frozen':frozen,'status':'frozen' if frozen else 'trained_pending_freeze' if models else 'pending complete audited corpus',
            'historical_active_model':'m20261016T074751_a92c0db8f44e; separate Stage13 store; not new-cohort acceptance'},
        'held_out_metrics':metrics,'baseline_results':labs.get('baseline_results') if labs else None,
        'scale_results':labs.get('scale_results') if labs else None,
        'per_fault':labs.get('per_fault') if labs else None,
        'summary':{'automatic_repair_enabled':control.get('auto_enabled') if control else None,'campaign_control':control,'pilot_windows_counted_toward_target':False,
            'new_test_opened':(OUT/'evaluation/test_access.json').exists(),
            'historical_assets_unchanged':all(p['unchanged'] for p in preserved),'pipeline':pipeline,
            'runtime':{k:supervisor.get(k) for k in ['state','supervisor_pid','api_pid','agent_pid','batch_id','error','errors']},
            'config':str(OUT/'runtime/config.json'),'api_port':cfg['port'],'data_store':cfg['data_dir']},
        'checks':{'preservation':preserved},
        'blockers':[],
        'limitations':['Historical examined cohort is separate; no old heldout tuning.',
            'Five-switch training does not establish10/15-switch model transfer.',
            'Within-source windows and trial repeats are correlated; independent episode/family counts are reported.',
            'Software fixtures are not packet evidence; pending metrics remain null.'],
        'reproduce':{'status':'.venv/bin/python scripts/status_completion_stage3.py',
            'pipeline':'wsl.exe -d Ubuntu -u root --cd "/path/to/user\\Desktop\\CN project" -- env PYTHONPATH=src /usr/bin/python3 scripts/completion_stage3_pipeline.py run --resume --detach',
            'cancel':'Typed dataset-cancel against the recorded configuration/batch; checkpoint and scoped cleanup required.'},
        'stage15_readiness':{'prompt4':report_complete(pipeline,main,metrics,labs)}}
    if not report['dataset_ready']:report['blockers'].append('Representative corpus incomplete or final dataset audit not ready; training/final-test gate stays closed.')
    if main and main.get('error'):report['blockers'].append('Collection stopped at '+str(main.get('current_episode'))+': '+str(main['error'])+'. Preserve failed attempts and maximum retry budget.')
    if metrics is None:report['blockers'].append('New frozen heldout metrics, calibration, IF ranking and SHAP/no-XAI results are pending.')
    elif metrics['window_classification']['macro_f1']<.85:report['blockers'].append('New heldout macro-F1 target0.85 was not met; no test-driven tuning.')
    if not labs or not labs.get('finished'):report['blockers'].append('Declared native baseline/fault/scale comparisons are not all terminal; pending work is not complete.')
    else:
        for fault in ['latency','loss','saturation','qos']:
            cases=[c for c in labs['cases'] if c['condition']==fault and c['switches']==5]
            qualified=[c for c in cases if c.get('complete_repeated_candidate_coverage') and c['control_fidelity'] and all(v['status']=='pass' for v in c['control_fidelity'])]
            if not qualified:report['blockers'].append(fault+': no new source passed required C0 and two-candidate measured coverage; exact nested refusals retained.')
            if not any(c['original_outcome']=='succeeded' for c in cases):
                report['blockers'].append(fault+': trained original-network recovery remains unqualified; twin-only/refused outcomes are not original success.')
        eligible=[c['timings']['eligible_recommendation_ms'] for c in labs['cases'] if c['timings'].get('eligible_recommendation_ms') is not None]
        if not eligible:report['blockers'].append('Integrated10-second target unverified: no eligible recommendation; fast refusal/inference is not a pass.')
        elif max(eligible)>=10000:report['blockers'].append('Integrated10-second target unmet; actual eligible recommendations require packet-testing time.')
        if any(c['switches']>5 and c['model_transfer'].startswith('outside') for c in labs['cases']):
            report['blockers'].append('10/15-switch trained-model transfer/original recovery is unqualified; construction/fidelity results are separate.')
    backend=load(OUT/'backend_checks.json')
    if backend and backend.get('status')!='passed':report['blockers'].append('New backend diagnosis/explanation compatibility has failures or pending explanations; trained gates remain.')
    report['software_verification']=[]
    for p in sorted(OUT.glob('*.xml')):
        try:
            suites=ET.parse(p).getroot().findall('testsuite')
            report['software_verification'].append({'artifact':p.name,'tests':sum(int(s.get('tests','0')) for s in suites),
                'failures':sum(int(s.get('failures','0')) for s in suites),'errors':sum(int(s.get('errors','0')) for s in suites),
                'elapsed_s':sum(float(s.get('time','0')) for s in suites),'evidence_type':'software fixtures, not packet efficacy',
                'authoritative_final':p.name in {'final_software.xml','bundle_and_evaluator_final.xml','final_binding_checks.xml','final_report_checks.xml'}})
        except (OSError,ValueError,ET.ParseError):
            report['software_verification'].append({'artifact':p.name,'status':'unreadable; unverified'})
    report['backend_checks']=backend
    report['interface_checks']=load(OUT/'interface_checks.json')
    report['controller_handoff']=load(OUT/'controller_handoff.json')
    review=load(OUT/'source_review.json')
    report['source_version']={'artifact':'artifacts/completion_stage3/source_review.json','snapshot_utc':review.get('at_utc'),
        'changed_from_checkpoint':review.get('changed_from_checkpoint'),'added_since_checkpoint':review.get('added_since_checkpoint')} if review else None
    previous={kind:load(ROOT/f'artifacts/completion_stage2/verified/{kind}.json',{}).get('elapsed_ms')
        for kind in ['healthy','latency','loss','qos','saturation']}
    report['runtime_estimates']={'collection_remaining_s':main.get('estimated_remaining_s') if main else None,
        'historical_stage2_source_episode_s':{k:v/1000 if v is not None else None for k,v in previous.items()},
        'source':'Preserved artifacts/completion_stage2/verified/<fault>.json elapsed_ms, real native sources including cleanup',
        'native_campaign_estimate_s':{'lower':5400,'upper':18000},
        'interpretation':'Planning range1.5–5h from historical~70s healthy and~671s successful latency sources; new model support, larger topology and added C0 affect duration. Not a Stage3 measured result. Native bound12h; train1h/evaluate2h bounds are not duration estimates.'}
    from explainnet.dataset_export import atomic_json
    atomic_json(ROOT/'artifacts/completion_stage3_validation.json',report)
    OUT.mkdir(exist_ok=True)
    with (OUT/'collection_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['batch_id','purpose','state','accepted_windows','expected_windows','completed_episodes','mean_completed_episode_s','estimated_remaining_s'])
        writer.writeheader(); writer.writerows({k:b.get(k) for k in writer.fieldnames} for b in batches)
    return report


def report_complete(pipeline,main,metrics,labs):
    return bool(pipeline.get('state')=='finished' and main and main['state']=='completed' and metrics and labs and labs.get('finished'))


if __name__=='__main__':
    r=record()
    from report_completion_stage3 import write_handover
    write_handover(r)
    compact=lambda b:{k:v for k,v in (b or {}).items() if k!='attempts'}
    print(json.dumps({'state':r['status'],'new_cohort':compact(r['dataset_audit']['cohort']),'pilot':compact(r['dataset_audit']['pilot']),
        'model_state':r['model_metadata']['status'],'preservation':r['summary']['historical_assets_unchanged']},indent=2))
