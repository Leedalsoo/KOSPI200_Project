from __future__ import annotations
from decimal import Decimal
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.position_provenance import PositionRole
from contracts.track9_authoritative_sources import Track9PositionExecutionSnapshot

class VirtualTrack9PositionExecutionReadModel:
    """Authoritative Virtual projection of Track9 executions and open position lots."""
    def __init__(self, bridge: VirtualMultiLegExecutionBridge) -> None:
        self.bridge = bridge

    def snapshot(self, *, run_id: str, strategy_id: str) -> Track9PositionExecutionSnapshot | None:
        if run_id != self.bridge.run_id:
            return None
        lots = self.bridge.option_position_attribution.snapshot()
        track9_lots = tuple(x for x in lots if x.strategy_id == strategy_id)
        active_sell_qty = sum(x.remaining_quantity for x in track9_lots if str(x.side).upper() == "SELL")
        insurance_qty = sum(
            x.remaining_quantity for x in self.bridge.insurance_position.snapshot()
            if x.strategy_id == strategy_id and x.position_role != PositionRole.NONE
        )
        premium_spent = Decimal("0")
        for group_reports in self.bridge.groups.values():
            for report in group_reports:
                if report.status != "FILLED" or not report.execution_id or report.execution_price is None:
                    continue
                meta = self.bridge.execution_legs.get(report.execution_id)
                if not meta or meta.get("strategy_id") != strategy_id:
                    continue
                if str(meta.get("asset_type", "")).upper() != "OPTION" or str(meta.get("side", "")).upper() != "BUY":
                    continue
                multiplier = meta.get("contract_multiplier")
                if multiplier is None:
                    return None
                premium_spent += (
                    Decimal(str(report.execution_price))
                    * Decimal(report.filled_quantity)
                    * Decimal(str(multiplier))
                )
        return Track9PositionExecutionSnapshot(
            active_sell_qty=active_sell_qty,
            insurance_qty=insurance_qty,
            premium_spent=premium_spent,
            source="VSSF:CanonicalExecutionReport+VirtualPositionLotStore",
        )
