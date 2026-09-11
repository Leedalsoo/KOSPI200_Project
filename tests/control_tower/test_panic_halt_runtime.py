"""Test Panic Halt Runtime — PANIC_HALT 실제 상태 전이 및 킬스위치 실행 경로 검증.

HTTP 200이나 단순 문자열 응답이 아니라,
명령 전후의 RiskEngine 킬스위치 상태와 RuntimeController 실행 상태 전이를 직접 비교 검증합니다.
"""

from decimal import Decimal
from datetime import datetime

from contracts.types import EnvironmentType
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from environments.virtual.account.virtual_account import VirtualAccount
from environments.virtual.position.virtual_position import VirtualPosition
from environments.virtual.bundle import VirtualEnvironmentBundle
from application.environment_hub.hub import EnvironmentHub
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.runtime_controller.controller import RuntimeController
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


class ConcreteMarginCalculator:
    def calculate_order_margin(self, command):
        return 1500.0


class ConcreteClock:
    def now(self):
        return datetime(2026, 9, 11, 10, 30, 0)


def test_panic_halt_actual_state_transition():
    """PANIC_HALT 발동 시 RiskEngine과 RuntimeController의 실제 상태 전이를 정밀 대조 검증."""
    clock = ConcreteClock()
    account = VirtualAccount(cash=Decimal("20000000"), clock=clock)
    position = VirtualPosition(instrument_id="201W9350", quantity=2, clock=clock)
    bundle = VirtualEnvironmentBundle(
        config=EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual_runtime"),
        policy=RuntimePolicy(),
        market=object(),
        clock=clock,
        broker=object(),
        account=account,
        position=position,
        execution=object(),
    )
    bundle.initialize()
    bundle.connect()
    bundle.start()

    factory = EnvironmentFactory(virtual_builder=lambda c, p: bundle)
    hub = EnvironmentHub(factory)
    controller = RuntimeController(hub)
    controller.start(EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual_runtime"), RuntimePolicy())

    risk_engine = RiskEngine(config=RiskConfig(), margin_engine=ConcreteMarginCalculator())

    # --- 1. [BEFORE 상태 검증] ---
    assert risk_engine.is_kill_switch_active() is False, "발동 전 kill switch는 비활성 상태여야 함"
    assert controller.status().state == "RUNNING", "발동 전 런타임은 RUNNING 상태여야 함"

    adapter = ControlTowerUIAdapter(runtime_controller=controller, risk_engine=risk_engine)
    before_summary = adapter.get_summary()
    assert before_summary["kill_switch_global"] is False
    assert before_summary["alert_message"] is None

    # --- 2. [PANIC_HALT 명령 실행] ---
    result = adapter.handle_command("PANIC_HALT")

    # --- 3. [명령 응답 계약 검증] ---
    assert result["success"] is True
    assert result["command"] == "PANIC_HALT"
    assert result["kill_switch_active"] is True
    assert result["runtime_state"] == "STOPPED"
    assert "RiskEngine kill switch triggered" in result["actions"]
    assert "RuntimeController stopped" in result["actions"]

    # --- 4. [AFTER 실제 객체 상태 전이 검증] ---
    assert risk_engine.is_kill_switch_active() is True, "발동 후 kill switch는 반드시 True로 전이되어야 함"
    assert controller.status().state == "STOPPED", "발동 후 런타임은 반드시 STOPPED로 전이되어야 함"

    # --- 5. [AFTER UI Observable State 검증] ---
    after_summary = adapter.get_summary()
    assert after_summary["kill_switch_global"] is True
    assert "KILL SWITCH ACTIVE" in after_summary["alert_message"]
