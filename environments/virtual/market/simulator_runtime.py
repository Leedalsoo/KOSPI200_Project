"""Reference Virtual Market Simulator Runtime."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from math import erf, exp, log, sqrt
from typing import Optional

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.config import VirtualBrokerConfig, VirtualBrokerControlInterface
from environments.virtual.market.clock_controller import VMSClockController
from environments.virtual.market.state_manager import VMSStateManager
from environments.virtual.market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.scenario_engine import ScenarioEngine


class VirtualMarketSimulatorRuntime:
    _SPEED_TO_REPLAY = {"SLOW": 1, "NORMAL": 300, "FAST": 1000}

    def __init__(self, config: Optional[VirtualBrokerConfig] = None, *, scenario_config_path: str | None = None) -> None:
        self.config = config or VirtualBrokerConfig()
        self.control = VirtualBrokerControlInterface(config=self.config)
        self.clock = VMSClockController()
        self.state_mgr = VMSStateManager()
        self.scenario = ScenarioEngine(config_path=scenario_config_path)
        self.replay = HistoricalReplayEngine()
        self._price = 350.0
        self._initial_price = 350.0
        self._subscribers = []
        self._recent_ticks = deque(maxlen=50)
        self.last_tick = None
        self._option_quotes = {}
        self._futures_price = self._price

    @property
    def recent_ticks(self):
        return tuple(self._recent_ticks)

    @property
    def option_quotes(self):
        return dict(self._option_quotes)

    @property
    def futures_price(self):
        return self._futures_price

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    @classmethod
    def _option_mid(cls, spot: float, strike: float, t: float, vol: float, kind: str) -> float:
        if t <= 0 or vol <= 0:
            return max(0.01, (spot - strike) if kind == "CALL" else (strike - spot))
        d1 = (log(spot / strike) + 0.5 * vol * vol * t) / (vol * sqrt(t))
        d2 = d1 - vol * sqrt(t)
        if kind == "CALL":
            return max(0.01, spot * cls._norm_cdf(d1) - strike * cls._norm_cdf(d2))
        return max(0.01, strike * cls._norm_cdf(-d2) - spot * cls._norm_cdf(-d1))

    def _refresh_option_quotes(self, tick, volatility_multiplier: float) -> None:
        observed = datetime.fromisoformat(tick.timestamp)
        expiry = datetime.strptime(tick.expiry, "%Y%m").replace(day=1)
        t = max(1.0 / 365.0, (expiry - observed.replace(day=1)).total_seconds() / 31536000.0)
        vol = max(0.05, 0.20 * float(volatility_multiplier) * self.config.volatility_scale)
        atm = round(tick.underlying_price / 2.5) * 2.5
        quotes = {}
        for option_type in ("CALL", "PUT"):
            for offset in (-15.0, 0.0, 15.0):
                strike = atm + offset
                mid = self._option_mid(tick.underlying_price, strike, t, vol, option_type)
                quotes[(option_type, strike, tick.expiry)] = {
                    "bid": max(0.01, mid - 0.05), "ask": mid + 0.05, "last": mid,
                    "iv": vol, "bid_qty": self.config.option_quote_qty,
                    "ask_qty": self.config.option_quote_qty, "contract_multiplier": 250000.0, "timestamp": tick.timestamp,
                }
        self._option_quotes = quotes

    def subscribe(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_MARKET_SUBSCRIBER_REQUIRED")
        self._subscribers.append(callback)

    def publish_authoritative_option_quote(self, key, quote) -> None:
        """Publish an externally authoritative option quote without synthetic fallback."""
        if not isinstance(key, tuple) or len(key) != 3:
            raise ValueError("OPTION_QUOTE_KEY_REQUIRED")
        if not isinstance(quote, dict):
            raise ValueError("OPTION_QUOTE_REQUIRED")
        bid = quote.get("bid")
        ask = quote.get("ask")
        if bid is None or ask is None or float(bid) <= 0 or float(ask) <= 0:
            raise ValueError("OPTION_QUOTE_BID_ASK_REQUIRED")
        if float(ask) < float(bid):
            raise ValueError("OPTION_QUOTE_CROSSED")
        multiplier = quote.get("contract_multiplier")
        if multiplier is None or float(multiplier) <= 0:
            raise ValueError("OPTION_CONTRACT_MULTIPLIER_REQUIRED")
        self._option_quotes[key] = dict(quote)
    def generate_tick_stream(self, *, total_days: int, ticks_per_day: int):
        if total_days <= 0 or ticks_per_day <= 0:
            return
        total_ticks = total_days * ticks_per_day
        start = datetime(2026, 1, 2, 9, 0, 0)
        interval = timedelta(seconds=max(1, int(6 * 60 * 60 / ticks_per_day)))
        for seq in range(1, total_ticks + 1):
            adjustment = self.scenario.next_adjustment(seq - 1, ticks_per_day)
            self._price = max(0.01, self._price + adjustment.drift)
            if adjustment.gap_pct:
                self._price *= 1.0 + adjustment.gap_pct
            if adjustment.shock_delta:
                self._price += adjustment.shock_delta
            last = round(self._price, 4)
            spread = 0.05
            tick = ReferenceCanonicalMarketTick(
                timestamp=(start + interval * (seq - 1)).isoformat(),
                underlying_price=last, strike_price=round(last / 2.5) * 2.5,
                option_type="CALL", bid_price=max(0.01, last - spread),
                ask_price=last + spread, last_price=last, volume=1000,
                seq_id=seq, expiry="202609", symbol="KOSPI200",
            )
            self.last_tick = tick
            self._recent_ticks.append(tick)
            self._futures_price = tick.underlying_price + self.config.futures_basis_points
            self._refresh_option_quotes(tick, adjustment.volatility_multiplier)
            for subscriber in tuple(self._subscribers):
                subscriber(tick)
            yield tick
