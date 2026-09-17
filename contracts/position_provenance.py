from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from contracts.types import OptionInstrumentIdentity


class PositionRole(StrEnum):
    NONE = "NONE"
    OVERNIGHT_INSURANCE = "OVERNIGHT_INSURANCE"
    EVENT_INSURANCE = "EVENT_INSURANCE"
    REHEDGE_INSURANCE = "REHEDGE_INSURANCE"


@dataclass(frozen=True)
class PositionLotProvenance:
    """Immutable provenance of one execution-created position lot."""

    run_id: str
    instrument_id: str
    strategy_id: str
    group_id: str
    leg_id: str
    client_order_id: str
    execution_id: str
    side: str
    opened_quantity: int
    remaining_quantity: int
    execution_timestamp: datetime
    instrument_identity: OptionInstrumentIdentity
    contract_multiplier: Decimal
    identity_source: str
    position_role: PositionRole

    def validate(self) -> None:
        required = {
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "strategy_id": self.strategy_id,
            "group_id": self.group_id,
            "leg_id": self.leg_id,
            "client_order_id": self.client_order_id,
            "execution_id": self.execution_id,
            "identity_source": self.identity_source,
        }
        if any(not isinstance(value, str) or not value.strip() for value in required.values()):
            raise ValueError("POSITION_PROVENANCE_REQUIRED")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_PROVENANCE_SIDE_INVALID")
        if self.opened_quantity <= 0 or self.remaining_quantity <= 0:
            raise ValueError("POSITION_PROVENANCE_QUANTITY_INVALID")
        if self.remaining_quantity > self.opened_quantity:
            raise ValueError("POSITION_PROVENANCE_REMAINING_GT_OPENED")
        if self.execution_timestamp is None:
            raise ValueError("POSITION_PROVENANCE_TIMESTAMP_REQUIRED")
        if self.contract_multiplier <= 0:
            raise ValueError("POSITION_PROVENANCE_MULTIPLIER_INVALID")
        identity = self.instrument_identity
        if identity is None or identity.instrument_id != self.instrument_id:
            raise ValueError("POSITION_PROVENANCE_IDENTITY_INVALID")
        if identity.contract_multiplier != self.contract_multiplier:
            raise ValueError("POSITION_PROVENANCE_MULTIPLIER_MISMATCH")
        if identity.identity_source != self.identity_source:
            raise ValueError("POSITION_PROVENANCE_IDENTITY_SOURCE_MISMATCH")
        if not isinstance(self.position_role, PositionRole):
            raise ValueError("POSITION_PROVENANCE_ROLE_REQUIRED")


@dataclass(frozen=True)
class PositionLotCloseEvent:
    """Immutable record of quantity consumed from an existing lot."""

    execution_id: str
    source_lot_execution_id: str
    quantity: int
    execution_timestamp: datetime


__all__ = ["PositionRole", "PositionLotProvenance", "PositionLotCloseEvent"]
