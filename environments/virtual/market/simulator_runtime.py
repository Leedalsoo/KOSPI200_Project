"""Reference Virtual Market Simulator Runtime."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from math import erf, exp, log, sqrt
from decimal import Decimal
from typing import Optional

from core.option.option_master import IOptionContractMaster, KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
from contracts.option_expiry import normalize_option_expiry

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from contracts.types import CanonicalFuturesQuote
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from environments.virtual.market.config import VirtualBrokerConfig, VirtualBrokerControlInterface
from environments.virtual.market.clock_controller import VMSClockController
from environments.virtual.market.state_manager import VMSStateManager
from environments.virtual.market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.scenario_engine import ScenarioEngine


class VirtualMarketSimulatorRuntime:
    _SPEED_TO_REPLAY = {"SLOW": 1, "NORMAL": 300, "FAST": 1000}

    def __init__(self, config: Optional[VirtualBrokerConfig] = None, *, scenario_config_path: str | None = None, option_master: IOptionContractMaster | None = None) -> None:
        self.config = config or VirtualBrokerConfig()
        self.option_master = option_master
        self.control = VirtualBrokerControlInterface(config=self.config)
        self.clock = VMSClockController()
        self.state_mgr = VMSStateManager()
        self.scenario = ScenarioEngine(config_path=scenario_config_path)
        self.replay = HistoricalReplayEngine()
        self._price = 350.0
        self._initial_price = 350.0
        self._subscribers = []
        self._futures_quote_subscribers = []
        self._futures_observation_subscribers = []
        self._futures_observation_replay = None
        self._index_price_observation_subscribers = []
        self._index_price_observation_replay = None
        self._recent_ticks = deque(maxlen=50)
        self._underlying_history = deque(maxlen=600)
        self.last_tick = None
        self._option_quotes = {}
        self._authoritative_option_quote_provider = None
        self._futures_price = self._price

    @property
    def recent_ticks(self):
        return tuple(self._recent_ticks)

    @property
    def underlying_history(self):
        return tuple(self._underlying_history)

    @property
    def option_quotes(self):
        return dict(self._option_quotes)

    @property
    def futures_price(self):
        return self._futures_price

    def set_authoritative_option_quote_provider(self, provider) -> None:
        """Set a source-side quote provider used only at replay publication time."""
        if provider is not None and not callable(provider):
            raise TypeError("VMS_AUTHORITATIVE_OPTION_QUOTE_PROVIDER_REQUIRED")
        self._authoritative_option_quote_provider = provider

    def load_historical_store(self, store, *, source: str | None = None) -> None:
        """Load canonical historical events for Virtual Exchange replay."""
        self.replay.load_store(store, source=source)

    def load_historical_observation_store(self, store, *, source: str | None = None) -> None:
        """Load authoritative REST market observations for Virtual Exchange replay."""
        self.replay = HistoricalReplayEngine.from_observation_store(store, source=source)

    def replay_next(self):
        """Publish one historical event through the Virtual Exchange subscriber boundary."""
        tick = self.replay.next_tick()
        if tick is None:
            return None
        return self.publish_replay_tick(tick)

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

    def _authoritative_strike(self, expiry: str, option_type: str, target: float) -> tuple[Decimal, object]:
        if self.option_master is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_SOURCE_REQUIRED")
        candidates = tuple(
            identity for identity in self.option_master.list_contract_identities(expiry)
            if identity.option_type == option_type
            and identity.contract_multiplier is not None
            and identity.expiry.replace("-", "")[:8] == expiry.replace("-", "")[:8]
        )
        if not candidates:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_REQUIRED")
        identity = min(candidates, key=lambda item: (abs(float(item.strike) - target), float(item.strike)))
        return Decimal(str(identity.strike)), identity

    def _refresh_option_quotes(self, tick, volatility_multiplier: float) -> None:
        observed = datetime.fromisoformat(tick.timestamp)
        canonical_expiry = normalize_option_expiry(tick.expiry)
        exact_expiry = canonical_expiry.require_exact()
        expiry = datetime.strptime(exact_expiry, "%Y%m%d")
        t = max(1.0 / 365.0, (expiry - observed).total_seconds() / 31536000.0)
        vol = max(0.05, 0.20 * float(volatility_multiplier) * self.config.volatility_scale)
        atm = round(tick.underlying_price / 2.5) * 2.5
        quotes = {}
        if self.option_master is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_SOURCE_REQUIRED")
        for option_type in ("CALL", "PUT"):
            selected_strikes: set[Decimal] = set()
            for offset in (-15.0, 0.0, 15.0):
                strike, identity = self._authoritative_strike(tick.expiry, option_type, atm + offset)
                if strike in selected_strikes:
                    continue
                selected_strikes.add(strike)
                mid = self._option_mid(tick.underlying_price, float(strike), t, vol, option_type)
                quotes[(option_type, float(strike), tick.expiry)] = {
                    "bid": max(0.01, mid - 0.05), "ask": mid + 0.05, "last": mid,
                    "iv": vol, "bid_qty": self.config.option_quote_qty,
                    "ask_qty": self.config.option_quote_qty,
                    "contract_multiplier": identity.contract_multiplier,
                    "shrn_iscd": identity.shrn_iscd, "timestamp": tick.timestamp,
                }
        self._option_quotes = quotes

    def subscribe(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_MARKET_SUBSCRIBER_REQUIRED")
        self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        self._subscribers = [item for item in self._subscribers if item != callback]

    def register_replay_option_quote(self, *, symbol: str, option_type: str, strike: float, expiry: str, bid: float, ask: float, last: float, timestamp: str, contract_multiplier: float) -> None:
        """Register an external replay quote without triggering strategy evaluation."""
        if not symbol or option_type not in {"CALL", "PUT"} or not expiry:
            raise ValueError("VMS_REPLAY_OPTION_QUOTE_REQUIRED")
        normalized_expiry = str(expiry).replace("-", "")[:8]
        self._option_quotes[(option_type.upper(), float(strike), normalized_expiry)] = {
            "bid": float(bid),
            "ask": float(ask),
            "last": float(last),
            "timestamp": timestamp,
            "contract_multiplier": float(contract_multiplier),
        }

    def subscribe_index_price_observation(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_INDEX_PRICE_OBSERVATION_SUBSCRIBER_REQUIRED")
        self._index_price_observation_subscribers.append(callback)

    def set_index_price_observation_replay(self, replay) -> None:
        if replay is None or not hasattr(replay, "consume_until"):
            raise TypeError("VMS_INDEX_PRICE_OBSERVATION_REPLAY_REQUIRED")
        self._index_price_observation_replay = replay

    def _publish_index_price_observations_until(self, timestamp: str) -> int:
        if self._index_price_observation_replay is None:
            return 0
        observations = self._index_price_observation_replay.consume_until(timestamp)
        for observation in observations:
            for subscriber in tuple(self._index_price_observation_subscribers):
                subscriber(observation)
        return len(observations)

    def subscribe_futures_observation(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_FUTURES_OBSERVATION_SUBSCRIBER_REQUIRED")
        self._futures_observation_subscribers.append(callback)

    def set_futures_observation_replay(self, replay) -> None:
        if replay is None or not hasattr(replay, "consume_until"):
            raise TypeError("VMS_FUTURES_OBSERVATION_REPLAY_REQUIRED")
        self._futures_observation_replay = replay

    def _publish_futures_observations_until(self, timestamp: str) -> int:
        if self._futures_observation_replay is None:
            return 0
        observations = self._futures_observation_replay.consume_until(timestamp)
        for observation in observations:
            for subscriber in tuple(self._futures_observation_subscribers):
                subscriber(observation)
        return len(observations)

    def subscribe_futures_quote(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_FUTURES_QUOTE_SUBSCRIBER_REQUIRED")
        self._futures_quote_subscribers.append(callback)

    def publish_authoritative_futures_quote(self, quote: CanonicalFuturesQuote) -> CanonicalFuturesQuote:
        """Publish an authoritative futures quote without altering option/underlying replay state."""
        if not isinstance(quote, CanonicalFuturesQuote):
            raise TypeError("VMS_FUTURES_QUOTE_REQUIRED")
        for subscriber in tuple(self._futures_quote_subscribers):
            subscriber(quote)
        return quote

    def publish_replay_tick(self, tick: ReferenceCanonicalMarketTick):
        """Publish one externally supplied replay tick through the Virtual Market boundary."""
        if not isinstance(tick, ReferenceCanonicalMarketTick):
            raise TypeError("VMS_REPLAY_TICK_REQUIRED")
        # Preserve the observed WS broker symbol at the Runtime boundary.
        # Contract metadata is resolved separately through the authoritative Master.
        # Keep authoritative VSSF execution timestamps aligned with replay observation time.
        observed_at = datetime.fromisoformat(tick.timestamp)
        self.clock.current_time = observed_at
        self.last_tick = tick
        self._recent_ticks.append(tick)
        self._publish_futures_observations_until(tick.timestamp)
        self._publish_index_price_observations_until(tick.timestamp)
        if tick.underlying_price is not None:
            observed_at = datetime.fromisoformat(tick.timestamp)
            underlying_value = Decimal(str(tick.underlying_price))
            if not self._underlying_history or self._underlying_history[-1][0] != observed_at:
                self._underlying_history.append((observed_at, underlying_value))
            elif self._underlying_history[-1][1] != underlying_value:
                raise ValueError("VMS_UNDERLYING_SAME_TIMESTAMP_MISMATCH")
            self._price = tick.underlying_price
            self._futures_price = self._price + self.config.futures_basis_points
        if tick.symbol and tick.option_type and tick.expiry and tick.bid_price > 0 and tick.ask_price > 0:
            normalized_expiry = str(tick.expiry).replace("-", "")[:8]
            self._option_quotes[(tick.option_type.upper(), float(tick.strike_price), normalized_expiry)] = {
                "bid": tick.bid_price,
                "ask": tick.ask_price,
                "last": tick.last_price,
                "timestamp": tick.timestamp,
                "contract_multiplier": tick.contract_multiplier,
            }
        provider = self._authoritative_option_quote_provider
        if provider is not None:
            authoritative_quotes = provider(observed_at)
            if authoritative_quotes is None:
                authoritative_quotes = {}
            if not isinstance(authoritative_quotes, dict):
                raise TypeError("VMS_AUTHORITATIVE_OPTION_QUOTE_PROVIDER_RESULT_REQUIRED")
            for key, quote in authoritative_quotes.items():
                self.publish_authoritative_option_quote(key, quote)
        for subscriber in tuple(self._subscribers):
            subscriber(tick)
        return tick

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

    def _authoritative_tick_identity(
        self, timestamp: datetime, option_type: str, target_strike: Decimal
    ):
        if self.option_master is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_SOURCE_REQUIRED")
        timestamp_date = timestamp.strftime("%Y%m%d")
        candidates = []
        for identity in self.option_master.list_contract_identities():
            if (
                identity.option_type != option_type
                or identity.strike is None
                or identity.contract_multiplier != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
                or not identity.expiry
            ):
                continue
            try:
                exact_expiry = normalize_option_expiry(identity.expiry).require_exact()
            except (TypeError, ValueError):
                continue
            if exact_expiry <= timestamp_date:
                continue
            strike = Decimal(str(identity.strike))
            candidates.append((exact_expiry, abs(strike - target_strike), strike, identity))
        if not candidates:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_REQUIRED")
        earliest_expiry = min(candidate[0] for candidate in candidates)
        same_expiry = (
            candidate for candidate in candidates if candidate[0] == earliest_expiry
        )
        return min(same_expiry, key=lambda item: (item[1], item[2]))[3]

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
            strike_price = round(last / 2.5) * 2.5
            tick_timestamp = start + interval * (seq - 1)
            identity = self._authoritative_tick_identity(
                tick_timestamp, "CALL", Decimal(str(strike_price))
            )
            exact_expiry = normalize_option_expiry(identity.expiry).require_exact()
            tick = ReferenceCanonicalMarketTick(
                timestamp=tick_timestamp.isoformat(),
                underlying_price=last, strike_price=strike_price,
                option_type="CALL", contract_multiplier=identity.contract_multiplier,
                bid_price=max(0.01, last - spread),
                ask_price=last + spread, last_price=last, volume=1000,
                seq_id=seq, expiry=exact_expiry, symbol="KOSPI200",
            )
            self.last_tick = tick
            self._recent_ticks.append(tick)
            observed_at = datetime.fromisoformat(tick.timestamp)
            underlying_value = Decimal(str(tick.underlying_price))
            if not self._underlying_history or self._underlying_history[-1][0] != observed_at:
                self._underlying_history.append((observed_at, underlying_value))
            elif self._underlying_history[-1][1] != underlying_value:
                raise ValueError("VMS_UNDERLYING_SAME_TIMESTAMP_MISMATCH")
            self._futures_price = tick.underlying_price + self.config.futures_basis_points
            self._refresh_option_quotes(tick, adjustment.volatility_multiplier)
            for subscriber in tuple(self._subscribers):
                subscriber(tick)
            yield tick
