"""Declared Stage 11 laboratory workflow policy; usable by OS Python."""
from explainnet.recovery_spec import POLICY_HASH, validate_action
from explainnet.topology.spec import fields, identifier
from explainnet.twin_spec import digest, validate_snapshot

WORKFLOW_POLICY = {'version': 'workflow_v2', 'action_policy_hash': POLICY_HASH,
    'original_families': ['reroute'], 'default_mode': 'recommend', 'persistence_windows': 2,
    'verification_windows': 2, 'window_s': 10, 'settle_s': 2, 'cooldown_s': 120,
    'max_attempts_per_incident': 2, 'max_workflow_s': 900, 'max_action_s': 150,
    'auto_requires_model': True, 'explicit_observed_only_lab_exception': True}
WORKFLOW_HASH = digest(WORKFLOW_POLICY)


def validate_lab(operation, p):
    required = ['schema_version', 'action_id']
    if operation == 'lab_prepare':
        required += ['instance_id', 'snapshot', 'action', 'idempotency_key', 'test_hook']
    if operation == 'lab_finish':
        required += ['verified']
    if operation == 'lab_test_stimulus':
        required = ['schema_version', 'instance_id', 'recipe']
    fields(p, required)
    if type(p['schema_version']) is not int or p['schema_version'] != 1:
        raise ValueError('unsupported laboratory schema')
    for key in ('action_id', 'instance_id', 'idempotency_key'):
        if key in p:
            identifier(p[key])
    if operation == 'lab_prepare':
        validate_snapshot(p['snapshot'])
        validate_action(p['action'])
        if p['action']['family'] not in WORKFLOW_POLICY['original_families']:
            raise ValueError('original action family lacks measured qualification')
        if p['test_hook'] not in {None, 'verification_failure', 'partial_failure', 'interrupt_after_apply'}:
            raise ValueError('unknown bounded test hook')
    if operation == 'lab_finish' and p['verified'] is not True:
        raise ValueError('unverified action cannot be kept')
    if operation == 'lab_test_stimulus':
        from explainnet.scenario_spec import validate_scenario
        validate_scenario(p['recipe'])
        if p['recipe']['kind'] != 'latency' or p['recipe']['severity'] != 'high' or p['recipe']['bidirectional']:
            raise ValueError('only declared one-direction latency demonstration stimulus supported')
