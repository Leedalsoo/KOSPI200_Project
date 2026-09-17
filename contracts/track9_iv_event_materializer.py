from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Protocol


SESSION_START = time(9, 0)
SPIKE_THRESHOLD = Decimal("4")
CRUSH_THRESHOLD = Decimal("-3")


@dataclass(frozen=True)
class Track9ATMIVSnapshot:
    """Authoritative ATM CALL/PUT IV pair selected from listed contracts."""
    symbol: str
    expiry: str
    strike: Decimal
    call_iv: Decimal
    put_iv: Decimal
    observed_at: datetime
    source: str


class Track9ATMIVSource(Protocol):
    """Authoritative source for an ATM CALL/PUT snapshot."""

    def snapshot(
        self,
        *,
        symbol: str,
        expiry: str,
        current_price: Decimal,
        observed_at: datetime,
    ) -> Track9ATMIVSnapshot | None: ...


@dataclass(frozen=True)
class Track9IVEventValues:
    baseline_iv: Decimal | None
    current_iv: Decimal | None
    iv_spike: Decimal | None
    iv_crush: Decimal | None
    baseline_strike: Decimal | None
    current_strike: Decimal | None
    baseline_observed_at: datetime | None
    source: str | None
    status: str


class Track9IVEventMaterializer:
    """Materialize Track9 IV event values without inventing missing observations."""

    def __init__(self) -> None:
        self._session_date: str | None = None
        self._baseline: Track9ATMIVSnapshot | None = None

    def reset_for_new_session(self, session_date: str) -> None:
        if self._session_date != session_date:
            self._session_date = session_date
            self._baseline = None

    @staticmethod
    def _average(snapshot: Track9ATMIVSnapshot) -> Decimal:
        return (snapshot.call_iv + snapshot.put_iv) / Decimal("2")

    @staticmethod
    def _validate(snapshot: Track9ATMIVSnapshot) -> None:
        if not snapshot.source:
            raise ValueError("TRACK9_IV_SOURCE_REQUIRED")
        if snapshot.call_iv <= 0 or snapshot.put_iv <= 0:
            raise ValueError("TRACK9_IV_INVALID")
        if snapshot.strike <= 0:
            raise ValueError("TRACK9_ATM_STRIKE_INVALID")

    def materialize(
        self,
        *,
        session_date: str,
        symbol: str,
        expiry: str,
        current_price: Decimal,
        observed_at: datetime,
        source: Track9ATMIVSource,
    ) -> Track9IVEventValues:
        self.reset_for_new_session(session_date)
        snapshot = source.snapshot(
            symbol=symbol,
            expiry=expiry,
            current_price=current_price,
            observed_at=observed_at,
        )
        if snapshot is None:
            return Track9IVEventValues(None, None, None, None, None, None, None, None, "UNAVAILABLE")
        self._validate(snapshot)
        if not self._baseline and observed_at.time() == SESSION_START:
            self._baseline = snapshot
        if self._baseline is None:
            return Track9IVEventValues(None, None, None, None, None, snapshot.strike, None, snapshot.source, "BASELINE_UNAVAILABLE")
        baseline_iv = self._average(self._baseline)
        current_iv = self._average(snapshot)
        delta_pct = (current_iv - baseline_iv) * Decimal("100")
        return Track9IVEventValues(
            baseline_iv,
            current_iv,
            max(Decimal("0"), delta_pct),
            min(Decimal("0"), delta_pct),
            self._baseline.strike,
            snapshot.strike,
            self._baseline.observed_at,
            snapshot.source,
            "READY",
        )
