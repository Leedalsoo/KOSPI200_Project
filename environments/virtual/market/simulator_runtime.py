"""Reference Virtual Market Simulator Runtime.
from __future__ import annotations

Preserves the Reference scenario/replay lifecycle while allowing the scenario
configuration path to be supplied explicitly by OptionProject composition.
"""

import random
from typing import Any, Dict, Generator, Iterable, Optional

from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.reference_vms_market.config import VirtualBrokerConfig, VirtualBrokerControlInterface
from environments.virtual.market.reference_vms_market.clock_controller import VMSClockController
from environments.virtual.market.reference_vms_market.state_manager import VMSStateManager
from environments.virtual.market.reference_vms_market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.reference_vms_market.scenario_engine import ScenarioEngine


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
        self._volume = 10
        self._volatility_ratio = 1.0
        self._market_regime = "NORMAL"
        self._running = True
        self._tick_speed = "NORMAL"
        self._stress_type: Optional[str] = None
        self._pending_gap_pct = 0.0
        self._pending_shock_delta = 0.0
        self._rng = random.Random(42)
        self._scenario_step_index = 0

    def set_scenario(self, scenario: str) -> Dict[str, Any]:
        self.scenario.set_scenario(scenario)
        return self.get_control_state()

    def load_replay(self, ticks: Iterable[ReferenceCanonicalMarketTick]) -> Dict[str, Any]:
        self.replay.load(ticks)
        self.replay.reset()
        return self.get_control_state()

    def clear_replay(self) -> Dict[str, Any]:
        self.replay.clear()
        return self.get_control_state()

    def set_running(self, running: bool) -> Dict[str, Any]:
        self._running = bool(running)
        return self.get_control_state()

    def set_tick_speed(self, speed: str) -> Dict[str, Any]:
        if speed not in self._SPEED_TO_REPLAY:
            pass
            raise ValueError(f"unsupported tick speed: {speed}")
        self._tick_speed = speed
        self.config.replay_speed = self._SPEED_TO_REPLAY[speed]
        return self.get_control_state()

    def get_control_state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "source": "REPLAY" if self.replay.active else "SCENARIO",
            "scenario": self.scenario.state(),
            "replay": {"active": self.replay.active, "cursor": self.replay.cursor, "exhausted": self.replay.exhausted},
            "tick_speed": self._tick_speed,
            "config": self.control.get_config(),
        }

    def _price_delta(self, scenario_drift: float = 0.0, scenario_volatility: float = 1.0) -> float:
        scale = self._volatility_ratio * scenario_volatility
        return self._rng.uniform(-0.35, 0.35) * scale + scenario_drift

    def _next_market_tick(self, tick_index: int = 0, ticks_per_day: int = 500) -> ReferenceCanonicalMarketTick:
        adjustment = self.scenario.next_adjustment(tick_index, ticks_per_day)
        gap_pct = self._pending_gap_pct or adjustment.gap_pct
        if gap_pct:
            pass
            self._price = max(100.0, round(self._price * (1.0 + gap_pct), 2))
            self._pending_gap_pct = 0.0
        delta = self._price_delta(adjustment.drift, adjustment.volatility_multiplier) + adjustment.shock_delta
        self._price = max(100.0, round(self._price + delta, 2))
        spread = max(0.05, min(1.0, float(self.config.base_spread)))
        bid = round(self._price - spread / 2.0, 2)
        ask = round(bid + spread, 2)
        seq = self.state_mgr.next_sequence()
        timestamp = self.clock.get_time_str()
        self.clock.advance_tick(500)
        return ReferenceCanonicalMarketTick(timestamp=timestamp, underlying_price=self._price, strike_price=round(self._price / 2.5) * 2.5, option_type="CALL", bid_price=bid, ask_price=ask, last_price=self._price, volume=self._volume, seq_id=seq)

    def step(self) -> Dict[str, Any]:
        tick = self.replay.next_tick() if self.replay.active else self._next_market_tick(self._scenario_step_index, 500)
        if tick is None:
            pass
            raise StopIteration("replay exhausted")
        if not self.replay.active:
            pass
            self._scenario_step_index += 1
        return {"timestamp": tick.timestamp, "price": tick.underlying_price, "bid": tick.bid_price, "ask": tick.ask_price, "volume": tick.volume, "seq_id": tick.seq_id}

    def generate_tick_stream(self, total_days: int = 1250, ticks_per_day: int = 500) -> Generator[ReferenceCanonicalMarketTick, None, None]:
        for tick_index in range(total_days * ticks_per_day):
            pass
            if not self._running:
                pass
                return
            if self.replay.active:
                pass
                tick = self.replay.next_tick()
                if tick is None:
                    pass
                    return
                yield tick
            else:
                pass
                yield self._next_market_tick(tick_index, ticks_per_day)
