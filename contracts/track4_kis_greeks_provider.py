from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Mapping, Protocol


class Track4KisGreeksSourceInvalid(ValueError):
    """Raised when a KIS option Greeks snapshot is missing or invalid."""


@dataclass(frozen=True)
class Track4KisGreeksSnapshot:
    instrument_id: str
    observed_at: str
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    implied_volatility: Decimal
    source: str = "KIS:H0IOCNT0"

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise Track4KisGreeksSourceInvalid("instrument_id is required")
        if not self.observed_at.strip():
            raise Track4KisGreeksSourceInvalid("observed_at is required")
        if not self.source.strip():
            raise Track4KisGreeksSourceInvalid("source is required")
        for name, value in (
            ("delta", self.delta),
            ("gamma", self.gamma),
            ("theta", self.theta),
            ("implied_volatility", self.implied_volatility),
        ):
            if not value.is_finite():
                raise Track4KisGreeksSourceInvalid(f"{name} must be finite")
        if self.implied_volatility <= 0:
            raise Track4KisGreeksSourceInvalid("implied_volatility must be positive")


class Track4KisGreeksProvider(Protocol):
    @property
    def snapshot(self) -> Track4KisGreeksSnapshot: ...
    def current_delta(self) -> Decimal: ...
    def current_gamma(self) -> Decimal: ...
    def current_theta(self) -> Decimal: ...
    def active_vol(self) -> Decimal: ...


class KISIndexOptionGreeksProvider:
    """Read-only projection of the KIS index-option realtime trade payload.

    KIS H0IOCNT0 supplies delta, gamma, theta and HTS implied volatility directly.
    This adapter does not calculate Greeks, infer IV, or introduce a risk-free-rate
    assumption. The payload must already be the authoritative KIS option event.
    """

    def __init__(self, snapshot: Track4KisGreeksSnapshot):
        self._snapshot = snapshot

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        instrument_id: str,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> "KISIndexOptionGreeksProvider":
        def decimal_field(name: str) -> Decimal:
            raw = payload.get(name)
            if raw is None or raw == "":
                raise Track4KisGreeksSourceInvalid(f"{name} is missing")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError) as exc:
                raise Track4KisGreeksSourceInvalid(f"{name} is invalid") from exc
            if not value.is_finite():
                raise Track4KisGreeksSourceInvalid(f"{name} must be finite")
            return value

        return cls(
            Track4KisGreeksSnapshot(
                instrument_id=instrument_id,
                observed_at=observed_at,
                delta=decimal_field("delta"),
                gamma=decimal_field("gama"),
                theta=decimal_field("theta"),
                implied_volatility=decimal_field("hts_ints_vltl"),
                source=source,
            )
        )

    def current_delta(self) -> Decimal:
        return self._snapshot.delta

    def current_gamma(self) -> Decimal:
        return self._snapshot.gamma

    def current_theta(self) -> Decimal:
        return self._snapshot.theta

    def active_vol(self) -> Decimal:
        return self._snapshot.implied_volatility

    @property
    def snapshot(self) -> Track4KisGreeksSnapshot:
        return self._snapshot
