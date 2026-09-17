from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from typing import Iterable
from contracts.position_provenance import PositionLotCloseEvent, PositionLotProvenance

class VirtualPositionLotStore:
    """Authoritative execution-created position lots with immutable provenance."""
    def __init__(self) -> None:
        self._lots: dict[str, PositionLotProvenance] = {}
        self._history: list[PositionLotProvenance] = []
        self._close_events: list[PositionLotCloseEvent] = []
        self._executions: dict[str, tuple] = {}

    def apply_execution(self, lot: PositionLotProvenance) -> None:
        lot.validate()
        fingerprint = (lot.instrument_id, lot.side, lot.opened_quantity,
                       lot.execution_timestamp, lot.strategy_id, lot.group_id,
                       lot.leg_id, lot.client_order_id, lot.position_role)
        prior = self._executions.get(lot.execution_id)
        if prior is not None:
            if prior != fingerprint:
                raise ValueError("POSITION_PROVENANCE_DUPLICATE_CONFLICT")
            return
        self._executions[lot.execution_id] = fingerprint
        opposite = "SELL" if lot.side == "BUY" else "BUY"
        remaining = lot.remaining_quantity
        for key, current in self._ordered_open_lots(lot.instrument_id, opposite):
            if remaining <= 0:
                break
            consumed = min(remaining, current.remaining_quantity)
            self._lots[key] = replace(current, remaining_quantity=current.remaining_quantity - consumed)
            self._close_events.append(PositionLotCloseEvent(lot.execution_id, current.execution_id, consumed, lot.execution_timestamp))
            remaining -= consumed
        if remaining > 0:
            opened = replace(lot, opened_quantity=remaining, remaining_quantity=remaining)
            self._lots[lot.execution_id] = opened
            self._history.append(opened)

    def apply_open(self, lot: PositionLotProvenance) -> None:
        self.apply_execution(lot)

    def apply_close(self, execution_id: str, instrument_id: str, side: str, quantity: int, execution_timestamp: datetime) -> None:
        raise NotImplementedError("POSITION_LOT_CLOSE_REQUIRES_EXECUTION_PROVENANCE")

    def _ordered_open_lots(self, instrument_id: str, side: str) -> Iterable[tuple[str, PositionLotProvenance]]:
        return sorted(((k, v) for k, v in self._lots.items() if v.instrument_id == instrument_id and v.side == side and v.remaining_quantity > 0), key=lambda item: (item[1].execution_timestamp, item[1].execution_id))

    def open_lots(self) -> tuple[PositionLotProvenance, ...]:
        return tuple(sorted((lot for lot in self._lots.values() if lot.remaining_quantity > 0), key=lambda x: (x.instrument_id, x.execution_timestamp, x.execution_id)))

    def lots_for_role(self, role) -> tuple[PositionLotProvenance, ...]:
        return tuple(lot for lot in self.open_lots() if lot.position_role == role)

    def close_events(self) -> tuple[PositionLotCloseEvent, ...]:
        return tuple(self._close_events)

    def history(self) -> tuple[PositionLotProvenance, ...]:
        return tuple(self._history)
