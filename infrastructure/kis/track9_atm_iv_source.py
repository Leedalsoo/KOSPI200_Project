from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from contracts.track9_iv_event_materializer import Track9ATMIVSnapshot, Track9ATMIVSource
from contracts.track9_iv_timeseries import Track9IVObservation, Track9IVTimeSeriesSource


class KISTrack9ATMIVSource(Track9ATMIVSource):
    """Resolve ATM IV from authoritative Option Master and KIS IV history."""

    def __init__(self, *, option_master: Any, history_source: Track9IVTimeSeriesSource) -> None:
        self.option_master = option_master
        self.history_source = history_source

    def _atm_strike(self, *, expiry: str, current_price: Decimal) -> Decimal | None:
        identities = self.option_master.list_contract_identities(expiry=expiry)
        strikes = sorted({
            identity.strike
            for identity in identities
            if identity.option_type in {"CALL", "PUT"} and identity.strike is not None
        })
        if not strikes:
            return None
        return min(strikes, key=lambda strike: (abs(strike - current_price), strike))

    def _latest(self, *, symbol: str, expiry: str, option_type: str,
                strike: Decimal, observed_at: datetime) -> Track9IVObservation | None:
        start = datetime.combine(observed_at.date(), datetime.min.time())
        end = observed_at + timedelta(microseconds=1)
        records = self.history_source.query(
            symbol=symbol, expiry=expiry, option_type=option_type,
            strike=strike, start=start, end=end,
        )
        return records[-1] if records else None

    def snapshot(self, *, symbol: str, expiry: str, current_price: Decimal,
                 observed_at: datetime) -> Track9ATMIVSnapshot | None:
        strike = self._atm_strike(expiry=expiry, current_price=current_price)
        if strike is None:
            return None
        call_identity = self.option_master.find_contract_identity(expiry, "CALL", strike)
        put_identity = self.option_master.find_contract_identity(expiry, "PUT", strike)
        if call_identity is None or put_identity is None:
            return None
        call = self._latest(symbol=call_identity.shrn_iscd, expiry=call_identity.expiry,
                            option_type="CALL", strike=strike, observed_at=observed_at)
        put = self._latest(symbol=put_identity.shrn_iscd, expiry=put_identity.expiry,
                           option_type="PUT", strike=strike, observed_at=observed_at)
        if call is None or put is None:
            return None
        if call.observed_at != put.observed_at:
            return None
        if call.source != "KIS:H0IOCNT0" or put.source != "KIS:H0IOCNT0":
            return None
        return Track9ATMIVSnapshot(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            call_iv=call.implied_volatility,
            put_iv=put.implied_volatility,
            observed_at=call.observed_at,
            source="KIS:H0IOCNT0",
        )
