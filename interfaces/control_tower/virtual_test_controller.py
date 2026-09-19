from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class VirtualTestState:
    state: str = "READY"
    scenario: str | None = None
    available_scenarios: tuple[str, ...] = ()
    processed_ticks: int = 0
    last_tick: dict[str, Any] | None = None
    kill_switch: bool = True
    blocked_reason: str | None = "FAIL_SAFE_DEFAULT"


class VirtualTestController:
    """Control boundary for deterministic Virtual Exchange test runs."""

    def __init__(self, *, market: Any, market_factory: Callable[[], Any] | None = None) -> None:
        self._market_factory = market_factory or self._default_factory(market)
        self._market = market
        self._stream = None
        self._state = "READY"
        self._processed_ticks = 0
        self._last_tick = None
        self._kill_switch = True
        self._blocked_reason = "FAIL_SAFE_DEFAULT"

    @staticmethod
    def _default_factory(market: Any) -> Callable[[], Any]:
        market_type = type(market)
        option_master = getattr(market, "option_master", None)
        scenario = getattr(market, "scenario", None)
        scenario_path = getattr(scenario, "config_path", None)
        return lambda: market_type(option_master=option_master, scenario_config_path=str(scenario_path) if scenario_path else None)

    @property
    def market(self) -> Any:
        return self._market

    def _available_scenarios(self) -> tuple[str, ...]:
        state = getattr(getattr(self._market, "scenario", None), "state", lambda: {})()
        return tuple(state.get("available_scenarios", ()))

    def read_model(self) -> dict[str, Any]:
        scenario_state = getattr(getattr(self._market, "scenario", None), "state", lambda: {})()
        tick = self._last_tick
        last_tick = None if tick is None else {
            "timestamp": tick.timestamp,
            "symbol": tick.symbol,
            "expiry": tick.expiry,
            "strike": tick.strike_price,
            "option_type": tick.option_type,
            "bid": tick.bid_price,
            "ask": tick.ask_price,
            "last": tick.last_price,
            "contract_multiplier": tick.contract_multiplier,
            "seq_id": tick.seq_id,
        }
        return asdict(VirtualTestState(
            state=self._state,
            scenario=scenario_state.get("active_scenario"),
            available_scenarios=self._available_scenarios(),
            processed_ticks=self._processed_ticks,
            last_tick=last_tick,
            kill_switch=self._kill_switch,
            blocked_reason=self._blocked_reason,
        ))

    def set_scenario(self, name: str) -> None:
        scenario = getattr(self._market, "scenario", None)
        if scenario is None or not hasattr(scenario, "set_scenario"):
            raise RuntimeError("VIRTUAL_TEST_SCENARIO_ENGINE_UNAVAILABLE")
        scenario.set_scenario(name)

    def start(self) -> None:
        if self._kill_switch:
            raise RuntimeError("VIRTUAL_TEST_KILL_SWITCH_ENGAGED")
        if self._state == "RUNNING":
            return
        self._stream = iter(self._market.generate_tick_stream(total_days=1, ticks_per_day=1000))
        self._state = "RUNNING"

    def pause(self) -> None:
        if self._state == "RUNNING":
            self._state = "PAUSED"

    def engage_kill_switch(self, reason: str) -> None:
        self._kill_switch = True
        self._blocked_reason = str(reason)
        self._state = "HALTED"

    def reset(self) -> None:
        self._market = self._market_factory()
        self._stream = None
        self._state = "READY"
        self._processed_ticks = 0
        self._last_tick = None
        self._kill_switch = True
        self._blocked_reason = "FAIL_SAFE_DEFAULT"

    def arm_for_test(self) -> None:
        """Open only the virtual test controller; this never arms Paper/Live trading."""
        self._kill_switch = False
        self._blocked_reason = None

    def next_tick(self) -> Any:
        if self._kill_switch:
            raise RuntimeError("VIRTUAL_TEST_KILL_SWITCH_ENGAGED")
        if self._state not in {"RUNNING", "PAUSED"}:
            raise RuntimeError("VIRTUAL_TEST_NOT_RUNNING")
        if self._stream is None:
            raise RuntimeError("VIRTUAL_TEST_STREAM_UNAVAILABLE")
        try:
            tick = next(self._stream)
        except StopIteration:
            self._state = "FINISHED"
            return None
        self._last_tick = tick
        self._processed_ticks += 1
        return tick
