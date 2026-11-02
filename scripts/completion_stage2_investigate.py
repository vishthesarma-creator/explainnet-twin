"""Predeclared two-control latency investigation; no candidate/original repair."""
import argparse
import time
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.app_launcher import request
from explainnet.application_profiles import PROFILES, ROOT
from explainnet.config import load_network, load_settings
from explainnet.dataset_export import atomic_json
from explainnet.network_contracts import (
    InstanceRequest,
    NetworkStartRequest,
    ProbeRequest,
    TrafficRunRequest,
    TrafficStartRequest,
    WorkloadProfile,
)
from explainnet.scenario_contracts import ScenarioStartRequest
from explainnet.storage import Store, utc_now
from explainnet.twin_contracts import (
    CaptureRequest,
    ConstructRequest,
    SnapshotRequest,
    TwinRequest,
    TwinResetRequest,
)
from explainnet.twin_fidelity import compare
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['legacy', 'warm'])
    args = parser.parse_args()
    cfg = load_settings(PROFILES['trained'][0])
    control = request(f'http://127.0.0.1:{cfg.port}/v1/lab/control')
    assert not control['active_workflow_id'] and not control['auto_enabled'] and not control.get('unsettled_action_ids')
    agent = AgentClient(cfg.agent_socket)
    assert not any(r['state'] == 'running' for r in agent.inventory()['instances']), 'canonical laboratory already in use'
    store = Store(cfg.database_path)
    twins = TwinService(store, agent, cfg.objective)
    definition = load_network(cfg.topology_file)
    name = 'c2i_' + args.phase + '_' + uuid4().hex[:8]
    twin_id = 'tw' + uuid4().hex[:16]
    path = ROOT / 'artifacts/completion_stage2' / ('investigation_' + args.phase + '.json')
    if path.exists():
        raise ValueError('declared investigation already attempted; preserve it, no favorable-sample retry')
    report = {'started_utc': utc_now(), 'phase': args.phase, 'instance_id': name,
        'purpose': 'fixed two fresh-runtime no-change controls; protocol investigation, not trained repair qualification',
        'planned_repeats': 2, 'duration_s': 15, 'attempts': [], 'cleanup': {}, 'hidden_inputs_in_snapshot': False}
    def save(): atomic_json(path, report)
    save()
    start = time.monotonic()
    instance = InstanceRequest(instance_id=name)
    try:
        agent.network_start(NetworkStartRequest(instance_id=name, definition=definition))
        report['connectivity'] = agent.network_probe(ProbeRequest(instance_id=name, source_host='h1', target_host='h3'))
        print('investigation ' + args.phase + ': nominal pilots', flush=True)
        profiles = [WorkloadProfile(profile_id=p, config_version='recovery_observation_v1', source_host=a, target_host=b,
            protocol='udp', offered_bps=rate, packet_size=1200, duration_s=180, warmup_s=3, stream_receiver=True)
            for p,a,b,rate in [('critical','h1','h3',8_000_000),('bulk','h2','h4',5_000_000)]]
        run = agent.traffic_start(TrafficStartRequest(instance_id=name, profiles=profiles))
        pilots = [twins.capture(name, 10)['window'] for _ in range(2)]
        baseline = {'window_ids': [w['window_id'] for w in pilots], 'definition_hash': digest(definition.model_dump())}
        _, policy = twins.pilot_reference(**baseline)
        agent.traffic_stop(TrafficRunRequest(instance_id=name, run_id=run['run_id']))
        scenario = {'schema_version':1,'config_version':'recovery_observation_v1','kind':'latency','severity':'high',
            'warmup_s':3,'measurement_s':900,'bidirectional':False,'variation_ms':0,'high_utilization':False,
            'traffic_profile':'moderate','critical_bps':8_000_000,'bulk_protocol':'udp','packet_size':1200,'seed':20261019}
        report['ground_truth'] = {'recipe': scenario, 'receipt': agent.scenario_start(ScenarioStartRequest(instance_id=name, scenario=scenario))}
        time.sleep(4)
        snapshot = twins.snapshot(SnapshotRequest(instance_id=name, request_key=name, baseline=baseline, policy=policy, duration_s=15, expiry_s=900))['snapshot']
        report['snapshot_id'] = snapshot['snapshot_id']; save()
        for repetition in range(2):
            print('investigation ' + args.phase + ': control ' + str(repetition), flush=True)
            reset = twins.construct(ConstructRequest(twin_id=twin_id, snapshot_id=snapshot['snapshot_id'])) if repetition == 0 else twins.reset(TwinResetRequest(twin_id=twin_id, hypothesis_id='h0'))
            capture = agent.twin_capture(CaptureRequest(instance_id=name, twin_id=twin_id, duration_s=15))
            left,_ = twins.materialize(capture,name); right,_ = twins.materialize(capture,twin_id)
            report['attempts'].append({'repetition':repetition,'capture_id':capture['capture_id'],'runtime_token':reset['ownership']['token'],
                'original_window':left,'twin_window':right,'fidelity':compare(left,right,policy,snapshot['workload'],snapshot['queue_configuration']),
                'measurement_protocol':capture.get('measurement_protocol','legacy_sequential_no_explicit_probe_warmup'),
                'probe_series':{key:[{'probe':p['probe'],'collection_duration_ms':p['collection_duration_ms'],'background_probe':p.get('background_probe')} for p in values] for key,values in capture['series'].items()}})
            save()
        report['state'] = 'completed_all_declared_controls'
    except Exception as exc:
        report.update(state='failed_retained', error=str(exc))
        raise
    finally:
        for label, action in [('twin', lambda: twins.destroy(TwinRequest(twin_id=twin_id))),
                ('scenario', lambda: agent.scenario_reset(instance)), ('original', lambda: agent.network_cleanup(instance))]:
            try: report['cleanup'][label] = action()
            except Exception as exc: report['cleanup'][label] = {'error':str(exc)}  # noqa: BLE001 - retain scoped cleanup failure
        report.update(ended_utc=utc_now(),elapsed_ms=(time.monotonic()-start)*1000); save()


if __name__ == '__main__': main()
