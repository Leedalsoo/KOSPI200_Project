from __future__ import annotations
from datetime import datetime
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
        put_fills: list[tuple[object, Decimal, int]] = []
        call_fills: list[tuple[object, Decimal, int]] = []
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
                execution_price = Decimal(str(report.execution_price))
                premium_spent += (
                    execution_price
                    * Decimal(report.filled_quantity)
                    * Decimal(str(multiplier))
                )
                option_type = str(meta.get("option_type", "")).upper()
                if option_type == "PUT":
                    put_fills.append((report.execution_timestamp, execution_price, report.filled_quantity))
                elif option_type == "CALL":
                    call_fills.append((report.execution_timestamp, execution_price, report.filled_quantity))
        def latest_fill(fills: list[tuple[object, Decimal, int]]) -> tuple[Decimal, object] | None:
            if not fills:
                return None
            latest = max(fills, key=lambda item: item[0] or datetime.min)
            return latest[1], latest[0]
        put_fill = latest_fill(put_fills)
        call_fill = latest_fill(call_fills)
        return Track9PositionExecutionSnapshot(
            active_sell_qty=active_sell_qty,
            insurance_qty=insurance_qty,
            premium_spent=premium_spent,
            put_entry_price=put_fill[0] if put_fill else None,
            call_entry_price=call_fill[0] if call_fill else None,
            put_entry_timestamp=put_fill[1] if put_fill else None,
            call_entry_timestamp=call_fill[1] if call_fill else None,
            source="VSSF:CanonicalExecutionReport+VirtualPositionLotStore",
        )
