from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.position_provenance import (
    PositionLotCloseEvent,
    PositionLotProvenance,
    PositionRole,
)
from contracts.types import BrokerOrderCommand, ExecutionReport


@dataclass(frozen=True)
class PositionLotApplyResult:
    execution_id: str
    opened_lots: tuple[PositionLotProvenance, ...]
    close_events: tuple[PositionLotCloseEvent, ...]
    idempotent: bool = False


class VirtualPositionLotStore:
    """Authoritative Virtual open-lot provenance with FIFO close/reversal rules."""

    def __init__(self) -> None:
        self._open: dict[str, list[PositionLotProvenance]] = {}
        self._history: list[PositionLotProvenance | PositionLotCloseEvent] = []
        self._applied: dict[str, tuple[object, ...]] = {}

    @staticmethod
    def _fingerprint(command: BrokerOrderCommand, report: ExecutionReport, run_id: str, role: PositionRole) -> tuple[object, ...]:
        identity = command.instrument_identity
        return (
            run_id, command.client_order_id, command.instrument_id, command.side,
            report.execution_id, report.filled_quantity, report.execution_price,
            report.execution_timestamp, identity, role,
        )

    @staticmethod
    def _validate(command: BrokerOrderCommand, report: ExecutionReport, run_id: str, role: PositionRole) -> None:
        if not run_id.strip() or not command.strategy_id or not command.group_id or not command.leg_id:
            raise ValueError("POSITION_PROVENANCE_REQUIRED")
        if not report.execution_id or not report.execution_timestamp:
            raise ValueError("POSITION_PROVENANCE_EXECUTION_REQUIRED")
        if command.client_order_id != report.client_order_id:
            raise ValueError("POSITION_PROVENANCE_CLIENT_ORDER_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"} or report.filled_quantity <= 0:
            raise ValueError("POSITION_PROVENANCE_FILL_INVALID")
        identity = command.instrument_identity
        if identity is None or identity.instrument_id != command.instrument_id:
            raise ValueError("POSITION_PROVENANCE_IDENTITY_INVALID")
        if identity.contract_multiplier is None or identity.contract_multiplier <= 0 or not identity.identity_source:
            raise ValueError("POSITION_PROVENANCE_IDENTITY_REQUIRED")
        if not isinstance(role, PositionRole):
            raise ValueError("POSITION_PROVENANCE_ROLE_REQUIRED")

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport, *, run_id: str, position_role: PositionRole) -> PositionLotApplyResult:
        self._validate(command, report, run_id, position_role)
        execution_id = report.execution_id
        fingerprint = self._fingerprint(command, report, run_id, position_role)
        prior = self._applied.get(execution_id)
        if prior is not None:
            if prior != fingerprint:
                raise ValueError("POSITION_PROVENANCE_DUPLICATE_CONFLICT")
            return PositionLotApplyResult(execution_id, (), (), True)

        identity = command.instrument_identity
        assert identity is not None and identity.contract_multiplier is not None and identity.identity_source
        quantity = report.filled_quantity
        close_events: list[PositionLotCloseEvent] = []
        lots = self._open.setdefault(command.instrument_id, [])
        opposite = "SELL" if command.side == "BUY" else "BUY"
        remaining = quantity
        for index, lot in enumerate(list(lots)):
            if remaining == 0:
                break
            if lot.side != opposite or lot.remaining_quantity == 0:
                continue
            consumed = min(remaining, lot.remaining_quantity)
            lots[index] = PositionLotProvenance(
                **{**lot.__dict__, "remaining_quantity": lot.remaining_quantity - consumed}
            )
            close_events.append(PositionLotCloseEvent(execution_id, lot.execution_id, consumed, report.execution_timestamp))
            remaining -= consumed

        self._open[command.instrument_id] = [lot for lot in lots if lot.remaining_quantity > 0]
        opened: list[PositionLotProvenance] = []
        if remaining > 0:
            lot = PositionLotProvenance(
                run_id=run_id, instrument_id=command.instrument_id,
                strategy_id=command.strategy_id, group_id=command.group_id,
                leg_id=command.leg_id, client_order_id=command.client_order_id,
                execution_id=execution_id, side=command.side,
                opened_quantity=remaining, remaining_quantity=remaining,
                execution_timestamp=report.execution_timestamp,
                instrument_identity=identity,
                contract_multiplier=identity.contract_multiplier,
                identity_source=identity.identity_source,
                position_role=position_role,
            )
            lot.validate()
            self._open.setdefault(command.instrument_id, []).append(lot)
            opened.append(lot)
            self._history.append(lot)
        self._history.extend(close_events)
        self._applied[execution_id] = fingerprint
        return PositionLotApplyResult(execution_id, tuple(opened), tuple(close_events))

    def open_lots(self, instrument_id: str | None = None) -> tuple[PositionLotProvenance, ...]:
        if instrument_id is None:
            lots = [lot for group in self._open.values() for lot in group]
        else:
            lots = list(self._open.get(instrument_id, ()))
        return tuple(sorted(lots, key=lambda lot: (lot.execution_timestamp, lot.execution_id)))

    def history(self) -> tuple[PositionLotProvenance | PositionLotCloseEvent, ...]:
        return tuple(self._history)
