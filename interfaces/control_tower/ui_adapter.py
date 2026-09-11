"""Control Tower UI Adapter — UI Data Interface.

Strategy/Core 내부 구현 객체를 직접 UI로 노출하지 않고,
실제 Runtime, Environment, RiskEngine의 상태만을 읽기 전용 DTO로 변환하여 Frontend에 공급합니다.
임의의 숫자/틱/계좌/주문/체결을 직접 생성하는 가짜 데이터 생성을 일체 금지합니다.
"""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from interfaces.control_tower.view_models import (
    ControlTowerSummaryView,
    HighSpeedTestView,
    LiveTradingView,
    PaperTradingView,
    TabEnvironmentId,
    VirtualBrokerView,
    VirtualExchangeView,
)


class ControlTowerUIAdapter:
    """UI-facing read-only adapter isolating Frontend from Strategy/Core internals."""

    def __init__(
        self,
        runtime_controller=None,
        *,
        risk_engine=None,
        lifecycle_coordinator=None,
    ):
        self._runtime_controller = runtime_controller
        self._risk_engine = risk_engine
        self._lifecycle_coordinator = lifecycle_coordinator
        self._active_tab = TabEnvironmentId.VIRTUAL_EXCHANGE.value
        self._audit_logs: list[str] = ["Control Tower UI Adapter initialized"]

    def set_active_tab(self, tab_id: str) -> None:
        """Switch active view tab."""
        valid_tabs = [t.value for t in TabEnvironmentId]
        if tab_id in valid_tabs:
            self._active_tab = tab_id

    def _is_kill_switch_active(self) -> bool:
        """Query real RiskEngine kill switch if injected."""
        if self._risk_engine is not None and hasattr(self._risk_engine, "is_kill_switch_active"):
            return bool(self._risk_engine.is_kill_switch_active())
        return False

    def _get_active_bundle(self):
        """Retrieve the currently active EnvironmentBundle from RuntimeController/Hub."""
        if self._runtime_controller is not None and hasattr(self._runtime_controller, "_hub"):
            return self._runtime_controller._hub.active
        return None

    def _get_runtime_state(self) -> str:
        """Query current runtime execution state."""
        if self._runtime_controller is not None and hasattr(self._runtime_controller, "status"):
            status = self._runtime_controller.status()
            return getattr(status, "state", "STOPPED")
        return "STOPPED"

    def get_summary(self) -> dict[str, Any]:
        """Return 5-environment summary state for global header & tabs status based on real runtime."""
        bundle = self._get_active_bundle()
        active_env_type = bundle.environment.value if bundle is not None and hasattr(bundle, "environment") else None
        runtime_state = self._get_runtime_state()
        kill_switch_active = self._is_kill_switch_active()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        tabs_summary = [
            {
                "tab_id": TabEnvironmentId.HIGH_SPEED.value,
                "name": "High-Speed Test",
                "status": runtime_state if active_env_type == "high_speed" else "STOPPED",
                "connection": "CONNECTED" if active_env_type == "high_speed" else "DISCONNECTED",
                "is_active": self._active_tab == TabEnvironmentId.HIGH_SPEED.value,
            },
            {
                "tab_id": TabEnvironmentId.VIRTUAL_EXCHANGE.value,
                "name": "가상거래소",
                "status": "OPEN" if (active_env_type == "virtual" and getattr(bundle, "running", False)) else "STOPPED",
                "connection": "CONNECTED" if (active_env_type == "virtual" and getattr(bundle, "connected", False)) else "DISCONNECTED",
                "is_active": self._active_tab == TabEnvironmentId.VIRTUAL_EXCHANGE.value,
            },
            {
                "tab_id": TabEnvironmentId.VIRTUAL_BROKER.value,
                "name": "가상증권사",
                "status": "OPERATIONAL" if (active_env_type == "virtual" and getattr(bundle, "connected", False)) else "NOT_INITIALIZED",
                "connection": "CONNECTED" if (active_env_type == "virtual" and getattr(bundle, "connected", False)) else "DISCONNECTED",
                "is_active": self._active_tab == TabEnvironmentId.VIRTUAL_BROKER.value,
            },
            {
                "tab_id": TabEnvironmentId.PAPER.value,
                "name": "모의투자",
                "status": "BLOCKED",
                "connection": "DISCONNECTED",
                "is_active": self._active_tab == TabEnvironmentId.PAPER.value,
            },
            {
                "tab_id": TabEnvironmentId.LIVE.value,
                "name": "실투자",
                "status": "BLOCKED",
                "connection": "DISCONNECTED",
                "is_active": self._active_tab == TabEnvironmentId.LIVE.value,
            },
        ]

        alert_message = None
        if kill_switch_active:
            alert_message = "KILL SWITCH ACTIVE: All trading halted"

        summary = ControlTowerSummaryView(
            active_environment=self._active_tab,
            system_time=now_str,
            kill_switch_global=kill_switch_active,
            tabs=tabs_summary,
            alert_message=alert_message,
        )
        return asdict(summary)

    def get_tab_detail(self, tab_id: str) -> dict[str, Any]:
        """Return detailed view data for a specific environment tab, projected from real components."""
        bundle = self._get_active_bundle()
        active_env_type = bundle.environment.value if bundle is not None and hasattr(bundle, "environment") else None
        runtime_state = self._get_runtime_state()

        if tab_id == TabEnvironmentId.HIGH_SPEED.value:
            if active_env_type == "high_speed" and bundle is not None:
                policy = getattr(bundle, "policy", None)
                speed = float(getattr(policy, "speed_multiplier", 1.0)) if policy else 1.0
                view = HighSpeedTestView(
                    runtime_state=runtime_state,
                    connection_state="CONNECTED",
                    speed_multiplier=speed,
                    scenario_name=getattr(bundle, "scenario_name", "SYNTHETIC_HIGH_SPEED"),
                    processed_ticks=getattr(bundle, "processed_ticks", 0),
                    total_ticks=getattr(bundle, "total_ticks", 0),
                    progress_ratio=getattr(bundle, "progress_ratio", 0.0),
                    audit_logs=list(self._audit_logs),
                )
                return asdict(view)
            return asdict(HighSpeedTestView(audit_logs=list(self._audit_logs)))

        elif tab_id == TabEnvironmentId.VIRTUAL_EXCHANGE.value:
            if active_env_type == "virtual" and bundle is not None:
                is_connected = getattr(bundle, "connected", False)
                is_running = getattr(bundle, "running", False)
                market = getattr(bundle, "market", None)

                ticks: list[dict[str, Any]] = []
                last_time = None
                underlying_price = None

                # Extract real tick if available on market object
                if market is not None:
                    last_tick = getattr(market, "last_tick", None)
                    if last_tick is not None:
                        price_val = float(last_tick.price) if isinstance(last_tick.price, (int, float, Decimal)) else None
                        underlying_price = price_val
                        time_str = last_tick.observed_at.isoformat() if hasattr(last_tick, "observed_at") and last_tick.observed_at else None
                        last_time = time_str
                        ticks.append({
                            "code": getattr(last_tick, "instrument_id", "KOSPI200_VIRTUAL"),
                            "name": "KOSPI200 Virtual Underlying",
                            "price": price_val,
                            "volume": float(getattr(last_tick, "volume", 0)),
                            "time": time_str,
                        })

                view = VirtualExchangeView(
                    market_state="OPEN" if is_running else ("READY" if is_connected else "STOPPED"),
                    connection_state="CONNECTED" if is_connected else "DISCONNECTED",
                    last_data_time=last_time,
                    instruments_count=1 if ticks else 0,
                    recent_ticks=ticks,
                    underlying_index_price=underlying_price,
                    audit_logs=list(self._audit_logs),
                )
                return asdict(view)
            return asdict(VirtualExchangeView(audit_logs=list(self._audit_logs)))

        elif tab_id == TabEnvironmentId.VIRTUAL_BROKER.value:
            if active_env_type == "virtual" and bundle is not None:
                is_connected = getattr(bundle, "connected", False)
                account = getattr(bundle, "account", None)
                position = getattr(bundle, "position", None)

                cash_val = None
                margin_used_val = None
                margin_avail_val = None
                realized_pnl_val = None

                if account is not None and hasattr(account, "snapshot"):
                    try:
                        snap = account.snapshot()
                        balances = getattr(snap, "balances", {})
                        if "cash" in balances:
                            cash_val = float(balances["cash"])
                        if "margin_used" in balances:
                            margin_used_val = float(balances["margin_used"])
                        if "available_cash" in balances:
                            margin_avail_val = float(balances["available_cash"])
                        if "realized_pnl" in balances:
                            realized_pnl_val = float(balances["realized_pnl"])
                    except Exception:
                        pass

                positions_list: list[dict[str, Any]] = []
                if position is not None and hasattr(position, "snapshot"):
                    try:
                        pos_snap = position.snapshot()
                        pos_dict = getattr(pos_snap, "positions", {})
                        for sym, qty in pos_dict.items():
                            positions_list.append({
                                "symbol": str(sym),
                                "qty": int(qty),
                            })
                    except Exception:
                        pass

                view = VirtualBrokerView(
                    broker_state="OPERATIONAL" if is_connected else "NOT_INITIALIZED",
                    connection_state="CONNECTED" if is_connected else "DISCONNECTED",
                    account_number="VIRTUAL-ACCOUNT-01" if is_connected else "—",
                    cash_balance=cash_val,
                    margin_used=margin_used_val,
                    margin_available=margin_avail_val,
                    positions=positions_list,
                    realized_pnl=realized_pnl_val,
                    audit_logs=list(self._audit_logs),
                )
                return asdict(view)
            return asdict(VirtualBrokerView(audit_logs=list(self._audit_logs)))

        elif tab_id == TabEnvironmentId.PAPER.value:
            return asdict(PaperTradingView(audit_logs=list(self._audit_logs)))

        elif tab_id == TabEnvironmentId.LIVE.value:
            return asdict(LiveTradingView(audit_logs=list(self._audit_logs)))

        else:
            return {"error": f"UNKNOWN_TAB_ID: {tab_id}"}

    def handle_command(self, command: str) -> dict[str, Any]:
        """Execute real command against RiskEngine, RuntimeController, and Broker."""
        if command == "PANIC_HALT":
            halt_actions: list[str] = []

            # 1. Trigger RiskEngine pre-trade Kill Switch
            if self._risk_engine is not None and hasattr(self._risk_engine, "trigger_kill_switch"):
                self._risk_engine.trigger_kill_switch(reason="UI_PANIC_HALT")
                halt_actions.append("RiskEngine kill switch triggered")
            else:
                halt_actions.append("RiskEngine not injected (skipped)")

            # 2. Halt RuntimeController execution
            runtime_stopped = False
            if self._runtime_controller is not None and hasattr(self._runtime_controller, "stop"):
                try:
                    self._runtime_controller.stop()
                    runtime_stopped = True
                    halt_actions.append("RuntimeController stopped")
                except Exception as exc:
                    halt_actions.append(f"RuntimeController stop error: {exc}")
            else:
                halt_actions.append("RuntimeController not injected (skipped)")

            # 3. Log audit event
            log_entry = f"PANIC_HALT executed: {', '.join(halt_actions)}"
            self._audit_logs.append(log_entry)

            return {
                "success": True,
                "command": "PANIC_HALT",
                "kill_switch_active": self._is_kill_switch_active(),
                "runtime_state": self._get_runtime_state(),
                "actions": halt_actions,
                "message": log_entry,
            }

        return {
            "success": False,
            "command": command,
            "error": f"UNSUPPORTED_COMMAND: {command}",
        }
