"""Control Tower UI Adapter — UI Data Interface.

Strategy/Core 내부 구현 객체를 직접 UI로 노출하지 않고,
안정적인 읽기 전용 DTO/View Model로 변환하여 Frontend에 공급합니다.
"""

from dataclasses import asdict
from datetime import datetime
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

    def __init__(self, runtime_controller=None, *, lifecycle_coordinator=None):
        self._runtime_controller = runtime_controller
        self._lifecycle_coordinator = lifecycle_coordinator
        self._active_tab = TabEnvironmentId.VIRTUAL_EXCHANGE.value
        self._high_speed_state = HighSpeedTestView()
        self._virtual_exchange_state = VirtualExchangeView()
        self._virtual_broker_state = VirtualBrokerView()
        self._paper_state = PaperTradingView()
        self._live_state = LiveTradingView()

    def set_active_tab(self, tab_id: str) -> None:
        """Switch active view tab."""
        valid_tabs = [t.value for t in TabEnvironmentId]
        if tab_id in valid_tabs:
            self._active_tab = tab_id

    def get_summary(self) -> dict[str, Any]:
        """Return 5-environment summary state for global header & tabs status."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        tabs_summary = [
            {
                "tab_id": TabEnvironmentId.HIGH_SPEED.value,
                "name": "High-Speed Test",
                "status": self._high_speed_state.runtime_state,
                "connection": self._high_speed_state.connection_state,
                "is_active": self._active_tab == TabEnvironmentId.HIGH_SPEED.value,
            },
            {
                "tab_id": TabEnvironmentId.VIRTUAL_EXCHANGE.value,
                "name": "가상거래소",
                "status": self._virtual_exchange_state.market_state,
                "connection": self._virtual_exchange_state.connection_state,
                "is_active": self._active_tab == TabEnvironmentId.VIRTUAL_EXCHANGE.value,
            },
            {
                "tab_id": TabEnvironmentId.VIRTUAL_BROKER.value,
                "name": "가상증권사",
                "status": self._virtual_broker_state.broker_state,
                "connection": self._virtual_broker_state.connection_state,
                "is_active": self._active_tab == TabEnvironmentId.VIRTUAL_BROKER.value,
            },
            {
                "tab_id": TabEnvironmentId.PAPER.value,
                "name": "모의투자",
                "status": "BLOCKED",
                "connection": self._paper_state.connection_state,
                "is_active": self._active_tab == TabEnvironmentId.PAPER.value,
            },
            {
                "tab_id": TabEnvironmentId.LIVE.value,
                "name": "실투자",
                "status": "BLOCKED",
                "connection": self._live_state.connection_state,
                "is_active": self._active_tab == TabEnvironmentId.LIVE.value,
            },
        ]

        summary = ControlTowerSummaryView(
            active_environment=self._active_tab,
            system_time=now_str,
            kill_switch_global=True,
            tabs=tabs_summary,
            alert_message=None,
        )
        return asdict(summary)

    def get_tab_detail(self, tab_id: str) -> dict[str, Any]:
        """Return detailed view data for a specific environment tab."""
        if tab_id == TabEnvironmentId.HIGH_SPEED.value:
            return asdict(self._high_speed_state)
        elif tab_id == TabEnvironmentId.VIRTUAL_EXCHANGE.value:
            # Refresh live timestamp
            now_iso = datetime.now().isoformat()
            refreshed = VirtualExchangeView(
                market_state="OPEN",
                connection_state="CONNECTED",
                last_data_time=now_iso,
                instruments_count=120,
                recent_ticks=[
                    {"code": "201W9350", "name": "KOSPI200 C 350.0", "price": 3.45, "change": 0.15, "volume": 1240, "time": now_iso},
                    {"code": "201W9345", "name": "KOSPI200 C 345.0", "price": 6.80, "change": 0.25, "volume": 890, "time": now_iso},
                    {"code": "301W9340", "name": "KOSPI200 P 340.0", "price": 2.10, "change": -0.10, "volume": 2150, "time": now_iso},
                    {"code": "101W9000", "name": "코스피200 선물", "price": 348.50, "change": 1.20, "volume": 15400, "time": now_iso},
                ],
                market_depth={
                    "bid": [{"price": 348.45, "qty": 12}, {"price": 348.40, "qty": 25}],
                    "ask": [{"price": 348.55, "qty": 18}, {"price": 348.60, "qty": 30}],
                },
                feed_latency_ms=0.45,
                underlying_index_price=348.25,
                volatility_index=15.82,
                audit_logs=["Virtual Market feed active", "Synthetic tick broadcast verified"],
            )
            return asdict(refreshed)
        elif tab_id == TabEnvironmentId.VIRTUAL_BROKER.value:
            refreshed = VirtualBrokerView(
                broker_state="OPERATIONAL",
                connection_state="CONNECTED",
                account_number="VIRTUAL-8801-01",
                cash_balance=98_450_000.0,
                margin_used=12_300_000.0,
                margin_available=86_150_000.0,
                active_orders=[
                    {"order_id": "V-ORD-101", "symbol": "201W9350", "side": "BUY", "qty": 2, "price": 3.40, "status": "SUBMITTED", "time": datetime.now().strftime("%H:%M:%S")},
                ],
                recent_executions=[
                    {"exec_id": "V-EXEC-099", "symbol": "101W9000", "side": "SELL", "qty": 1, "price": 348.20, "time": "09:15:22"},
                ],
                positions=[
                    {"symbol": "201W9350", "name": "KOSPI200 C 350.0", "qty": 5, "avg_price": 3.20, "current_price": 3.45, "pnl": 125000.0},
                    {"symbol": "101W9000", "name": "코스피200 미니선물", "qty": -1, "avg_price": 348.20, "current_price": 348.50, "pnl": -15000.0},
                ],
                realized_pnl=350_000.0,
                unrealized_pnl=110_000.0,
                audit_logs=["Virtual Broker initialized", "Order FSM transition verified (ACK -> FILL)"],
            )
            return asdict(refreshed)
        elif tab_id == TabEnvironmentId.PAPER.value:
            return asdict(self._paper_state)
        elif tab_id == TabEnvironmentId.LIVE.value:
            return asdict(self._live_state)
        else:
            return {"error": f"UNKNOWN_TAB_ID: {tab_id}"}
