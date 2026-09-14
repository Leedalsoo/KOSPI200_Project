"""Reference Virtual Market Simulator Runtime."""
from __future__ import annotations

from datetime import datetime, timedelta
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

    def subscribe(self, callback) -> None:
        if not callable(callback):
            raise TypeError("VMS_MARKET_SUBSCRIBER_REQUIRED")
        self._subscribers.append(callback)

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
                underlying_price=last,
                strike_price=round(last / 2.5) * 2.5,
                option_type="CALL",
                bid_price=max(0.01, last - spread),
                ask_price=last + spread,
                last_price=last,
                volume=1000,
                seq_id=seq,
                expiry="202609",
                symbol="KOSPI200",
            )
            for subscriber in tuple(self._subscribers):
                subscriber(tick)
            yield tick
