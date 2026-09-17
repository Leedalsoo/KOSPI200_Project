"""Authoritative derived-data providers for the Virtual Market runtime."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import erf, exp, log, sqrt
from typing import Any

from contracts.option_orderbook_source import OptionOrderBookSource
from contracts.volume_profile_source import VolumeProfileSource
from contracts.basis_source import BasisSource
from contracts.track2_market_metrics_source import Track2MarketMetricsSource
from contracts.track2_option_iv_source import Track2OptionIVSource
from application.composition.track7_calendar_source import Track7CalendarSource
from application.composition.track7_support_resistance_source import Track7AuthoritativeSupportResistanceSource

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
    basis: Decimal | None = None
    bbw_window: tuple[Decimal, ...] | None = None
    volume_window: tuple[Decimal, ...] | None = None
    ma_1m: Decimal | None = None
    ma_3m: Decimal | None = None
    ma_5m: Decimal | None = None
    ma_10m: Decimal | None = None
    is_new_week_start: bool | None = None
    is_expiry_day: bool | None = None
    is_week_end: bool | None = None
    order_timeout: bool | None = None
    support: Decimal | None = None
    resistance: Decimal | None = None

class VirtualRuntimeDataProvider:
    """Derive only from VMS observations and injected authoritative sources."""
    def __init__(self, market: Any, *, history_size: int = 50, option_expiry_source: Any | None = None, track7_order_timeout_source: Any | None = None, trading_calendar: Any | None = None, option_master: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None, track2_metrics_source: Track2MarketMetricsSource | None = None, track2_option_iv_source: Track2OptionIVSource | None = None, track7_support_resistance_source: Track7AuthoritativeSupportResistanceSource | None = None) -> None:
        self.market = market
        self.history_size = history_size
        self.option_expiry_source = option_expiry_source
        self.track7_order_timeout_source = track7_order_timeout_source
        self.trading_calendar = Track7CalendarSource(trading_calendar, option_master) if trading_calendar is not None else None
        self.option_orderbook_source = option_orderbook_source
        self.volume_profile_source = volume_profile_source
        self.basis_source = basis_source
        self.track2_metrics_source = track2_metrics_source
        self.track2_option_iv_source = track2_option_iv_source
        self.track7_support_resistance_source = track7_support_resistance_source

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

    @staticmethod
    def _time_window_ma(recent: tuple[Any, ...], as_of: datetime, minutes: int) -> Decimal | None:
        cutoff = as_of.timestamp() - minutes * 60
        points: list[tuple[datetime, Decimal]] = []
        for item in recent:
            timestamp = getattr(item, "timestamp", None)
            last_price = getattr(item, "last_price", None)
            if timestamp is None or last_price is None:
                continue
            observed_at = datetime.fromisoformat(timestamp)
            if observed_at <= as_of:
                points.append((observed_at, Decimal(str(last_price))))
        points.sort()
        if not points or points[0][0].timestamp() > cutoff:
            return None
        values = [price for timestamp, price in points if timestamp.timestamp() >= cutoff]
        if not values:
            return None
        return sum(values, Decimal("0")) / Decimal(len(values))

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
        ma_1m = self._time_window_ma(recent, observed_at, 1)
        ma_3m = self._time_window_ma(recent, observed_at, 3)
        ma_5m = self._time_window_ma(recent, observed_at, 5)
        ma_10m = self._time_window_ma(recent, observed_at, 10)
        strike = Decimal(str(tick.strike_price))
        iv = None
        put_iv = None
        if self.track2_option_iv_source is not None:
            current_type = str(getattr(tick, "option_type", "CALL")).upper()
            current_iv = self.track2_option_iv_source.get_iv(expiry=tick.expiry, option_type=current_type, strike=strike)
            opposite_type = "PUT" if current_type == "CALL" else "CALL"
            opposite_iv = self.track2_option_iv_source.get_iv(expiry=tick.expiry, option_type=opposite_type, strike=strike)
            if current_type == "CALL":
                iv, put_iv = current_iv, opposite_iv
            else:
                put_iv, iv = current_iv, opposite_iv
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
        calendar_flags = (None, None, None)
        order_timeout = None
        support = resistance = None
        support_resistance_status = RuntimeDataStatus(False, False, "Track7SupportResistance", "TRACK7_SUPPORT_RESISTANCE_SOURCE_UNAVAILABLE")
        if self.track7_support_resistance_source is not None and getattr(tick, "symbol", None):
            observation = self.track7_support_resistance_source.get(symbol=tick.symbol, observed_at=observed_at)
            if observation is not None:
                support, resistance = observation.support, observation.resistance
                support_resistance_status = RuntimeDataStatus(True, True, observation.source)
        if self.track7_order_timeout_source is not None:
            order_timeout = self.track7_order_timeout_source.is_strategy_timed_out(
                "TRACK7", observed_at
            )
        calendar_status = RuntimeDataStatus(False, False, "TradingCalendar", "TRACK7_TRADING_CALENDAR_UNAVAILABLE")
        if self.option_expiry_source is not None and getattr(tick, "symbol", None):
            option_expiry = self.option_expiry_source.resolve_expiry(tick.symbol)
        if option_expiry is None and self.trading_calendar is not None:
            try:
                option_expiry = self.trading_calendar.resolve_option_expiry(tick)
            except (ValueError, TypeError):
                option_expiry = None
        if option_expiry is not None:
            days_to_expiry = (option_expiry - observed_at.date()).days
            expiry_status = RuntimeDataStatus(True, True, "KIS.OptionMaster.expiry")
        if self.trading_calendar is not None:
            try:
                calendar_flags = self.trading_calendar.flags(observed_at.date(), option_expiry)
                calendar_status = RuntimeDataStatus(True, True, "ProductionTradingCalendar")
            except (ValueError, TypeError):
                calendar_flags = (None, None, None)
                calendar_status = RuntimeDataStatus(False, False, "ProductionTradingCalendar", "TRACK7_TRADING_CALENDAR_UNAVAILABLE")
        option_bid_qtys = None
        option_ask_qtys = None
        orderbook_status = RuntimeDataStatus(
            False, False, "OptionOrderBookSource", "OPTION_ORDERBOOK_SOURCE_UNAVAILABLE"
        )
        symbol = getattr(tick, "symbol", None)
        underlying_key = getattr(tick, "underlying_symbol", None) or "KOSPI200"
        poc_price = None
        basis = None
        bbw_window = None
        volume_window = None
        metrics_active_vol = None
        metrics_base_vol = None
        metrics_status = RuntimeDataStatus(False, False, "Track2MarketMetricsSource", "TRACK2_BBW_VOLUME_SOURCE_UNAVAILABLE")
        basis_status = RuntimeDataStatus(
            False, False, "BasisSource", "BASIS_SOURCE_UNAVAILABLE"
        )
        if self.basis_source is not None and symbol:
            basis = self.basis_source.get_basis(underlying_key)
            if basis is not None:
                basis_status = RuntimeDataStatus(
                    True, True, "KIS:futures-minus-spot"
                )
        if self.track2_metrics_source is not None and symbol:
            metrics = self.track2_metrics_source.get_metrics(underlying_key)
            if metrics is not None:
                bbw_window = metrics.bbw_window
                volume_window = metrics.volume_window
                metrics_active_vol = metrics.active_vol
                metrics_base_vol = metrics.base_vol
                metrics_status = RuntimeDataStatus(True, True, "KIS:H0IFCNT0:Track2Metrics")

        poc_status = RuntimeDataStatus(
            False, False, "VolumeProfileSource", "VOLUME_PROFILE_SOURCE_UNAVAILABLE"
        )
        if self.volume_profile_source is not None and symbol:
            poc_price = self.volume_profile_source.get_poc(underlying_key)
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

        moving_average_available = all(value is not None for value in (ma_1m, ma_3m, ma_5m, ma_10m))
        status = {
            "tick": RuntimeDataStatus(True, True, "VMS.recent_ticks"),
            "ohlc_history": RuntimeDataStatus(len(prices) >= 1, True, "VMS.recent_ticks"),
            "track7_moving_average": RuntimeDataStatus(
                moving_average_available,
                moving_average_available,
                "VMS.recent_ticks",
                None if moving_average_available else "TRACK7_MOVING_AVERAGE_HISTORY_COVERAGE_UNAVAILABLE",
            ),
            "iv_greeks": RuntimeDataStatus(iv is not None and put_iv is not None, iv is not None and put_iv is not None, "VMS.option_quotes", "OPTION_CHAIN_UNAVAILABLE" if iv is None or put_iv is None else None),
            "macro": RuntimeDataStatus(True, True, "VMS.scenario.active_config"),
            "event": RuntimeDataStatus(True, True, "VMS.scenario.shock_schedule"),
            "option_expiry": expiry_status,
            "track7_calendar": calendar_status,
            "track7_support_resistance": support_resistance_status,
            "option_orderbook": orderbook_status,
            "volume_profile_poc": poc_status,
            "basis": basis_status,
            "track2_bbw_volume": metrics_status,
        }
        return VirtualRuntimeData(
            as_of=observed_at, price=price, prices=prices, open_price=open_price,
            high_price=high, low_price=low, previous_close=previous_close,
            active_vol=metrics_active_vol if metrics_active_vol is not None else active_vol,
            base_vol=metrics_base_vol if metrics_base_vol is not None else base_vol,
            option_iv=iv, put_iv=put_iv, option_delta=delta, option_gamma=gamma,
            macro_regime=macro_regime, event_upcoming=event_upcoming, status=status,
            option_expiry=option_expiry, days_to_expiry=days_to_expiry,
            option_bid_qtys=option_bid_qtys, option_ask_qtys=option_ask_qtys,
            poc_price=poc_price, basis=basis, bbw_window=bbw_window, volume_window=volume_window,
            ma_1m=ma_1m, ma_3m=ma_3m, ma_5m=ma_5m, ma_10m=ma_10m,
            is_new_week_start=calendar_flags[0], is_expiry_day=calendar_flags[1], is_week_end=calendar_flags[2],
            order_timeout=order_timeout,
            support=support, resistance=resistance,
        )


