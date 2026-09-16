"""Authoritative derived-data providers for the Virtual Market runtime."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import erf, exp, log, sqrt
from typing import Any

from contracts.option_orderbook_source import OptionOrderBookSource
from contracts.volume_profile_source import VolumeProfileSource

@dataclass(frozen=True)
class RuntimeDataStatus:
    available: bool
    fresh: bool
    source: str
    reason: str | None = None

@dataclass(frozen=True)
class VirtualRuntimeData:
    as_of: datetime
    price: Decimal
    prices: tuple[Decimal, ...]
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    previous_close: Decimal
    active_vol: Decimal | None
    base_vol: Decimal | None
    option_iv: Decimal | None
    put_iv: Decimal | None
    option_delta: Decimal | None
    option_gamma: Decimal | None
    macro_regime: str | None
    event_upcoming: bool | None
    status: dict[str, RuntimeDataStatus]
    option_expiry: date | None = None
    days_to_expiry: int | None = None
    option_bid_qtys: tuple[Decimal, ...] | None = None
    option_ask_qtys: tuple[Decimal, ...] | None = None
    poc_price: Decimal | None = None

class VirtualRuntimeDataProvider:
    """Derive only from VMS observations and injected authoritative sources."""
    def __init__(self, market: Any, *, history_size: int = 50, option_expiry_source: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, volume_profile_source: VolumeProfileSource | None = None) -> None:
        self.market = market
        self.history_size = history_size
        self.option_expiry_source = option_expiry_source
        self.option_orderbook_source = option_orderbook_source
        self.volume_profile_source = volume_profile_source

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    @classmethod
    def _implied_vol(cls, spot: Decimal, strike: Decimal, premium: Decimal,
                     expiry: str, observed_at: datetime) -> Decimal | None:
        try:
            exp_dt = datetime.strptime(expiry, "%Y%m")
            exp_dt = exp_dt.replace(day=1)
            t = max(1.0 / 365.0, (exp_dt - observed_at).total_seconds() / 31536000.0)
            s, k, p = float(spot), float(strike), float(premium)
            if s <= 0 or k <= 0 or p <= 0:
                return None
            intrinsic = max(0.0, s - k)
            if p <= intrinsic:
                return None
            lo, hi = 1e-4, 5.0
            for _ in range(80):
                sigma = (lo + hi) / 2.0
                d1 = (log(s / k) + 0.5 * sigma * sigma * t) / (sigma * sqrt(t))
                d2 = d1 - sigma * sqrt(t)
                value = s * cls._norm_cdf(d1) - k * cls._norm_cdf(d2)
                if value > p:
                    hi = sigma
                else:
                    lo = sigma
            return Decimal(str(round((lo + hi) / 2.0, 8)))
        except (ValueError, OverflowError, ZeroDivisionError):
            return None

    def snapshot(self, tick: Any) -> VirtualRuntimeData:
        observed_at = datetime.fromisoformat(tick.timestamp)
        recent = tuple(self.market.recent_ticks[-self.history_size:])
        prices = tuple(Decimal(str(x.last_price)) for x in recent) or (Decimal(str(tick.last_price)),)
        price = Decimal(str(tick.last_price))
        high = max(prices)
        low = min(prices)
        open_price = prices[0]
        previous_close = prices[-2] if len(prices) >= 2 else prices[0]
        returns = tuple(abs(prices[i] / prices[i - 1] - 1) for i in range(1, len(prices)) if prices[i - 1])
        active_vol = (sum(returns, Decimal("0")) / Decimal(len(returns))) if returns else None
        base_vol = active_vol
        mid = (Decimal(str(tick.bid_price)) + Decimal(str(tick.ask_price))) / Decimal("2")
        iv = self._implied_vol(price, Decimal(str(tick.strike_price)), mid, tick.expiry, observed_at)
        put_quote = self.market.option_quotes.get(("PUT", float(tick.strike_price), tick.expiry))
        put_iv = Decimal(str(put_quote["iv"])) if put_quote is not None else None
        delta = gamma = None
        if iv is not None:
            s, k, sigma = float(price), float(tick.strike_price), float(iv)
            t = max(1.0 / 365.0, (datetime.strptime(tick.expiry, "%Y%m") - observed_at.replace(day=1)).total_seconds() / 31536000.0)
            d1 = (log(s / k) + 0.5 * sigma * sigma * t) / (sigma * sqrt(t))
            delta = Decimal(str(round(self._norm_cdf(d1), 8)))
            gamma = Decimal(str(round(exp(-0.5 * d1 * d1) / sqrt(2 * 3.141592653589793) / (s * sigma * sqrt(t)), 8)))
        scenario = self.market.scenario.active_config()
        base_volatility = float(scenario.get("base_volatility", 1.0))
        macro_regime = "HIGH_VOL" if base_volatility >= 2.0 else "NORMAL"
        shock_interval = max(1, int(scenario.get("shock_interval_days", 999999)))
        event_upcoming = (tick.seq_id % shock_interval) == 0
        option_expiry = None
        days_to_expiry = None
        expiry_status = RuntimeDataStatus(False, False, "OptionExpirySource", "OPTION_EXPIRY_SOURCE_UNAVAILABLE")
        if self.option_expiry_source is not None and getattr(tick, "symbol", None):
            option_expiry = self.option_expiry_source.resolve_expiry(tick.symbol)
            if option_expiry is not None:
                days_to_expiry = (option_expiry - observed_at.date()).days
                expiry_status = RuntimeDataStatus(True, True, "KIS.OptionMaster.expiry")
        option_bid_qtys = None
        option_ask_qtys = None
        orderbook_status = RuntimeDataStatus(
            False, False, "OptionOrderBookSource", "OPTION_ORDERBOOK_SOURCE_UNAVAILABLE"
        )
        symbol = getattr(tick, "symbol", None)
        poc_price = None
        poc_status = RuntimeDataStatus(
            False, False, "VolumeProfileSource", "VOLUME_PROFILE_SOURCE_UNAVAILABLE"
        )
        if self.volume_profile_source is not None and symbol:
            poc_price = self.volume_profile_source.get_poc(symbol)
            if poc_price is not None:
                poc_status = RuntimeDataStatus(
                    True, True, "KIS:H0IFCNT0:volume_profile"
                )
        if self.option_orderbook_source is not None and symbol:
            order_book = self.option_orderbook_source.get_order_book(symbol)
            if order_book is not None and order_book.symbol == symbol and order_book.is_complete():
                option_bid_qtys = order_book.bid_quantities
                option_ask_qtys = order_book.ask_quantities
                orderbook_status = RuntimeDataStatus(True, True, order_book.source)
            elif order_book is not None:
                orderbook_status = RuntimeDataStatus(
                    False, False, order_book.source, "OPTION_ORDERBOOK_IDENTITY_OR_DEPTH_MISMATCH"
                )

        status = {
            "tick": RuntimeDataStatus(True, True, "VMS.recent_ticks"),
            "ohlc_history": RuntimeDataStatus(len(prices) >= 1, True, "VMS.recent_ticks"),
            "iv_greeks": RuntimeDataStatus(iv is not None and put_iv is not None, iv is not None and put_iv is not None, "VMS.option_quotes", "OPTION_CHAIN_UNAVAILABLE" if iv is None or put_iv is None else None),
            "macro": RuntimeDataStatus(True, True, "VMS.scenario.active_config"),
            "event": RuntimeDataStatus(True, True, "VMS.scenario.shock_schedule"),
            "option_expiry": expiry_status,
            "option_orderbook": orderbook_status,
            "volume_profile_poc": poc_status,
        }
        return VirtualRuntimeData(
            observed_at, price, prices, open_price, high, low, previous_close,
            active_vol, base_vol, iv, put_iv, delta, gamma, macro_regime,
            event_upcoming, status, option_expiry, days_to_expiry, option_bid_qtys, option_ask_qtys, poc_price
        )


