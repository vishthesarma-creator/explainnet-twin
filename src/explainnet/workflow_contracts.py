"""Typed bounded coordinator and original laboratory operations."""
from typing import Any, Literal

from pydantic import Field

from explainnet.contracts import Identifier, Record
from explainnet.network_contracts import InstanceRequest
from explainnet.recovery_spec import RecoveryAction


class ModeRequest(Record):
    mode: Literal['observe', 'recommend', 'assisted-repair', 'lab-auto-repair']
    allow_observed_only: bool = False


class WorkflowRequest(InstanceRequest):
    workflow_id: Identifier
    request_key: Identifier
    baseline: dict[str, Any]
    policy: dict[str, Any]
    max_hypotheses: int = Field(default=2, ge=1, le=2)
    max_repairs: int = Field(default=2, ge=1, le=3)
    timeout_s: int = Field(default=900, ge=60, le=900)


class WorkflowID(Record):
    workflow_id: Identifier


class ApplyRequest(WorkflowID):
    action_id: Identifier
    request_key: Identifier
    test_hook: Literal['verification_failure', 'partial_failure', 'interrupt_after_apply'] | None = None


class UndoRequest(InstanceRequest):
    request_key: Identifier
    action_id: Identifier | None = None


class LabID(Record):
    action_id: Identifier


class LabPrepare(InstanceRequest):
    action_id: Identifier
    idempotency_key: Identifier
    snapshot: dict[str, Any]
    action: RecoveryAction = Field(discriminator='family')
    test_hook: Literal['verification_failure', 'partial_failure', 'interrupt_after_apply'] | None = None


class LabFinish(LabID):
    verified: Literal[True] = True


class LabStimulus(InstanceRequest):
    recipe: dict[str, Any]
