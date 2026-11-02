"""Restricted version 1 operation validation, usable by OS Python."""

from explainnet.topology.spec import fields, identifier, validate_definition

OPERATIONS = {
    "evidence_read",
    "lab_prepare", "lab_apply", "lab_status", "lab_finish", "lab_rollback", "lab_test_stimulus",
    "health", "capabilities", "inventory", "network_start", "network_inspect", "network_stop",
    "network_cleanup", "path_select", "network_probe", "traffic_start", "traffic_status", "traffic_stop",
    "scenario_start", "scenario_inspect", "scenario_stop", "scenario_reset",
    "telemetry_observe",
    "twin_view", "twin_capture", "twin_construct", "twin_status", "twin_reset", "twin_destroy", "twin_cancel", "twin_apply_candidate",
}


def validate_parameters(operation, parameters):
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")  # noqa: TRY004 - protocol validation error
    if operation == 'evidence_read':
        fields(parameters, ['sha256', 'offset'])
        sha = parameters['sha256']
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('invalid evidence hash')
        if type(parameters['offset']) is not int or parameters['offset'] < 0:
            raise ValueError('invalid evidence offset')
        return
    if operation in {"health", "capabilities", "inventory"}:
        if parameters:
            raise ValueError("read-only operation takes no parameters")
        return
    if operation.startswith('lab_'):
        from explainnet.workflow_spec import validate_lab
        validate_lab(operation, parameters)
        return
    if operation.startswith('twin_'):
        required = ['schema_version', 'instance_id'] if operation in {'twin_view', 'twin_capture'} else ['schema_version', 'twin_id']
        if operation == 'twin_capture':
            required += ['duration_s', 'twin_id']
        if operation == 'twin_construct':
            required += ['snapshot', 'hypothesis_id']
        if operation == 'twin_apply_candidate':
            required += ['snapshot_hash', 'action']
        if operation == 'twin_reset':
            required += ['hypothesis_id']
        fields(parameters, required)
        if type(parameters['schema_version']) is not int or parameters['schema_version'] != 1:
            raise ValueError('unsupported twin schema')
        for key in ('instance_id', 'twin_id', 'hypothesis_id'):
            if key in parameters and parameters[key] is not None:
                identifier(parameters[key])
        if operation == 'twin_capture' and (type(parameters['duration_s']) is not int or not 10 <= parameters['duration_s'] <= 20):
            raise ValueError('bounded capture duration required')
        if operation == 'twin_apply_candidate':
            from explainnet.recovery_spec import validate_action
            validate_action(parameters['action'])
            if not isinstance(parameters['snapshot_hash'], str) or len(parameters['snapshot_hash']) != 64:
                raise ValueError('snapshot hash required')
        if operation == 'twin_construct':
            from explainnet.twin_spec import validate_snapshot
            validate_snapshot(parameters['snapshot'])
        return
    required = ["schema_version", "instance_id"]
    if operation == "network_start":
        required.append("definition")
    elif operation == "scenario_start":
        required.append("scenario")
    elif operation == "telemetry_observe":
        required.extend(["source_host", "target_host", "probe_count", "completed_run_ids", "since_utc"])
    elif operation == "path_select":
        required.extend(["pair_id", "path_name"])
    elif operation == "network_probe":
        required.extend(["source_host", "target_host"])
    elif operation == "traffic_start":
        required.append("profiles")
    elif operation in {"traffic_status", "traffic_stop"}:
        required.append("run_id")
    fields(parameters, required, ["live_receivers"] if operation == "telemetry_observe" else [])
    if operation == "telemetry_observe" and type(parameters.get("live_receivers", False)) is not bool:
        raise ValueError("invalid live receiver flag")
    if type(parameters["schema_version"]) is not int or parameters["schema_version"] != 1:
        raise ValueError("unsupported parameter schema")
    identifier(parameters["instance_id"])
    if operation == "network_start":
        validate_definition(parameters["definition"])
    elif operation == "scenario_start":
        from explainnet.scenario_spec import validate_scenario
        validate_scenario(parameters["scenario"])
    elif operation == "telemetry_observe":
        from datetime import UTC, datetime
        identifier(parameters["source_host"])
        identifier(parameters["target_host"])
        if type(parameters["probe_count"]) is not int or not 1 <= parameters["probe_count"] <= 5:
            raise ValueError("expected 1..5 probe packets")
        ids = parameters["completed_run_ids"]
        if not isinstance(ids, list) or len(ids) > 256:
            raise ValueError("invalid completed run cursor")
        for run_id in ids:
            identifier(run_id)
        stamp = datetime.fromisoformat(parameters["since_utc"])
        if stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp):
            raise ValueError("observation cursor must be UTC")
    elif operation == "path_select":
        identifier(parameters["pair_id"])
        identifier(parameters["path_name"])
    elif operation == "network_probe":
        for name in ("source_host", "target_host"):
            if parameters[name] is not None:
                identifier(parameters[name])
    elif operation == "traffic_start":
        if not isinstance(parameters["profiles"], list) or not 1 <= len(parameters["profiles"]) <= 3:
            raise ValueError("expected 1..3 profiles")
    elif operation in {"traffic_status", "traffic_stop"}:
        identifier(parameters["run_id"])
