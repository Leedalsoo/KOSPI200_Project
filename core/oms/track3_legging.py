from dataclasses import dataclass
from contracts.types import OrderIntent
from core.oms.position_group import PositionGroupLeg, LegStatus

@dataclass(frozen=True)
class LeggingPlan:
    group_id: str
    first_leg: PositionGroupLeg
    second_leg: PositionGroupLeg

class Track3LeggingCoordinator:
    """Turns a two-leg Track3 plan into sequential OrderIntent objects.

    No broker, clock, VMS/VSSF or UI dependency is allowed here.
    """
    def start(self, plan: LeggingPlan, *, price: object, purpose: str) -> OrderIntent:
        leg = plan.first_leg
        return OrderIntent(
            client_order_id=leg.leg_id,
            instrument_id=leg.instrument_id,
            side=leg.side,
            quantity=leg.quantity,
            intent_type=f"{purpose}:{plan.group_id}:{leg.leg_id}",
            group_id=plan.group_id,
            leg_id=leg.leg_id,
        )

    def next_after_fill(self, plan: LeggingPlan, filled_leg_id: str) -> OrderIntent | None:
        if filled_leg_id != plan.first_leg.leg_id:
            return None
        leg = plan.second_leg
        return OrderIntent(
            client_order_id=leg.leg_id,
            instrument_id=leg.instrument_id,
            side=leg.side,
            quantity=leg.quantity,
            intent_type=f"TRACK3_LEG2:{plan.group_id}:{leg.leg_id}",
            group_id=plan.group_id,
            leg_id=leg.leg_id,
        )
