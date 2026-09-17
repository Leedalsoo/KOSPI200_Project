from collections.abc import Mapping
from typing import Any

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


class VSSFPositionAggregateAdapter(PositionAggregateSource):
    """Read-only projection of VSSF authoritative positions into the Standard contract."""

    def __init__(self, position_source: Any):
        self._position_source = position_source

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        positions = getattr(self._position_source, "positions", None)
        if not isinstance(positions, Mapping):
            raise TypeError("VSSF_POSITION_SOURCE_REQUIRED")

        projected: dict[str, PositionAggregate] = {}
        for instrument_key, state in positions.items():
            if not isinstance(instrument_key, str) or not instrument_key:
                raise TypeError("VSSF_POSITION_INSTRUMENT_KEY_REQUIRED")
            if not isinstance(state, Mapping):
                raise TypeError("VSSF_POSITION_STATE_REQUIRED")

            side = state.get("side")
            qty = state.get("qty")
            avg_price = state.get("avg_price")

            if not isinstance(side, str) or side not in {"BUY", "SELL"}:
                raise TypeError("VSSF_POSITION_SIDE_REQUIRED")
            if not isinstance(qty, int) or qty <= 0:
                raise TypeError("VSSF_POSITION_QTY_REQUIRED")
            if avg_price is not None and not isinstance(avg_price, (int, float)):
                raise TypeError("VSSF_POSITION_AVG_PRICE_INVALID")

            projected[instrument_key] = PositionAggregate(
                side=side,
                qty=qty,
                avg_price=float(avg_price) if avg_price is not None else None,
            )

        return projected
