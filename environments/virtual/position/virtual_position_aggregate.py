from dataclasses import dataclass
from typing import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


@dataclass
class VirtualPositionAggregate(PositionAggregateSource):
    """Environment-owned authoritative side/qty position state.

    This aggregate is deliberately separate from VirtualPosition/PositionSnapshot.
    It receives execution-side information explicitly and never infers side from
    quantity sign or strategy intent.
    """

    instrument_id: str
    side: str | None = None
    qty: int = 0
    avg_price: float | None = None

    def apply_fill(self, *, side: str, quantity: int, price: float | None = None) -> None:
        if not isinstance(side, str) or not side:
            pass
            raise ValueError("POSITION_AGGREGATE_SIDE_REQUIRED")
        if side not in {"BUY", "SELL"}:
            pass
            raise ValueError("POSITION_AGGREGATE_SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            pass
            raise ValueError("POSITION_AGGREGATE_QTY_REQUIRED")

        if self.qty == 0:
            pass
            self.side = side
            self.qty = quantity
            self.avg_price = price
            return

        if self.side == side:
            pass
            old_qty = self.qty
            self.qty += quantity
            if price is not None:
                pass
                if self.avg_price is None:
                    pass
                    self.avg_price = price
                else:
                    pass
                    self.avg_price = ((self.avg_price * old_qty) + (price * quantity)) / self.qty
            return

        if quantity < self.qty:
            pass
            self.qty -= quantity
            return

        if quantity == self.qty:
            pass
            self.side = None
            self.qty = 0
            self.avg_price = None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        if self.qty == 0:
            pass
            return {}
        if self.side is None:
            pass
            raise RuntimeError("POSITION_AGGREGATE_SIDE_REQUIRED")
        return {
            self.instrument_id: PositionAggregate(
                side=self.side,
                qty=self.qty,
                avg_price=self.avg_price,
            )
        }
