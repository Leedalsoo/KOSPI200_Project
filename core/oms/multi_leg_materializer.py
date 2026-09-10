from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity, OrderIntent

class MultiLegMaterializationError(ValueError): pass
IdentityResolver = Callable[[ExecutionLeg], OptionInstrumentIdentity]

@dataclass(frozen=True)
class MultiLegExecutionSemantics:
    order_type: str
    order_purpose: str
    asset_type: str = "OPTION"

def materialize_multi_leg_plan(plan: MultiLegExecutionPlan, *, resolve_identity: IdentityResolver, semantics: MultiLegExecutionSemantics, client_order_id_for: Callable[[MultiLegExecutionPlan, ExecutionLeg], str] | None = None) -> Sequence[OrderIntent]:
    if not semantics.order_type: raise MultiLegMaterializationError("ORDER_TYPE_REQUIRED")
    if not semantics.order_purpose: raise MultiLegMaterializationError("ORDER_PURPOSE_REQUIRED")
    if semantics.asset_type != "OPTION": raise MultiLegMaterializationError("OPTION_ASSET_TYPE_REQUIRED")
    make_client_id = client_order_id_for or (lambda p, leg: f"{p.group_id}:{leg.leg_id}")
    intents = []
    for leg in plan.legs:
        pass
        identity = resolve_identity(leg)
        if not identity or not identity.instrument_id: raise MultiLegMaterializationError("AUTHORITATIVE_IDENTITY_REQUIRED")
        if leg.option_type is not None and identity.option_type != leg.option_type: raise MultiLegMaterializationError("OPTION_TYPE_IDENTITY_MISMATCH")
        if leg.strike is not None and identity.strike != leg.strike: raise MultiLegMaterializationError("STRIKE_IDENTITY_MISMATCH")
        client_order_id = make_client_id(plan, leg)
        if not client_order_id: raise MultiLegMaterializationError("CLIENT_ORDER_ID_REQUIRED")
        intents.append(OrderIntent(client_order_id=client_order_id, instrument_id=identity.instrument_id, side=leg.side, quantity=leg.quantity, intent_type=semantics.order_purpose, strategy_id=plan.strategy_id, instrument_identity=identity, asset_type=semantics.asset_type, requested_price=leg.requested_price, order_type=semantics.order_type, order_purpose=semantics.order_purpose, track_id=plan.strategy_id, group_id=plan.group_id, leg_id=leg.leg_id))
    return tuple(intents)
