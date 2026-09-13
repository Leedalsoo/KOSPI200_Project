from __future__ import annotations

from core.position.position_aggregate import PositionAggregateSource
from core.risk.risk_input import RiskPosition, RiskPositionInput


def position_manager_to_risk_input(source: PositionAggregateSource) -> RiskPositionInput:
    snapshot = source.snapshot()
    positions = {}
    for instrument_id, position in snapshot.items():
        side = str(position.side).strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("RISK_POSITION_SIDE_REQUIRED")
        qty = int(position.qty)
        if qty < 0:
            raise ValueError("RISK_POSITION_QTY_INVALID")
        positions[str(instrument_id)] = RiskPosition(side=side, qty=qty)
    return RiskPositionInput(positions=positions)
