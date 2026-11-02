"""Bounded, sequential trained-profile development verification. Never fits a model."""
import argparse
import base64
import hashlib
import json
import time
import urllib.request
from uuid import uuid4

from explainnet.agent import AgentClient
from explainnet.app_launcher import validate_binding
from explainnet.application_profiles import PROFILES, ROOT
from explainnet.config import load_network, load_settings
from explainnet.dataset_export import atomic_json
from explainnet.model_bundle import BundleRepository
from explainnet.storage import Store, utc_now
from explainnet.twin_service import TwinService
from explainnet.twin_spec import digest

TERMINAL = {'recommended', 'refused', 'failed', 'interrupted', 'succeeded', 'rolled_back'}


class Verification:
    def __init__(self, run_id, config=None, output_root=None):
        if not run_id.replace('_', '').isalnum() or len(run_id) > 32:
            raise ValueError('bounded alphanumeric run ID required')
        self.cfg = load_settings(config or PROFILES['trained'][0])
        self.url = f'http://127.0.0.1:{self.cfg.port}'
        self.binding = validate_binding(self.cfg, self.url)
        if config is None: assert self.binding['profile'] == 'trained'
        self.store = Store(self.cfg.database_path)
        self.agent = AgentClient(self.cfg.agent_socket)
        self.twins = TwinService(self.store, self.agent, self.cfg.objective)
        self.model = self.http('/v1/models')['active_model_id']
        if not self.model:
            raise ValueError('trained profile has no active model; no observed-only fallback')
        self.trusted = BundleRepository(self.store).inspect(self.model)
        BundleRepository(self.store).load(self.model)  # Full schema/order/units/dependency/hash verification.
        self.out = (output_root or ROOT / 'artifacts/completion_stage2') / run_id
        self.out.mkdir(exist_ok=True,parents=True)
        self.case = None
        self.instance_prefix='c3_' if config is not None else 'c2_'

    def http(self, route, body=None, key=None, hydrate=True):
        req = urllib.request.Request(self.url + route, data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', **({'Idempotency-Key': key} if key else {})})
        with urllib.request.urlopen(req, timeout=40) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('response budget exceeded; outcome unknown, no retry')
        value = json.loads(raw)
        if hydrate and value.get('response_schema_version') == 2 and value.get('evidence_retrieval'):
            expected = value['evidence']; offset = 0; raw = bytearray()
            while offset < expected['bytes']:
                page = self.http(value['evidence_retrieval'] + '?offset=' + str(offset), hydrate=False)
                assert page['sha256'] == expected['sha256'] and page['offset'] == offset
                raw.extend(base64.b64decode(page['base64'], validate=True)); offset = page['next_offset']
                if len(raw) > 32 * 1024 * 1024: raise ValueError('evidence hydration budget exceeded')
            assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
            return json.loads(raw)
        return value

    def save(self):
        self.case['updated_utc'] = utc_now()
        atomic_json(self.out / (self.case['name'] + '.json'), self.case)

    def job(self, route, body):
        key = 'c2' + uuid4().hex
        intent = {'route': route, 'request_key': key, 'body': body, 'at_utc': utc_now(), 'submission': 'pending'}
        self.case.setdefault('jobs', []).append(intent); self.save()
        value = self.http(route, body, key)
        intent.update(job_id=value['job_id'], submission='acknowledged'); self.save()
        end = time.monotonic() + 150
        while time.monotonic() < end:
            actual = self.http('/v1/jobs/' + value['job_id'])
            if actual['state'] == 'succeeded':
                intent['state'] = 'succeeded'; self.save()
                if actual.get('evidence_retrieval'):
                    from explainnet.completion_client import CompletionClient
                    reader=object.__new__(CompletionClient)
                    reader.get=self.http
                    return reader.job_evidence(value['job_id'])['result']
                return actual['result']
            if actual['state'] in {'failed', 'canceled', 'interrupted'}:
                intent.update(state=actual['state'], error=actual.get('error'), result=actual.get('result')); self.save()
                raise RuntimeError(f"{route}: {actual.get('error') or actual['state']}; no automatic retry")
            time.sleep(.4)
        raise TimeoutError('job outcome unknown; inspect saved key/job, no automatic retry')

    def idle(self):
        c = self.http('/v1/lab/control')
        if c.get('active_workflow_id') or c.get('unsettled_action_ids') or c.get('cleanup_pending_workflow_ids') or c.get('monitor_active') or c.get('degraded'):
            raise ValueError('coordinator/action/cleanup unsettled; no laboratory mutation')
        return c

    def diagnosis(self, window):
        start = time.monotonic()
        result = self.job('/v1/models/infer', {'model_id': self.model, 'window_id': window['window_id'], 'mode': 'live'})
        explanation = self.job('/v1/explanations/request', {'model_id': self.model, 'window_id': window['window_id'], 'mode': 'live'})
        end = time.monotonic() + 25
        while explanation['status'] == 'pending' and time.monotonic() < end:
            time.sleep(.2); explanation = self.http('/v1/explanations/' + explanation['explanation_id'])
        assert explanation['model_id'] == self.model and explanation['window_id'] == window['window_id']
        return {'diagnosis': result, 'explanation': explanation, 'completion_elapsed_ms': (time.monotonic() - start) * 1000}

    def wait_workflow(self, wid, deadline_s=930):
        end = time.monotonic() + deadline_s; state = None
        while time.monotonic() < end:
            w = self.http('/v1/lab/workflows/' + wid)
            if w['state'] != state:
                print(self.case['name'] + ': ' + w['state'], flush=True); state = w['state']
            self.case['workflow'] = w; self.save()
            if w['state'] in TERMINAL and self.http('/v1/lab/control')['active_workflow_id'] != wid:
                return w
            time.sleep(1)
        raise TimeoutError('bounded workflow deadline; active ownership retained, no replay')

    def run_case(self, name, automatic=False, scenario_kind=None, definition=None, strategy='trained_twin', seed=20261016, healthy_fidelity=False):
        path = self.out / (name + '.json')
        if path.exists():
            raise ValueError('case already attempted; use status or --resume; no favorable-sample rerun')
        self.idle()
        if any(r['state'] == 'running' for r in self.agent.inventory()['instances']):
            raise ValueError('canonical owner already has a live laboratory; do not interfere')
        if strategy not in {'trained_twin','independent_no_twin','impaired_no_change','recommend_only'}:
            raise ValueError('unsupported comparison strategy')
        kind = scenario_kind or ('latency' if automatic else name)
        definition = definition or load_network(self.cfg.topology_file).model_dump()
        instance = self.instance_prefix + name + '_' + uuid4().hex[:9]
        self.case = {'name': name, 'reference_fault': kind, 'instance_id': instance, 'mode': 'trained-model',
            'automatic_explicitly_requested': automatic, 'model_id': self.model, 'model_manifest_sha256': self.trusted['manifest_sha256'],
            'binding': self.binding, 'started_utc': utc_now(), 'state': 'preparing', 'finished': False, 'jobs': [],
            'ground_truth_used_for_inference': False, 'source_episode_unit': 'one independent original Mininet construction',
            'trial_unit': 'two fresh-runtime measurements per candidate per retained observable hypothesis'}
        self.case.update(comparison_strategy=strategy,topology_switches=len(definition['switches']))
        self.save(); start = time.monotonic()
        try:
            self.job('/v1/lab/mode', {'mode': 'recommend', 'allow_observed_only': False})
            constructed=time.monotonic()
            self.case['construction']=self.job('/v1/networks/start', {'instance_id': instance,'switches':len(definition['switches'])})
            self.case['construction_rpc_ms']=(time.monotonic()-constructed)*1000
            self.case['connectivity'] = self.job('/v1/networks/probe', {'instance_id': instance, 'source_host': 'h1', 'target_host': 'h3'})
            assert self.case['connectivity']['passed']
            if healthy_fidelity:
                self.case['all_pair_connectivity']=self.job('/v1/networks/probe',{'instance_id':instance})
                assert self.case['all_pair_connectivity']['passed']
                self.job('/v1/networks/path',{'instance_id':instance,'pair_id':'critical','path_name':'alternative'})
                self.case['alternate_connectivity']=self.job('/v1/networks/probe',{'instance_id':instance,'source_host':'h1','target_host':'h3'})
                assert self.case['alternate_connectivity']['passed']
                self.job('/v1/networks/path',{'instance_id':instance,'pair_id':'critical','path_name':'primary'})
            scenario = {'schema_version':1, 'config_version':'recovery_observation_v1', 'kind': kind, 'severity':'high',
                'warmup_s':3, 'measurement_s':900, 'bidirectional':False, 'variation_ms':0, 'high_utilization':False,
                'traffic_profile':'shared' if kind == 'saturation' else 'qos_competing' if kind == 'qos' else 'moderate',
                'critical_bps':2_000_000 if kind == 'qos' else 8_000_000, 'bulk_protocol':'udp', 'packet_size':1200, 'seed':seed}
            nominal_run = None
            if kind == 'qos':
                nominal_setup = scenario | {'kind':'healthy'}
                self.case['nominal_setup_ground_truth'] = self.job('/v1/laboratory/scenarios/start', {'instance_id': instance, 'scenario':nominal_setup})
            else:
                profiles = [{'schema_version':1, 'config_version':'workflow_observation_v1', 'profile_id':p,
                    'source_host':a, 'target_host':b, 'protocol':'udp', 'offered_bps':rate, 'packet_size':1200,
                    'duration_s':900, 'warmup_s':3, 'stream_receiver':True}
                    for p,a,b,rate in [('critical','h1','h3',8_000_000),('bulk','h2','h4',5_000_000)]]
                nominal_run = self.job('/v1/traffic/workload/start', {'instance_id':instance, 'profiles':profiles})
            self.job('/v1/telemetry/start', {'instance_id':instance, 'duration_s':900})
            time.sleep(4)  # Fixed native omitted warmup plus one-second allowance, never sample-dependent.
            pilots = [self.twins.capture(instance, 15)['window'] for _ in range(2)]
            self.case['pilot_windows'] = pilots; self.save()
            baseline = {'window_ids':[w['window_id'] for w in pilots], 'definition_hash':digest(definition)}
            _,policy = self.twins.pilot_reference(**baseline)
            self.case.update(baseline=baseline, fidelity_policy=policy); self.save()
            if kind != 'healthy':
                self.job('/v1/telemetry/stop', {'instance_id':instance})
                if kind == 'qos': self.job('/v1/laboratory/scenarios/reset', {'instance_id':instance})
                else: self.job('/v1/traffic/stop', {'instance_id':instance, 'run_id':nominal_run['run_id']})
                self.case['ground_truth'] = {'recipe':scenario, 'setup':self.job('/v1/laboratory/scenarios/start', {'instance_id':instance, 'scenario':scenario})}
                self.job('/v1/telemetry/start', {'instance_id':instance, 'duration_s':900}); time.sleep(4)
                observed = self.twins.capture(instance, 15)['window']
            else: observed = pilots[-1]
            self.case['observation'] = observed
            self.case['observation_ready_monotonic_s']=time.monotonic()
            from explainnet.completion_baselines import independent_proposal
            from explainnet.network_contracts import InstanceRequest
            self.case['independent_baseline']=independent_proposal(observed,
                self.agent.twin_view(InstanceRequest(instance_id=instance)),self.cfg.objective)
            self.case['trained_observation'] = self.diagnosis(observed); self.save()
            self.case['diagnosis_explanation_ready_monotonic_s']=time.monotonic()
            mode = 'lab-auto-repair' if automatic else 'recommend'
            self.job('/v1/lab/mode', {'mode':mode, 'allow_observed_only':False})
            wid = 'c2w_' + uuid4().hex
            payload = {'instance_id':instance, 'workflow_id':wid, 'request_key':wid, 'baseline':baseline,
                'policy':policy, 'max_repairs':2, 'max_hypotheses':2, 'timeout_s':900}
            atomic_json(self.out / (name + '_workflow_request.json'), payload)
            self.case['workflow_id'] = wid; self.save()
            self.job('/v1/lab/workflow', payload)
            w = self.wait_workflow(wid)
            self.case['recommendation_outcome_monotonic_s']=time.monotonic()
            apply_selected=w['state']=='recommended' and strategy in {'trained_twin','independent_no_twin'}
            if apply_selected and strategy=='independent_no_twin':
                exp=w['candidate_result'];selected=exp['recommendation']['selected_candidate_id']
                action=next(c['action'] for c in exp['candidates'] if c['candidate_id']==selected)
                apply_selected=action==self.case['independent_baseline']['action']
                if not apply_selected:self.case['baseline_original_refusal']='Independent proposal differs from qualified selected action; no unsupported override'
            if apply_selected and not automatic:
                assert w['diagnosis']['status'] == 'supported' and w['explanation']['status'] == 'ready'
                self.job('/v1/lab/mode', {'mode':'assisted-repair', 'allow_observed_only':False})
                action_id = 'c2a_' + uuid4().hex
                self.job('/v1/lab/apply', {'workflow_id':wid, 'action_id':action_id, 'request_key':action_id})
                w = self.wait_workflow(wid, 180)
            self.case['outcome_monotonic_s']=time.monotonic()
            if w.get('action_id'):
                self.case['original_action'] = self.http('/v1/lab/actions/' + w['action_id']); self.save()
                if self.case['original_action']['state'] == 'succeeded':
                    self.case['undo'] = self.job('/v1/lab/undo', {'instance_id':instance, 'action_id':w['action_id'], 'request_key':'c2u_' + uuid4().hex})
            if strategy=='impaired_no_change' and kind!='healthy':
                self.case['no_change_windows']=[self.twins.capture(instance,15)['window'] for _ in range(2)]
                self.case['retained_impaired']=True
            if kind=='healthy' and healthy_fidelity:
                self.healthy_controls(instance,baseline,policy)
            self.case.update(state=w['state'], finished=True)
        except Exception as exc:  # noqa: BLE001 - preserve every source/setup/trial failure, no automatic retry
            self.case.update(state='blocked', error=str(exc), finished=True)
        finally:
            self.case['cleanup'] = {}
            try:
                c = self.idle()
                if c.get('auto_enabled'):
                    self.http('/v1/lab/automation/stop', {})
                self.job('/v1/lab/mode', {'mode':'recommend', 'allow_observed_only':False})
                self.job('/v1/telemetry/stop', {'instance_id':instance})
                state = self.http('/v1/networks/' + instance)
                if state['state'] == 'running':
                    journal = self.http('/v1/laboratory/scenarios/' + instance).get('laboratory_journal') or {}
                    if journal.get('state') not in {None,'stopped'}: self.job('/v1/laboratory/scenarios/reset', {'instance_id':instance})
                self.case['cleanup'] = self.job('/v1/networks/cleanup', {'instance_id':instance})
            except Exception as exc:  # noqa: BLE001 - unresolved owner must remain explicit; do not force teardown
                self.case['cleanup'] = {'blocked':str(exc)}
            self.case.update(ended_utc=utc_now(), elapsed_ms=(time.monotonic()-start)*1000); self.save()
        return self.case

    def healthy_controls(self,instance,baseline,policy):
        from explainnet.twin_contracts import (
            ConstructRequest,
            SnapshotRequest,
            TwinMeasureRequest,
            TwinRequest,
            TwinResetRequest,
        )
        twin='tw'+uuid4().hex[:16]
        snapshot=self.twins.snapshot(SnapshotRequest(instance_id=instance,request_key='s'+uuid4().hex,
            baseline=baseline,policy=policy,duration_s=15,expiry_s=900))['snapshot']
        self.case['healthy_twin_controls']=[];self.save()
        try:
            self.twins.construct(ConstructRequest(twin_id=twin,snapshot_id=snapshot['snapshot_id']))
            for repeat in range(2):
                if repeat:self.twins.reset(TwinResetRequest(twin_id=twin,hypothesis_id='h0'))
                result=self.twins.measure(TwinMeasureRequest(twin_id=twin,trial_id='v'+uuid4().hex,duration_s=15))
                self.case['healthy_twin_controls'].append(result);self.save()
        finally:
            self.case['healthy_twin_cleanup']=self.twins.destroy(TwinRequest(twin_id=twin));self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','status'])
    parser.add_argument('--case', choices=['all','healthy','latency','loss','saturation','qos'], default='all')
    parser.add_argument('--run-id', default='main')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.action == 'status':
        out = ROOT / 'artifacts/completion_stage2' / args.run_id
        print(json.dumps([{'case':d['name'], 'historical_outcome':d.get('state'), 'error':d.get('error'),
            'workflow_id':d.get('workflow_id'), 'undo_state':(d.get('undo') or {}).get('state'),
            'cleanup_state':d.get('cleanup',{}).get('state')}
            for p in out.glob('*.json') if (d:=json.loads(p.read_text())).get('name')], indent=2)); return
    v = Verification(args.run_id)
    plan_file = v.out / 'plan.json'
    if not plan_file.exists():
        atomic_json(plan_file, {'version':'completion_stage2_development_v1', 'at_utc':utc_now(),
            'cases':['healthy','latency','loss','saturation','qos'], 'independent_episodes_per_case':1,
            'max_repairs':2,'repetitions':2,'max_hypotheses':2,'trial_duration_s':15,'workflow_timeout_s':900,
            'conditional_extra_episode':'exactly one fresh latency automatic episode only after a successful trained assisted latency case',
            'retry_failed_samples':False,'sealed_test_access':False,'training':False,'observed_only_fallback':False})
    for case in ['healthy','latency','loss','saturation','qos'] if args.case == 'all' else [args.case]:
        if (v.out / (case+'.json')).exists() and args.resume: continue
        result = v.run_case(case)
        print(json.dumps({'case':case,'state':result['state'],'error':result.get('error')}), flush=True)
        if result.get('cleanup',{}).get('blocked'): break
    latency = v.out / 'latency.json'
    if args.case == 'all' and latency.exists() and not (v.out/'automatic_latency.json').exists():
        case = json.loads(latency.read_text())
        if (case.get('original_action') or {}).get('state') == 'succeeded' and not case.get('cleanup',{}).get('blocked'):
            v.run_case('automatic_latency', automatic=True)


if __name__ == '__main__': main()
