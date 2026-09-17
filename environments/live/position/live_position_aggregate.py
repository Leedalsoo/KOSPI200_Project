from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionAggregate:
    instrument_id: str
    side: str | None
    qty: int
    avg_price: Decimal | None


class LivePositionAggregate:
    """Live-owned authoritative side/quantity/average-price aggregate."""

    def __init__(self, instrument_id: str) -> None:
        instrument_id = str(instrument_id).strip()
        if not instrument_id:
            raise ValueError("INSTRUMENT_ID_REQUIRED")
        self.instrument_id = instrument_id
        self.side: str | None = None
        self.qty = 0
        self.avg_price: Decimal | None = None

    def apply_fill(self, *, side: str, quantity: int, price: Decimal) -> None:
        if side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("QUANTITY_INVALID")
        if not isinstance(price, Decimal):
            try:
                price = Decimal(str(price))
            except Exception as exc:
                raise ValueError("PRICE_INVALID") from exc
        if price <= 0:
            raise ValueError("PRICE_INVALID")

        if self.qty == 0 or self.side is None:
            self.side, self.qty, self.avg_price = side, quantity, price
            return

        if side == self.side:
# assert self.avg_price is not None
            self.avg_price = ((self.avg_price * self.qty) + (price * quantity)) / (self.qty + quantity)
            self.qty += quantity
            return

        if quantity < self.qty:
            self.qty -= quantity
            return
        if quantity == self.qty:
            self.side, self.qty, self.avg_price = None, 0, None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> PositionAggregate:
        return PositionAggregate(self.instrument_id, self.side, self.qty, self.avg_price)
