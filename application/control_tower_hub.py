from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


class ControlTowerHub:
    """Stable read/command facade for Control Tower and run operations."""

    def __init__(self, *, runtime_controller: Any, ui_adapter: Any,
                 strategy_hub: Any | None = None, run_context: Any | None = None,
                 run_hub: Any | None = None, virtual_test_controller: Any | None = None) -> None:
        self._runtime_controller = runtime_controller
        self._ui_adapter = ui_adapter
        self._strategy_hub = strategy_hub
        self._run_context = run_context
        self._run_hub = run_hub
        self._virtual_test_controller = virtual_test_controller

    def virtual_test_read_model(self) -> dict[str, Any]:
        if self._virtual_test_controller is None:
            raise RuntimeError("VIRTUAL_TEST_CONTROLLER_UNAVAILABLE")
        return self._virtual_test_controller.read_model()

    def virtual_test_action(self, action: str, *, scenario: str | None = None, reason: str | None = None) -> dict[str, Any]:
        controller = self._virtual_test_controller
        if controller is None:
            raise RuntimeError("VIRTUAL_TEST_CONTROLLER_UNAVAILABLE")
        action = action.upper()
        if action == "ARM":
            controller.arm_for_test()
        elif action == "START":
            controller.start()
        elif action == "PAUSE":
            controller.pause()
        elif action == "NEXT_TICK":
            tick = controller.next_tick()
            return {**controller.read_model(), "tick": tick}
        elif action == "RESET":
            controller.reset()
        elif action == "KILL_SWITCH":
            controller.engage_kill_switch(reason or "UI_KILL_SWITCH")
        elif action == "SET_SCENARIO":
            if not scenario:
                raise ValueError("VIRTUAL_TEST_SCENARIO_REQUIRED")
            controller.set_scenario(scenario)
        else:
            raise ValueError(f"UNSUPPORTED_VIRTUAL_TEST_ACTION:{action}")
        return controller.read_model()

    def status(self) -> dict[str, Any]: return self._ui_adapter.get_summary()
    def environment(self, tab_id: str) -> dict[str, Any]: return self._ui_adapter.get_tab_detail(tab_id)
    def command(self, command: str) -> dict[str, Any]: return self._ui_adapter.handle_command(command)

    def attach_run_hub(self, run_hub: Any) -> None:
        self._run_hub = run_hub

    def strategy_read_model(self) -> dict[str, Any]:
        hub = self._strategy_hub
        keys = tuple(getattr(hub, "strategy_keys", ())) if hub else ()
        rows = []
        for key in keys:
            strategy_id, version = (key[0], key[1]) if isinstance(key, tuple) else (key.strategy_id, key.version)
            rows.append({"strategy_id": strategy_id, "version": version, "enabled": bool(hub.is_enabled(strategy_id, version))})
        return {"strategies": rows}

    def run_read_model(self) -> dict[str, Any]:
        session = getattr(self._run_hub, "active", None) if self._run_hub else None
        context = getattr(session, "context", self._run_context) if session else self._run_context
        result = {"active": session is not None, "run_id": getattr(context, "run_id", None),
                  "environment": getattr(context, "environment", None), "scenario": getattr(context, "scenario", None),
                  "historical_source": getattr(context, "historical_source", None),
                  "historical_store_path": getattr(context, "historical_store_path", None),
                  "runtime_state": getattr(self._runtime_controller.status(), "state", "STOPPED")}
        if session is not None:
            market = session.bundle.market
            tick = getattr(market, "last_tick", None)
            result["last_replay_tick"] = None if tick is None else {
                "timestamp": tick.timestamp, "seq_id": tick.seq_id, "symbol": tick.symbol, "expiry": tick.expiry,
                "strike": tick.strike_price, "option_type": tick.option_type,
                "bid": tick.bid_price, "ask": tick.ask_price, "last": tick.last_price
            }
            broker_api = getattr(session.bundle, "broker_api", None)
            if broker_api is not None:
                for name, method in (("account", "get_account_snapshot"), ("position", "get_position_snapshot"), ("margin", "get_margin_state"), ("pnl", "get_pnl_state")):
                    try:
                        value = getattr(broker_api, method)()
                        if name == "account" and hasattr(value, "balances"):
                            result[name] = {"as_of": value.as_of.isoformat() if value.as_of else None, "balances": {k: str(v) for k, v in value.balances.items()}, "freshness": str(value.freshness)}
                        else:
                            result[name] = asdict(value) if is_dataclass(value) else value
                    except Exception as exc:
                        result[name] = {"status": "UNAVAILABLE", "reason": str(exc)}
                try:
                    group_ids = broker_api.get_group_ids()
                    result["execution_reports"] = [asdict(x) if is_dataclass(x) else x for x in broker_api.get_group_reports(next(iter(group_ids), ""))] if group_ids else []
                except Exception:
                    result["execution_reports"] = []
        return result

    def scenario_read_model(self) -> dict[str, Any]:
        session = getattr(self._run_hub, "active", None) if self._run_hub else None
        market = getattr(session, "bundle", None).market if session else None
        engine = getattr(market, "scenario", None)
        return engine.state() if engine is not None else {"active_scenario": None, "available_scenarios": []}

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._run_hub is None: raise RuntimeError("RUN_HUB_UNAVAILABLE")
        if self._run_hub.active is not None: self._run_hub.close()
        context = self._run_hub.start(
            run_id=str(payload.get("run_id", "")).strip(), environment=str(payload.get("environment", "virtual")),
            scenario=payload.get("scenario"), historical_source=payload.get("historical_source"), historical_store_path=payload.get("historical_store_path"),
            strategy_keys=tuple(tuple(x) for x in payload.get("strategy_keys", ())),
            initial_capital=payload.get("initial_capital"), replay_speed=payload.get("replay_speed"),
        ).context
        return self.run_read_model()

    def run_action(self, action: str) -> dict[str, Any]:
        session = self._run_hub.active if self._run_hub else None
        if session is None: raise RuntimeError("RUN_NOT_ACTIVE")
        action = action.upper()
        if action == "START":
            restarted = self._run_hub.restart()
            self._strategy_hub = restarted.strategy_hub
            self._runtime_controller = restarted.runtime_controller
            self._ui_adapter = restarted.ui_adapter
            self._run_context = restarted.context
            return self.run_read_model()
        if action == "STOP":
            session.runtime_controller.stop()
            return self.run_read_model()
        if action == "REPLAY":
            market = session.bundle.market
            tick = market.replay_next()
            return {**self.run_read_model(), "replay_tick": None if tick is None else {
                "timestamp": tick.timestamp, "seq_id": tick.seq_id, "symbol": tick.symbol, "expiry": tick.expiry,
                "strike": tick.strike_price, "option_type": tick.option_type,
                "bid": tick.bid_price, "ask": tick.ask_price, "last": tick.last_price
            }}
        raise ValueError(f"UNSUPPORTED_RUN_ACTION:{action}")

    @property
    def runtime_controller(self) -> Any: return self._runtime_controller
    @property
    def strategy_hub(self) -> Any | None: return self._strategy_hub
    @property
    def run_context(self) -> Any | None: return self._run_context
