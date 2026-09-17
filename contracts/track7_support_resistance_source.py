"""Authoritative Support/Resistance source contract for Track7."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track7SupportResistanceObservation:
    """One externally authoritative support/resistance observation."""

    support: Decimal
    resistance: Decimal
    observed_at: datetime
    source: str
    definition: str
    window: str
    calculation_version: str

    def __post_init__(self) -> None:
        if self.support <= 0 or self.resistance <= 0:
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_LEVEL_INVALID")
        if self.support > self.resistance:
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_ORDER_INVALID")
        if not self.source.strip():
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_SOURCE_REQUIRED")
        if not self.definition.strip():
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_DEFINITION_REQUIRED")
        if not self.window.strip():
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_WINDOW_REQUIRED")
        if not self.calculation_version.strip():
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_VERSION_REQUIRED")


class Track7SupportResistanceProvider(Protocol):
    """Port for a source that owns the Track7 level definition and data."""

    def get_support_resistance(
        self, *, symbol: str, observed_at: datetime, current_price: Decimal
    ) -> Track7SupportResistanceObservation | None: ...
