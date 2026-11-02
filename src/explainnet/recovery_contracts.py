"""Bounded public recovery requests; no original execution operation exists."""
from pydantic import Field

from explainnet.contracts import Identifier, Record
from explainnet.recovery_spec import RecoveryAction
from explainnet.twin_contracts import TwinRequest


class RecoveryRequest(TwinRequest):
    operation_id: Identifier
    snapshot_id: Identifier
    max_repairs: int = Field(default=3, ge=1, le=3)
    repetitions: int = Field(default=2, ge=2, le=3)
    max_hypotheses: int = Field(default=2, ge=1, le=2)
    duration_s: int = Field(default=10, ge=10, le=20)
    seed: int = Field(default=20261007, ge=0, le=2147483647)
    timeout_s: int = Field(default=700, ge=30, le=700)


class RecoveryID(Record):
    operation_id: Identifier


class AgentRecoveryAction(TwinRequest):
    snapshot_hash: str
    action: RecoveryAction = Field(discriminator='family')
