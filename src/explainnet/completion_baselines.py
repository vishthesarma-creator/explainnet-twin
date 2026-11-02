"""Independent deterministic baseline. No twin, diagnosis label, SHAP or truth inputs."""
import time

from explainnet.recovery_spec import POLICY_HASH
from explainnet.service_requirements import evaluate


def independent_proposal(window,view,objective=None):
    started=time.monotonic()
    evidence=evaluate(window,objective)
    action=None;reason='Service acceptable or insufficient measured service evidence'
    if evidence['service_violation'] and not evidence['missing']:
        pair=next((p for p in view['definition']['pairs'] if p['pair_id']=='critical' and
            p['source_host']=='h1' and p['target_host']=='h3'),None)
        if pair:
            current=view['selected_paths']['critical']
            alternatives=sorted(k for k,p in pair['paths'].items() if p!=pair['paths'][current])
            if alternatives:
                action={'family':'reroute','policy_hash':POLICY_HASH,'changes':[{'pair_id':'critical','from_path':current,'to_path':alternatives[0]}]}
                reason='Observed service violation: choose first declared critical alternate, independently of twin outcomes. Shared feasibility/actuation gates still required.'
    return {'algorithm':'deterministic_service_alternate_v1','action':action,'reason':reason,
        'service_evidence':evidence,'algorithm_ms':(time.monotonic()-started)*1000,
        'uses_twin_results':False,'uses_SHAP':False,'uses_injector_truth':False,
        'timing_boundary':'qualified existing observation+logical topology ready to independent proposal; excludes common shadow qualification'}
