from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.track6_volatility_source import Track6VolatilitySnapshot


class KISTrack6ATMVolatilitySource:
    """Authoritative ATM IV source for Track6."""

    def __init__(self, *, option_master: Any, option_iv_source: Any) -> None:
        self.option_master = option_master
        self.option_iv_source = option_iv_source
        self._session_date = None
        self._baseline = None
        self._baseline_strike = None
        self._baseline_expiry = None

    def reset_for_new_session(self, session_date) -> None:
        if self._session_date != session_date:
            self._session_date = session_date
            self._baseline = None
            self._baseline_strike = None
            self._baseline_expiry = None

    def _atm_strike(self, *, expiry: str, current_price: Decimal) -> Decimal | None:
        identities = self.option_master.list_contract_identities(expiry=expiry)
        strikes = sorted({
            Decimal(str(i.strike))
            for i in identities
            if str(getattr(i, "option_type", "")).upper() in {"CALL", "PUT"}
            and getattr(i, "strike", None) is not None
        })
        return min(strikes, key=lambda x: (abs(x-current_price), x)) if strikes else None

    def _iv(self, *, expiry: str, option_type: str, strike: Decimal):
        get_observation = getattr(self.option_iv_source, "get_observation", None)
        if callable(get_observation):
            record = get_observation(expiry=expiry, option_type=option_type, strike=strike)
            if record is not None:
                value = Decimal(str(record.implied_volatility))
                return (value, str(record.source)) if value > 0 else None
        value = self.option_iv_source.get_iv(expiry=expiry, option_type=option_type, strike=strike)
        if value is None:
            return None
        value = Decimal(str(value))
        if value <= 0:
            return None
        get_source = getattr(self.option_iv_source, "get_iv_source", None)
        source = get_source(expiry=expiry, option_type=option_type, strike=strike) if callable(get_source) else None
        return value, str(source or getattr(self.option_iv_source, "authoritative_source", "") or "KIS:H0IOCNT0")

    def snapshot(self, *, expiry: str, current_price: Decimal, observed_at: datetime):
        self.reset_for_new_session(observed_at.date())
        strike = self._atm_strike(expiry=expiry, current_price=current_price)
        if strike is None:
            return None
        call = self._iv(expiry=expiry, option_type="CALL", strike=strike)
        put = self._iv(expiry=expiry, option_type="PUT", strike=strike)
        if call is None or put is None or call[1] != put[1]:
            return None
        current = (call[0] + put[0]) / Decimal("2")
        if self._baseline is None:
            self._baseline = current
            self._baseline_strike = strike
            self._baseline_expiry = expiry
        if self._baseline_strike != strike or self._baseline_expiry != expiry:
            return None
        return Track6VolatilitySnapshot(
            active_vol=current / Decimal("100"),
            base_vol=self._baseline / Decimal("100"),
            call_iv=call[0],
            put_iv=put[0],
            strike=strike,
            expiry=expiry,
            observed_at=observed_at,
            source=call[1],
        )
