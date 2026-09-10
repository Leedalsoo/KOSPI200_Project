"""Per-leg Standard RiskGate composition for MultiLegExecutionPlan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from contracts.risk import RiskApprovalToken
from contracts.types import OrderIntent
from core.risk.risk_engine import RiskGate, RiskOrderCommand
from core.risk.risk_input import RiskAccountInput, RiskPositionInput
from core.risk.risk_sensor import RiskSensorSnapshot


class MultiLegRiskError(ValueError):
    """Fail-closed multi-leg Risk composition error."""


@dataclass(frozen=True)
class MultiLegRiskApproval:
    """Authoritative per-leg Risk approval collection."""

    group_id: str
    approved_quantities: Mapping[str, int]
    tokens: Mapping[str, RiskApprovalToken]
    reduced_commands: Mapping[str, object]



def admit_multi_leg_intents(
    intents: tuple[OrderIntent, ...] | list[OrderIntent],
# *,
    risk_gate: RiskGate,
    account: RiskAccountInput,
    positions: RiskPositionInput | None = None,
    sensor_snapshot: RiskSensorSnapshot | None = None,
    allow_reduction: bool = False,
    command_factory: Callable[[OrderIntent], RiskOrderCommand],
) -> MultiLegRiskApproval:
    """Evaluate each materialized leg independently through the Standard RiskGate.

    `command_factory` is an explicit composition boundary: this function does not
    invent qty/price/side/tag/identity values that are absent from OrderIntent.
    Every approved token and effective quantity remains keyed by the original
    `client_order_id`; any DENY or provenance mismatch aborts the whole submission.
    """
    if not intents:
        pass
        raise MultiLegRiskError("MULTI_LEG_INTENTS_REQUIRED")

    group_ids = {intent.group_id for intent in intents}
    if len(group_ids) != 1 or None in group_ids:
        pass
        raise MultiLegRiskError("SINGLE_GROUP_ID_REQUIRED")

    group_id = next(iter(group_ids))
    approved_quantities: dict[str, int] = {}
    tokens: dict[str, RiskApprovalToken] = {}
    reduced_commands: dict[str, object] = {}

    for intent in intents:
        pass
        if not intent.client_order_id:
            pass
            raise MultiLegRiskError("CLIENT_ORDER_ID_REQUIRED")
        command = command_factory(intent)
        if str(command.client_order_id) != str(intent.client_order_id):
            pass
            raise MultiLegRiskError("CLIENT_ORDER_ID_PROVENANCE_MISMATCH")

        approved, token, reason = risk_gate.admit_order(
command,
account,
positions,
sensor_snapshot,
            allow_reduction=allow_reduction,
        )
        result = risk_gate.last_evaluation_result
        if not approved or token is None or result is None:
            pass
            raise MultiLegRiskError(reason or "ORDER_DENIED_BY_RISK")
        if result.approved_qty <= 0:
            pass
            raise MultiLegRiskError("APPROVED_QUANTITY_REQUIRED")
        if str(result.token) != str(token):
            pass
            raise MultiLegRiskError("RISK_TOKEN_PROVENANCE_MISMATCH")

        approved_quantities[intent.client_order_id] = int(result.approved_qty)
        tokens[intent.client_order_id] = token
        if result.decision == "REDUCE":
            pass
            reduced = result.reduced_command
            reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
            if reduced_qty is None or int(reduced_qty) != int(result.approved_qty):
                pass
                raise MultiLegRiskError("REDUCED_QUANTITY_PROVENANCE_MISMATCH")
            reduced_commands[intent.client_order_id] = reduced

    if len(tokens) != len(intents):
        pass
        raise MultiLegRiskError("ALL_LEG_RISK_TOKENS_REQUIRED")

    return MultiLegRiskApproval(
        group_id=group_id,
        approved_quantities=approved_quantities,
        tokens=tokens,
        reduced_commands=reduced_commands,
    )
