"""Validated adapter for an authoritative Track7 support/resistance source."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts.track7_support_resistance_source import (
    Track7SupportResistanceObservation,
    Track7SupportResistanceProvider,
)


class Track7AuthoritativeSupportResistanceSource:
    """Expose only observations supplied by an injected authoritative source.

    This adapter deliberately performs no pivot, swing, high/low, or fallback
    calculation. The injected provider owns the definition and provenance.
    """

    source_name = "Track7.authoritative_support_resistance"

    def __init__(self, provider: Track7SupportResistanceProvider) -> None:
        if provider is None or not callable(getattr(provider, "get_support_resistance", None)):
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_PROVIDER_REQUIRED")
        self._provider = provider

    def get(self, *, symbol: str, observed_at: datetime, current_price: Any) -> Track7SupportResistanceObservation | None:
        observation = self._provider.get_support_resistance(
            symbol=symbol, observed_at=observed_at, current_price=current_price
        )
        if observation is None:
            return None
        if not isinstance(observation, Track7SupportResistanceObservation):
            raise TypeError("TRACK7_SUPPORT_RESISTANCE_OBSERVATION_REQUIRED")
        if observation.observed_at > observed_at:
            raise ValueError("TRACK7_SUPPORT_RESISTANCE_FUTURE_OBSERVATION")
        return observation

    @property
    def provider(self) -> Any:
        return self._provider
