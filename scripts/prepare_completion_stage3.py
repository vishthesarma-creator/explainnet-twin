"""Write-once prospective protocol/configuration. Does not start laboratory work."""
import hashlib
import json
import socket
import sqlite3
import urllib.request
from collections import Counter
from pathlib import Path

from explainnet.application_profiles import ROOT
from explainnet.completion_protocol import SEED, VERSION, make_completion_schedule
from explainnet.dataset_contracts import digest
from explainnet.recovery_spec import POLICY, POLICY_HASH
from explainnet.storage import utc_now
from explainnet.topology.spec import scale_definition

OUT = ROOT/'artifacts/completion_stage3'


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'protocol.json').exists():
        print('Prospective protocol already exists; not overwritten'); return
    prior = json.loads((ROOT/'artifacts/completion_stage2_validation.json').read_text())
    assert prior['preservation_all_pass'] and prior['authoritative_final_software'][0]['failures']=='0'
    for port in [38223,43989]:
        c=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/lab/control',timeout=10))
        assert not c['auto_enabled'] and not c.get('active_workflow_id') and not c.get('unsettled_action_ids')
    old=json.loads((ROOT/'config/datasets/expansion_v1.json').read_text())
    compact=json.loads((ROOT/'config/datasets/main_v1.json').read_text())
    signature=lambda e:digest({k:v for k,v in e['scenario'].items() if k not in {'seed','measurement_s','warmup_s'}})
    old_signatures={signature(e) for e in compact['episodes']}
    expansion_overlap=len({signature(e) for e in old['episodes']} & old_signatures)
    for pilot,name in [(True,'pilot_schedule.json'),(False,'schedule.json')]:
        data=make_completion_schedule(pilot).model_dump()
        (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
    schedule=json.loads((OUT/'schedule.json').read_text())
    assert not {signature(e) for e in schedule['episodes'] if e['partition']=='test'} & old_signatures
    data=Path('/home/USER/.local/share/explainnet/completion3_v1/data')
    data.mkdir(parents=True,exist_ok=True)
    runtime=OUT/'runtime'; runtime.mkdir(exist_ok=True)
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    cfg={'schema_version':1,'data_dir':str(data),'runtime_dir':str(data.parent/'run'),
        'agent_socket':f'/run/explainnet-stage6-{port}/agent.sock','host':'127.0.0.1','port':port,
        'topology_file':str(ROOT/'config/topology.yaml'),'traffic_profiles_file':str(ROOT/'config/traffic.yaml'),
        'objective':{'max_rtt_ms':20,'max_loss_fraction':.02},
        'dataset_artifact_dir':str(OUT/'dataset'),'telemetry':schedule['telemetry']}
    (runtime/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    topology=json.loads((ROOT/'config/topologies/scale_5_v1.json').read_text())
    for n in [5,10,15]:
        (OUT/f'topology_{n}.json').write_text(json.dumps(scale_definition(topology,n),indent=2)+'\n')
    database=Path('/home/USER/.local/share/explainnet/stage13/data/explainnet.sqlite3')
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        counts=dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition'))
    protocol={'schema_version':1,'version':VERSION,'declared_utc':utc_now(),'seed':SEED,
        'working_target':3600,'episodes':600,'families':60,'windows_per_episode':6,
        'class_counts':{c:720 for c in ['healthy','saturation','loss','latency','qos']},
        'partitions_windows':{'train':2400,'validation':600,'test':600},
        'partitions_episodes':dict(Counter(e['partition'] for e in schedule['episodes'])),
        'historical_corpus':{'counts':counts,'examined_test':'historical only; never new confirmatory test',
            'expansion_v1_episodes':len(old['episodes']),'expansion_v1_target':sum(e['target_windows'] for e in old['episodes']),
            'expansion_compact_recipe_overlap':expansion_overlap,
            'reuse':'Preserve the complete360-window cohort separately. New held-out joint recipes/seeds/provenance are disjoint; new train explicitly includes intended8MbpsUDP1200 demonstration domain.'},
        'collection':{'config':str(runtime/'config.json'),'sequential':True,'pilot_required':True,
            'pilot_counts':{'episodes':5,'windows':10},'measurement_s':100,'baseline_recovery_s':12,
            'sample_interval_s':2,'window_s':10,'minimum_coverage_fraction':.65,'minimum_probe_transmissions':6,
            'maximum_cpu_memory_fraction':.85,'maximum_attempts':2,'identical_failure_policy':'Stop on two identical failures; no automatic re-amendment',
            'checkpoint':'<data_dir>/datasets/BATCH/checkpoint.json','final_audit_required':True},
        'training':{'profile':'completion3','RF_candidates':3,'RF_trees':160,'group_CV_folds':4,
            'selection':'validation raw macro-F1, first tie; validation calibration/IF threshold are development only',
            'IF':'160 trees on healthy training only','confidence':.70,'margin':.15,
            'SHAP_background':'24 deterministic estimator-fit training rows, embedded before immutable publication',
            'test_access':'Only after model/background/protocol/evaluator/source freeze; never backend fitting'},
        'primary_comparisons':{'independent_sources_per_approach':3,'fault':'latency','approaches':['impaired_no_change','independent_no_twin','trained_twin'],
            'workload':{'critical_bps':8000000,'bulk_bps':5000000,'protocol':'udp','packet_size':1200},
            'no_twin':'Choose independently from measured service/topology before any twin result; shadow qualification excluded from intrinsic decision clock',
            'no_XAI':'SHAP is post-hoc, not a selection input. Same frozen model/data/policy; compare identical predictions/choices and measured explanation overhead. No invented user study.',
            'actuation':'Common existing trained/model/ownership/service/fidelity/rollback gates; failed qualification yields recommendation/twin-only evidence'},
        'recovery':{'policy':POLICY,'policy_hash':POLICY_HASH,'fidelity':'unchanged fidelity_v1; no failed repeat discarded',
            'repairs':2,'repetitions':2,'hypotheses':2,'trial_duration_s':15,'workflow_timeout_s':900,
            'known_open_prerequisites':prior['per_fault'],'original_families':['reroute'],'automatic_repair':False},
        'scale':{'sizes':[5,10,15],'conditions':['healthy','latency'],'independent_episodes_per_condition':3,
            'domain':'Train5-switch only. Larger-topology predictions exploratory; transfer is not qualified by construction alone.',
            'maximum_live_twins':1,'minimum_available_memory_bytes':1073741824},
        'metrics':{'classification':['per-class precision recall F1','macro-F1','confusion matrix','RF argmax versus supported coverage'],
            'anomaly':['sensitivity','healthy false alert fraction','ROC AUC','average precision and prevalence'],
            'calibration':['five-class Brier sum0..2','log loss','ECE','reliability bins'],
            'uncertainty':'500 seeded class-stratified whole-episode and whole-family bootstrap repetitions',
            'SHAP':['matching model/window','raw RF additivity','neighboring-window top-feature stability','latency'],
            'localization':['correct','incorrect','ambiguous','abstained','truth unavailable'],
            'clocks':['onset-detection','observation-ready diagnosis/explanation','snapshot/reconstruction','candidate testing','eligible recommendation','application','verification','onset-outcome'],
            'targets':{'macro_F1':.85,'integrated_decision_ms_strictly_less_than':10000}},
        'cancellation':'Typed dataset-cancel; finish in-flight operation, scoped reset/stop. No global cleanup.',
        'preservation_checks':prior['preservation']}
    protocol['files']={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['schedule.json','pilot_schedule.json','topology_5.json','topology_10.json','topology_15.json']}
    protocol['protocol_hash']=digest(protocol)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    (OUT/'evaluation_config.json').write_text(json.dumps({'schema_version':1,'evaluation_id':VERSION,'seed':SEED,
        'training_profile':'completion3','bootstrap_repetitions':500,'test_tuning_permitted':False,
        'protocol_hash':protocol['protocol_hash']},indent=2)+'\n')
    print(json.dumps({'protocol_hash':protocol['protocol_hash'],'episodes':600,'target':3600,'historical_recipe_overlap':expansion_overlap,'config':cfg}))


if __name__=='__main__': main()
