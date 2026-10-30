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

    def preview_fill(self, *, side: str, quantity: int, price: Decimal) -> PositionAggregate:
        projected = LivePositionAggregate(self.instrument_id)
        projected.side = self.side
        projected.qty = self.qty
        projected.avg_price = self.avg_price
        projected.apply_fill(side=side, quantity=quantity, price=price)
        return projected.snapshot()

    def restore_snapshot(self, snapshot: PositionAggregate) -> None:
        if snapshot.instrument_id != self.instrument_id:
            raise ValueError("POSITION_SNAPSHOT_INSTRUMENT_MISMATCH")
        if snapshot.qty < 0 or (snapshot.qty == 0) != (snapshot.side is None):
            raise ValueError("POSITION_SNAPSHOT_STATE_INVALID")
        if snapshot.qty > 0 and snapshot.avg_price is None:
            raise ValueError("POSITION_SNAPSHOT_AVERAGE_PRICE_REQUIRED")
        self.side, self.qty, self.avg_price = snapshot.side, snapshot.qty, snapshot.avg_price

    def persistence_record(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "side": self.side,
            "qty": self.qty,
            "avg_price": str(self.avg_price) if self.avg_price is not None else None,
        }

    def restore_persistence_record(self, record: dict[str, object]) -> None:
        if str(record.get("instrument_id", "")) != self.instrument_id:
            raise ValueError("POSITION_SNAPSHOT_INSTRUMENT_MISMATCH")
        avg = record.get("avg_price")
        snapshot = PositionAggregate(
            instrument_id=self.instrument_id,
            side=record.get("side"),
            qty=int(record.get("qty", 0)),
            avg_price=Decimal(str(avg)) if avg is not None else None,
        )
        self.restore_snapshot(snapshot)

    def snapshot(self) -> PositionAggregate:
        return PositionAggregate(self.instrument_id, self.side, self.qty, self.avg_price)
