from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.kis_index_price_source import KISIndexPriceObservation
from contracts.track3_runtime_input_source import Track3RuntimeInput
from contracts.types import MarketObservation


@dataclass(frozen=True)
class _FuturesPoint:
    observed_at: datetime
    price: Decimal
    ask: Decimal | None
    bid: Decimal | None


@dataclass(frozen=True)
class _IndexPoint:
    observed_at: datetime
    price: Decimal


class KISTrack3RuntimeInputSource:
    """Authoritative Track3 source from KIS futures/index/option observations."""

    source_name = "KIS:Track3:FuturesIndexBasis+OptionObservation"
    _FUTURES_SOURCES = {"KIS:H0IFCNT0", "KIS:H0IFASP0"}
    _INDEX_SOURCES = {"KIS:FHPUP02100000:2001", "KIS:H0UPCNT0"}
    _MAX_MATCH_SECONDS = 2.0
    _HISTORY_SIZE = 512
    _KST = ZoneInfo("Asia/Seoul")

    def __init__(
        self,
        *,
        initial_futures: Iterable[KisIndexFuturesMarketObservation] = (),
        initial_index: Iterable[KISIndexPriceObservation] = (),
        initial_options: Iterable[MarketObservation] = (),
    ) -> None:
        self._futures: deque[_FuturesPoint] = deque(maxlen=self._HISTORY_SIZE)
        self._index: deque[_IndexPoint] = deque(maxlen=self._HISTORY_SIZE)
        self._options: dict[str, list[tuple[datetime, MarketObservation]]] = defaultdict(list)
        self._fees: dict[datetime, Decimal] = {}
        self._premium: dict[datetime, Decimal] = {}
        self._option_quantities: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        self._common_analytics: dict[datetime, tuple[float, float, str]] = {}
        for item in initial_futures:
            self.update_futures(item, session_date=item.observed_at.date() if hasattr(item, "observed_at") else None)
        for item in initial_index:
            self.update_index(item)
        for item in initial_options:
            self.update_option(item)

    def update_futures(self, observation: KisIndexFuturesMarketObservation, *, session_date) -> None:
        if observation.source not in self._FUTURES_SOURCES or observation.price is None:
            return
        if not observation.shrn_iscd.strip() or not session_date:
            raise ValueError("TRACK3_FUTURES_SESSION_DATE_REQUIRED")
        raw = observation.observed_hour.strip()
        if len(raw) == 6:
            parsed = datetime.strptime(raw, "%H%M%S")
        elif len(raw) == 9:
            parsed = datetime.strptime(raw, "%H%M%S%f")
        else:
            raise ValueError("TRACK3_FUTURES_OBSERVED_HOUR_INVALID")
        observed_at = datetime.combine(session_date, parsed.time())
        if observation.price <= 0:
            return
        self._futures.append(
            _FuturesPoint(observed_at, observation.price, observation.ask_price, observation.bid_price)
        )
        self._futures = deque(
            sorted(self._futures, key=lambda item: item.observed_at),
            maxlen=self._HISTORY_SIZE,
        )

    def update_index(self, observation: KISIndexPriceObservation) -> None:
        if observation.underlying_symbol != "KOSPI200" or observation.index_code != "2001":
            raise ValueError("TRACK3_INDEX_IDENTITY_MISMATCH")
        if observation.source not in self._INDEX_SOURCES:
            raise ValueError("TRACK3_INDEX_SOURCE_REQUIRED")
        if observation.price <= 0:
            return
        self._index.append(_IndexPoint(observation.observed_at, observation.price))
        self._index = deque(
            sorted(self._index, key=lambda item: item.observed_at),
            maxlen=self._HISTORY_SIZE,
        )

    def update_option(self, observation: MarketObservation) -> None:
        observed_at = observation.observed_at or observation.collected_at
        identity = observation.contract
        if observed_at is None or str(identity.option_type).upper() not in {"CALL", "PUT"}:
            return
        if identity.contract_multiplier is None or identity.contract_multiplier <= 0:
            return
        if observation.quote.last is None or observation.quote.last <= 0:
            return
        self._options[str(identity.instrument_id)].append((observed_at, observation))
        self._options[str(identity.instrument_id)].sort(key=lambda item: item[0])

    def set_common_analytics(
        self,
        *,
        observed_at: datetime,
        active_vol: float,
        base_vol: float,
        current_regime: str,
    ) -> None:
        if active_vol <= 0 or base_vol <= 0 or not str(current_regime).strip():
            raise ValueError("TRACK3_COMMON_ANALYTICS_INVALID")
        self._common_analytics[observed_at] = (
            float(active_vol),
            float(base_vol),
            str(current_regime),
        )

    def set_execution_totals(
        self,
        *,
        observed_at: datetime,
        total_fees: Decimal,
        premium_spent: Decimal,
    ) -> None:
        if total_fees < 0 or premium_spent < 0:
            raise ValueError("TRACK3_EXECUTION_TOTALS_INVALID")
        self._fees[observed_at] = total_fees
        self._premium[observed_at] = premium_spent

    def set_option_quantity(
        self,
        *,
        instrument_id: str,
        observed_at: datetime,
        quantity: int,
    ) -> None:
        if not str(instrument_id).strip() or quantity <= 0:
            raise ValueError("TRACK3_OPTION_QUANTITY_INVALID")
        values = self._option_quantities[str(instrument_id)]
        values.append((observed_at, int(quantity)))
        values.sort(key=lambda item: item[0])

    def get_input(self, symbol: str, observed_at: datetime) -> Track3RuntimeInput | None:
        if str(symbol).strip() != "KOSPI200":
            return None
        futures = self._latest_futures(observed_at)
        index = self._latest_index(observed_at)
        common = self._common_analytics.get(observed_at)
        if futures is None or index is None or common is None:
            return None

        active_vol, base_vol, regime = common
        current_basis = self._matched_basis(futures, index)
        basis_points = self._basis_history(observed_at)
        if current_basis is None or len(basis_points) < 10:
            return None
        if active_vol <= 0 or base_vol <= 0:
            return None

        index_prices = self._index_prices(observed_at)
        if len(index_prices) < 2:
            return None
        price_change_rate = float(
            index_prices[-1] / index_prices[-2] - Decimal("1")
        ) if index_prices[-2] else 0.0

        bid_ask_spread = (
            float(futures.ask - futures.bid)
            if futures.bid is not None
            and futures.ask is not None
            and futures.bid > 0
            and futures.ask >= futures.bid
            else 0.0
        )
        mean_basis = sum(basis_points, Decimal("0")) / Decimal(len(basis_points))
        spread_normalizing = (
            abs(float(current_basis - mean_basis))
            <= abs(float(basis_points[-2] - mean_basis))
        )

        options_legs = self._option_legs(observed_at)
        if not options_legs:
            return None
        total_fees = self._latest_total(self._fees, observed_at)
        premium_spent = self._latest_total(self._premium, observed_at)
        if total_fees is None or premium_spent is None:
            return None
        multipliers = {float(leg["contract_multiplier"]) for leg in options_legs}
        if len(multipliers) != 1:
            return None

        return Track3RuntimeInput(
            observed_at=observed_at,
            spread_history=tuple(float(value) for value in basis_points),
            active_vol=active_vol,
            base_vol=base_vol,
            price_change_rate=price_change_rate,
            bid_ask_spread=bid_ask_spread,
            gap_pct=price_change_rate,
            is_gap=False,
            market_stable=regime not in {"EXTREME_MOVE", "HIGH_VOLATILITY"},
            spread_normalizing=spread_normalizing,
            allow_size_up=regime == "NORMAL" and spread_normalizing,
            total_fees=total_fees,
            premium_spent=premium_spent,
            options_legs=options_legs,
            contract_multiplier=multipliers.pop(),
            source=self.source_name,
        )

    @classmethod
    def _comparison_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(cls._KST).replace(tzinfo=None)

    def _latest_futures(self, observed_at: datetime) -> _FuturesPoint | None:
        comparison_at = self._comparison_time(observed_at)
        values = [item for item in self._futures if item.observed_at <= comparison_at]
        return values[-1] if values else None

    def _latest_index(self, observed_at: datetime) -> _IndexPoint | None:
        comparison_at = self._comparison_time(observed_at)
        values = [item for item in self._index if item.observed_at <= comparison_at]
        return values[-1] if values else None

    def _matched_basis(
        self,
        futures: _FuturesPoint,
        index: _IndexPoint,
    ) -> Decimal | None:
        if abs((futures.observed_at - index.observed_at).total_seconds()) > self._MAX_MATCH_SECONDS:
            return None
        return futures.price - index.price

    def _basis_history(self, observed_at: datetime) -> tuple[Decimal, ...]:
        points: list[Decimal] = []
        comparison_at = self._comparison_time(observed_at)
        for future in self._futures:
            if future.observed_at > comparison_at:
                continue
            index = self._nearest_index(future.observed_at)
            if index is None:
                continue
            basis = self._matched_basis(future, index)
            if basis is not None:
                points.append(basis)
        return tuple(points)

    def _nearest_index(self, observed_at: datetime) -> _IndexPoint | None:
        if not self._index:
            return None
        comparison_at = self._comparison_time(observed_at)
        candidate = min(
            self._index,
            key=lambda item: abs((item.observed_at - comparison_at).total_seconds()),
        )
        return (
            candidate
            if abs((candidate.observed_at - comparison_at).total_seconds()) <= self._MAX_MATCH_SECONDS
            else None
        )

    def _index_prices(self, observed_at: datetime) -> tuple[Decimal, ...]:
        comparison_at = self._comparison_time(observed_at)
        return tuple(item.price for item in self._index if item.observed_at <= comparison_at)

    def _option_legs(self, observed_at: datetime) -> tuple[dict[str, object], ...]:
        legs: list[dict[str, object]] = []
        comparison_at = self._comparison_time(observed_at)
        for values in self._options.values():
            candidates = [item for item in values if self._comparison_time(item[0]) <= comparison_at]
            if not candidates:
                continue
            item = candidates[-1][1]
            identity = item.contract
            quantity = self._latest_option_quantity(
                str(identity.instrument_id),
                observed_at,
            )
            if quantity is None:
                continue
            legs.append(
                {
                    "instrument_id": identity.instrument_id,
                    "strike": float(identity.strike),
                    "price": float(item.quote.last),
                    "current_market_price": float(item.quote.last),
                    "qty": quantity,
                    "side": "BUY",
                    "type": str(identity.option_type).upper(),
                    "expiry": str(identity.expiry),
                    "contract_multiplier": float(identity.contract_multiplier),
                    "source": f"HistoricalObservationStore:{item.source}",
                }
            )
        return tuple(legs)

    @staticmethod
    def _latest_total(values: dict[datetime, Decimal], observed_at: datetime) -> float | None:
        candidates = sorted(value for timestamp, value in values.items() if timestamp <= observed_at)
        return float(candidates[-1]) if candidates else None

    def _latest_option_quantity(self, instrument_id: str, observed_at: datetime) -> int | None:
        comparison_at = self._comparison_time(observed_at)
        values = self._option_quantities.get(str(instrument_id), ())
        candidates = [quantity for timestamp, quantity in values if self._comparison_time(timestamp) <= comparison_at]
        return candidates[-1] if candidates else None
