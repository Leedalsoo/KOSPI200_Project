from __future__ import annotations

from core.risk.risk_input import RiskPosition, RiskPositionInput


def position_manager_to_risk_input(source) -> RiskPositionInput:
    snapshot_method = getattr(source, "snapshot", None)
    snapshot = snapshot_method() if callable(snapshot_method) else getattr(source, "positions", None)
    if snapshot is None:
        raise ValueError("RISK_POSITION_SOURCE_REQUIRED")
    positions = {}
    for instrument_id, position in snapshot.items():
        side = str(getattr(position, "side", position.get("side", ""))).strip().upper()
        qty = int(getattr(position, "qty", position.get("qty", 0)))
        if side not in {"BUY", "SELL"}:
            raise ValueError("RISK_POSITION_SIDE_REQUIRED")
        if qty < 0:
            raise ValueError("RISK_POSITION_QTY_INVALID")
        positions[str(instrument_id)] = RiskPosition(side=side, qty=qty)
    return RiskPositionInput(positions=positions)
