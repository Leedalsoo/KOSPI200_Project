from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from core.option.option_master import KisOptionContractIdentity
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


class OptionIdentityLookup(Protocol):
    def get_contract_identity(self, shrn_iscd: str) -> KisOptionContractIdentity | None: ...


class KISOptionHistoricalRecorder:
    """Normalize authoritative KIS option observations into the historical store."""

    def __init__(self, store: HistoricalMarketStore, identity_lookup: OptionIdentityLookup) -> None:
        self._store = store
        self._identity_lookup = identity_lookup

    @staticmethod
    def _timestamp(session_date: str | date, observed_hour: str) -> str:
        day = session_date if isinstance(session_date, date) else date.fromisoformat(
            str(session_date).replace("/", "-")
        )
        raw = str(observed_hour).strip()
        if len(raw) not in (6, 9):
            raise ValueError("INVALID_KIS_OBSERVED_TIME")
        if len(raw) == 9:
            parsed = datetime.strptime(raw, "%H%M%S%f")
        else:
            parsed = datetime.strptime(raw, "%H%M%S")
        return f"{day.isoformat()}T{parsed.time().isoformat(timespec="milliseconds")}" 

    def record(
        self,
        observation: KisIndexOptionMarketObservation,
        *,
        session_date: str | date,
        seq_id: int,
        source: str = "KIS_INDEX_OPTION_WS",
        underlying_price: Decimal | float | None = None,
        underlying_state: object | None = None,
        underlying_sequence: int = 0,
    ) -> ReferenceCanonicalMarketTick:
        identity = self._identity_lookup.get_contract_identity(observation.shrn_iscd)
        if identity is None or identity.option_type is None or identity.strike is None:
            raise ValueError("AUTHORITATIVE_OPTION_IDENTITY_REQUIRED")
        underlying = underlying_state
        if underlying_price is not None and underlying is None:
            raise ValueError("AUTHORITATIVE_UNDERLYING_STATE_REQUIRED")
        tick = ReferenceCanonicalMarketTick(
            timestamp=self._timestamp(session_date, observation.observed_hour),
            underlying_price=float(underlying_price) if underlying_price is not None else None,
            underlying_symbol=underlying.symbol if underlying is not None else "",
            underlying_observed_hour=underlying.observed_hour if underlying is not None else "",
            underlying_source=underlying.source if underlying is not None else "",
            strike_price=float(identity.strike),
            option_type=identity.option_type,
            contract_multiplier=(
                float(identity.contract_multiplier)
                if identity.contract_multiplier is not None
                else None
            ),
            bid_price=float(observation.bid_price or 0),
            ask_price=float(observation.ask_price or 0),
            last_price=float(observation.last_price or 0),
            volume=int(observation.volume or 0),
            seq_id=seq_id,
            expiry=identity.expiry,
            symbol=identity.shrn_iscd,
            option_observed_hour=observation.observed_hour,
            option_source=observation.source,
            underlying_sequence=underlying_sequence,
        )
        self._store.append(tick, source=source)
        return tick
