"""Authoritative derived-data providers for the Virtual Market runtime."""
from __future__ import annotations
from bisect import bisect_left, bisect_right
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
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer, Track9ATMIVSource
from contracts.kis_kospi200_daily_source import KOSPI200DailySource
from contracts.track6_volatility_source import Track6VolatilitySource
from application.composition.market_calendar_hub import MarketCalendarHub
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
    iv_spike: Decimal | None
    iv_crush: Decimal | None
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
    def __init__(self, market: Any, *, history_size: int = 50, option_expiry_source: Any | None = None, track7_order_timeout_source: Any | None = None, trading_calendar: Any | None = None, option_master: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None, track2_metrics_source: Track2MarketMetricsSource | None = None, track2_option_iv_source: Track2OptionIVSource | None = None, track9_iv_event_materializer: Track9IVEventMaterializer | None = None, track9_atm_iv_source: Track9ATMIVSource | None = None, track7_support_resistance_source: Track7AuthoritativeSupportResistanceSource | None = None, track4_greeks_provider: Any | None = None, kospi200_daily_source: KOSPI200DailySource | None = None, track6_volatility_source: Track6VolatilitySource | None = None) -> None:
        self.market = market
        self.history_size = history_size
        self.option_expiry_source = option_expiry_source
        self.track7_order_timeout_source = track7_order_timeout_source
        self.trading_calendar = (
            trading_calendar
            if isinstance(trading_calendar, MarketCalendarHub)
            else MarketCalendarHub(trading_calendar) if trading_calendar is not None else None
        )
        self.option_master = option_master
        self.option_orderbook_source = option_orderbook_source
        self.volume_profile_source = volume_profile_source
        self.basis_source = basis_source
        self.track2_metrics_source = track2_metrics_source
        self.track2_option_iv_source = track2_option_iv_source
        self.track9_iv_event_materializer = track9_iv_event_materializer
        self.track9_atm_iv_source = track9_atm_iv_source
        self.track4_greeks_provider = track4_greeks_provider
        self.kospi200_daily_source = kospi200_daily_source
        self.track6_volatility_source = track6_volatility_source
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
    def _time_window_ma(
        underlying_history: tuple[tuple[datetime, Decimal], ...],
        as_of: datetime,
        minutes: int,
    ) -> Decimal | None:
        if not underlying_history:
            return None
        cutoff = as_of.timestamp() - minutes * 60
        cutoff_at = datetime.fromtimestamp(cutoff, tz=as_of.tzinfo)
        start = bisect_left(underlying_history, (cutoff_at, Decimal("-Infinity")))
        end = bisect_right(underlying_history, (as_of, Decimal("Infinity")))
        if start >= end:
            return None
        values = [price for _timestamp, price in underlying_history[start:end]]
        if not values:
            return None
        return sum(values, Decimal("0")) / Decimal(len(values))
    def snapshot(self, tick: Any) -> VirtualRuntimeData:
        observed_at = datetime.fromisoformat(tick.timestamp)
        recent = tuple(self.market.recent_ticks[-self.history_size:])
        underlying_history = tuple(getattr(self.market, "underlying_history", ()))
        prices = tuple(Decimal(str(x.last_price)) for x in recent) or (Decimal(str(tick.last_price)),)
        price = Decimal(str(tick.last_price))
        high = max(prices)
        low = min(prices)
        open_price = prices[0]
        previous_close = prices[-2] if len(prices) >= 2 else prices[0]
        daily_context = None
        daily_error = None
        if self.kospi200_daily_source is not None and str(getattr(tick, "underlying_symbol", "") or "KOSPI200") == "KOSPI200":
            try:
                daily_context = self.kospi200_daily_source.get_context(observed_at.date())
            except Exception as exc:
                daily_error = str(exc)
            if daily_context is not None:
                open_price = daily_context.open_price
                previous_close = daily_context.previous_close
        returns = tuple(abs(prices[i] / prices[i - 1] - 1) for i in range(1, len(prices)) if prices[i - 1])
        active_vol = (sum(returns, Decimal("0")) / Decimal(len(returns))) if returns else None
        base_vol = active_vol
        ma_1m = self._time_window_ma(underlying_history, observed_at, 1)
        ma_3m = self._time_window_ma(underlying_history, observed_at, 3)
        ma_5m = self._time_window_ma(underlying_history, observed_at, 5)
        ma_10m = self._time_window_ma(underlying_history, observed_at, 10)
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
        # Replay carries authoritative per-option analytics from MarketObservation.
        delta = getattr(tick, 'delta', None)
        gamma = getattr(tick, 'gamma', None)
        if self.track4_greeks_provider is not None and (delta is None or gamma is None):
            greeks_provider = getattr(
                self.track4_greeks_provider,
                "provider",
                self.track4_greeks_provider,
            )
            snapshot = (
                getattr(greeks_provider, "snapshot", None)
                if greeks_provider is not None
                else None
            )
            provider_observed_at = getattr(snapshot, "observed_at", None) if snapshot is not None else None
            if provider_observed_at:
                provider_as_of = datetime.fromisoformat(provider_observed_at)
                if provider_as_of <= observed_at:
                    if delta is None:
                        delta = self.track4_greeks_provider.current_delta()
                    if gamma is None:
                        gamma = self.track4_greeks_provider.current_gamma()
        # Strategy 5 active volatility uses authoritative KIS ATM CALL/PUT IV.
        # KIS reports IV in percentage points; Common Analytics consumes decimal form.
        # Missing H0IOCNT0 evidence remains unavailable and never falls back to scenario volatility.
        authoritative_active_vol = None
        iv_spike = iv_crush = None
        if (self.track9_iv_event_materializer is not None and self.track9_atm_iv_source is not None
                and getattr(tick, "symbol", None) and getattr(tick, "expiry", None)):
            event_values = self.track9_iv_event_materializer.materialize(
                session_date=observed_at.date().isoformat(),
                symbol=tick.symbol,
                expiry=tick.expiry,
                current_price=Decimal(str(tick.underlying_price)),
                observed_at=observed_at,
                source=self.track9_atm_iv_source,
            )
            iv_spike, iv_crush = event_values.iv_spike, event_values.iv_crush
            if event_values.current_iv is not None and event_values.current_iv > 0:
                authoritative_active_vol = event_values.current_iv / Decimal("100")
        elif (self.track9_atm_iv_source is not None
                and getattr(tick, "symbol", None) and getattr(tick, "expiry", None)):
            atm_snapshot = self.track9_atm_iv_source.snapshot(
                symbol=tick.symbol,
                expiry=tick.expiry,
                current_price=Decimal(str(tick.underlying_price)),
                observed_at=observed_at,
            )
            if atm_snapshot is not None and atm_snapshot.call_iv > 0 and atm_snapshot.put_iv > 0:
                authoritative_active_vol = (atm_snapshot.call_iv + atm_snapshot.put_iv) / Decimal("2") / Decimal("100")
        if authoritative_active_vol is not None:
            active_vol = authoritative_active_vol
            base_vol = authoritative_active_vol

        track6_active_vol = None
        track6_base_vol = None
        track6_vol_status = RuntimeDataStatus(False, False, "KIS:ATM_IV", "TRACK6_VOLATILITY_UNAVAILABLE")
        if (
            self.track6_volatility_source is not None
            and getattr(tick, "expiry", None)
            and getattr(tick, "underlying_price", None) is not None
        ):
            snapshot = self.track6_volatility_source.snapshot(
                expiry=tick.expiry,
                current_price=Decimal(str(tick.underlying_price)),
                observed_at=observed_at,
            )
            if snapshot is not None:
                track6_active_vol = snapshot.active_vol
                track6_base_vol = snapshot.base_vol
                track6_vol_status = RuntimeDataStatus(
                    True, True, snapshot.source
                )

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
            observation = self.track7_support_resistance_source.get(symbol=tick.symbol, observed_at=observed_at, current_price=price)
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
                option_expiry = self.trading_calendar.resolve_option_expiry(tick, self.option_master)
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
                    True, True, getattr(self.basis_source, "source_name", "BasisSource")
                )
        if self.track2_metrics_source is not None and symbol:
            metrics = self.track2_metrics_source.get_metrics(underlying_key)
            if metrics is not None:
                bbw_window = metrics.bbw_window
                volume_window = metrics.volume_window
                metrics_active_vol = metrics.active_vol
                metrics_base_vol = metrics.base_vol
                metrics_status = RuntimeDataStatus(True, True, getattr(self.track2_metrics_source, "source_name", "Track2MarketMetricsSource"))

        poc_status = RuntimeDataStatus(
            False, False, "VolumeProfileSource", "VOLUME_PROFILE_SOURCE_UNAVAILABLE"
        )
        if self.volume_profile_source is not None and symbol:
            poc_price = self.volume_profile_source.get_poc(underlying_key)
            if poc_price is not None:
                poc_status = RuntimeDataStatus(
                    True, True, getattr(self.volume_profile_source, "source_name", "VolumeProfileSource")
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
            "kospi200_daily": RuntimeDataStatus(daily_context is not None, daily_context is not None, getattr(daily_context, "source", "KIS:FHPUP02120000:2001"), daily_error or ("KOSPI200_DAILY_SOURCE_UNAVAILABLE" if daily_context is None else None)),
            "track7_moving_average": RuntimeDataStatus(
                moving_average_available,
                moving_average_available,
                "VMS.underlying_history",
                None if moving_average_available else "TRACK7_MOVING_AVERAGE_HISTORY_COVERAGE_UNAVAILABLE",
            ),
            "iv_greeks": RuntimeDataStatus(iv is not None and put_iv is not None, iv is not None and put_iv is not None, "VMS.option_quotes", "OPTION_CHAIN_UNAVAILABLE" if iv is None or put_iv is None else None),
            "track9_iv_event": RuntimeDataStatus(iv_spike is not None and iv_crush is not None, iv_spike is not None and iv_crush is not None, "KIS:H0IOCNT0:Track9IVTimeSeries", "TRACK9_IV_EVENT_UNAVAILABLE" if iv_spike is None or iv_crush is None else None),
            "macro": RuntimeDataStatus(True, True, "VMS.scenario.active_config"),
            "event": RuntimeDataStatus(True, True, "VMS.scenario.shock_schedule"),
            "option_expiry": expiry_status,
            "track7_calendar": calendar_status,
            "track7_support_resistance": support_resistance_status,
            "option_orderbook": orderbook_status,
            "volume_profile_poc": poc_status,
            "basis": basis_status,
            "track2_bbw_volume": metrics_status,
            "track6_volatility": track6_vol_status,
        }
        return VirtualRuntimeData(
            as_of=observed_at, price=price, prices=prices, open_price=open_price,
            high_price=high, low_price=low, previous_close=previous_close,
            active_vol=track6_active_vol if track6_active_vol is not None else (metrics_active_vol if metrics_active_vol is not None else active_vol),
            base_vol=track6_base_vol if track6_base_vol is not None else (metrics_base_vol if metrics_base_vol is not None else base_vol),
            option_iv=iv, put_iv=put_iv, option_delta=delta, option_gamma=gamma,
            iv_spike=iv_spike, iv_crush=iv_crush,
            macro_regime=macro_regime, event_upcoming=event_upcoming, status=status,
            option_expiry=option_expiry, days_to_expiry=days_to_expiry,
            option_bid_qtys=option_bid_qtys, option_ask_qtys=option_ask_qtys,
            poc_price=poc_price, basis=basis, bbw_window=bbw_window, volume_window=volume_window,
            ma_1m=ma_1m, ma_3m=ma_3m, ma_5m=ma_5m, ma_10m=ma_10m,
            is_new_week_start=calendar_flags[0], is_expiry_day=calendar_flags[1], is_week_end=calendar_flags[2],
            order_timeout=order_timeout,
            support=support, resistance=resistance,
        )
