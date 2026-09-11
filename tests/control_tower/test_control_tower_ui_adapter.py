"""Test Control Tower UI Adapter — 실제 Runtime 연결 및 가짜 데이터 완전 배제 검증.

UI Adapter가 Strategy/Core 내부 구현을 노출하지 않고,
실제 Runtime, Environment, RiskEngine의 상태만을 순수 DTO로 변환하여 공급하며,
PANIC_HALT 명령 시 실제 RiskEngine Kill Switch와 RuntimeController를 제어하는지 검증합니다.
"""

from decimal import Decimal
from datetime import datetime

from contracts.types import CanonicalMarketTick, EnvironmentType
from core.risk.risk_engine import RiskEngine
from core.risk.risk_config import RiskConfig
from environments.virtual.account.virtual_account import VirtualAccount
from environments.virtual.position.virtual_position import VirtualPosition
from environments.virtual.bundle import VirtualEnvironmentBundle
from application.environment_hub.hub import EnvironmentHub
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.runtime_controller.controller import RuntimeController
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from interfaces.control_tower.view_models import TabEnvironmentId


class DummyMarginEngine:
    def calculate_order_margin(self, command):
        return 1000.0


class DummyClock:
    def now(self):
        return datetime(2026, 9, 11, 9, 30, 0)


class DummyMarket:
    def __init__(self):
        self.last_tick = CanonicalMarketTick(
            instrument_id="KOSPI200_VIRTUAL",
            observed_at=datetime(2026, 9, 11, 9, 30, 0),
            price=Decimal("352.50"),
            volume=Decimal("150"),
            source_sequence=1,
        )


def test_ui_adapter_provides_summary_with_5_tabs():
    adapter = ControlTowerUIAdapter()
    summary = adapter.get_summary()

    assert "active_environment" in summary
    assert "tabs" in summary
    assert len(summary["tabs"]) == 5

    tab_ids = [t["tab_id"] for t in summary["tabs"]]
    assert tab_ids == [
        "high_speed",
        "virtual_exchange",
        "virtual_broker",
        "paper",
        "live",
    ]


def test_ui_adapter_tab_switching():
    adapter = ControlTowerUIAdapter()
    adapter.set_active_tab("virtual_broker")
    summary = adapter.get_summary()
    assert summary["active_environment"] == "virtual_broker"

    # 유효하지 않은 탭 요청 시 기존 탭 유지
    adapter.set_active_tab("invalid_tab_name")
    summary = adapter.get_summary()
    assert summary["active_environment"] == "virtual_broker"


def test_ui_adapter_no_fake_data_when_unconnected():
    """연결된 번들이 없을 때 가짜 데이터를 생성하지 않고 정직하게 비어있음을 반환하는지 검증."""
    adapter = ControlTowerUIAdapter()

    # 1. Virtual Exchange
    ve_detail = adapter.get_tab_detail("virtual_exchange")
    assert ve_detail["connection_state"] == "DISCONNECTED"
    assert ve_detail["market_state"] == "STOPPED"
    assert ve_detail["recent_ticks"] == []
    assert ve_detail["underlying_index_price"] is None

    # 2. Virtual Broker
    vb_detail = adapter.get_tab_detail("virtual_broker")
    assert vb_detail["connection_state"] == "DISCONNECTED"
    assert vb_detail["broker_state"] == "NOT_INITIALIZED"
    assert vb_detail["account_number"] == "—"
    assert vb_detail["cash_balance"] is None
    assert vb_detail["active_orders"] == []
    assert vb_detail["positions"] == []

    # 3. High-Speed Test
    hs_detail = adapter.get_tab_detail("high_speed")
    assert hs_detail["connection_state"] == "DISCONNECTED"
    assert hs_detail["runtime_state"] == "STOPPED"
    assert hs_detail["processed_ticks"] == 0
    assert hs_detail["total_pnl"] == 0.0

    # 4. Paper & Live
    paper_detail = adapter.get_tab_detail("paper")
    assert paper_detail["connection_state"] == "DISCONNECTED"
    assert "blocked_reason" in paper_detail

    live_detail = adapter.get_tab_detail("live")
    assert live_detail["connection_state"] == "DISCONNECTED"
    assert live_detail["kill_switch_engaged"] is True


def test_ui_adapter_with_real_runtime_controller_and_virtual_bundle():
    """실제 VirtualEnvironmentBundle의 마켓 틱과 계좌/포지션 스냅샷이 UI DTO에 투영되는지 검증."""
    clock = DummyClock()
    account = VirtualAccount(cash=Decimal("50000000"), margin_used=Decimal("5000000"), clock=clock)
    position = VirtualPosition(instrument_id="201W9350", quantity=3, average_price=3.25, clock=clock)
    market = DummyMarket()

    bundle = VirtualEnvironmentBundle(
        config=EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual"),
        policy=RuntimePolicy(),
        market=market,
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
    controller.start(EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual"), RuntimePolicy())

    adapter = ControlTowerUIAdapter(runtime_controller=controller)

    # Summary 검증
    summary = adapter.get_summary()
    tabs_dict = {t["tab_id"]: t for t in summary["tabs"]}
    assert tabs_dict["virtual_exchange"]["status"] == "OPEN"
    assert tabs_dict["virtual_exchange"]["connection"] == "CONNECTED"
    assert tabs_dict["virtual_broker"]["status"] == "OPERATIONAL"

    # Virtual Exchange Detail 검증 (실제 DummyMarket의 틱 투영)
    ve_detail = adapter.get_tab_detail("virtual_exchange")
    assert ve_detail["connection_state"] == "CONNECTED"
    assert ve_detail["market_state"] == "OPEN"
    assert ve_detail["underlying_index_price"] == 352.50
    assert len(ve_detail["recent_ticks"]) == 1
    assert ve_detail["recent_ticks"][0]["code"] == "KOSPI200_VIRTUAL"
    assert ve_detail["recent_ticks"][0]["price"] == 352.50

    # Virtual Broker Detail 검증 (실제 VirtualAccount, VirtualPosition의 스냅샷 투영)
    vb_detail = adapter.get_tab_detail("virtual_broker")
    assert vb_detail["connection_state"] == "CONNECTED"
    assert vb_detail["cash_balance"] == 50000000.0
    assert vb_detail["margin_used"] == 5000000.0
    assert vb_detail["margin_available"] == 45000000.0
    assert len(vb_detail["positions"]) == 1
    assert vb_detail["positions"][0]["symbol"] == "201W9350"
    assert vb_detail["positions"][0]["qty"] == 3


def test_panic_halt_actual_execution_path():
    """PANIC_HALT 명령 시 실제 RiskEngine Kill Switch와 RuntimeController.stop()이 가동되는지 검증."""
    clock = DummyClock()
    account = VirtualAccount(cash=Decimal("10000000"), clock=clock)
    position = VirtualPosition(instrument_id="201W9350", quantity=0, clock=clock)
    bundle = VirtualEnvironmentBundle(
        config=EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual"),
        policy=RuntimePolicy(),
        market=DummyMarket(),
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
    controller.start(EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual"), RuntimePolicy())

    risk_engine = RiskEngine(config=RiskConfig(), margin_engine=DummyMarginEngine())
    assert risk_engine.is_kill_switch_active() is False
    assert controller.status().state == "RUNNING"

    adapter = ControlTowerUIAdapter(runtime_controller=controller, risk_engine=risk_engine)
    assert adapter.get_summary()["kill_switch_global"] is False

    # PANIC_HALT 실행
    cmd_result = adapter.handle_command("PANIC_HALT")
    assert cmd_result["success"] is True
    assert cmd_result["command"] == "PANIC_HALT"

    # 실제 RiskEngine 및 RuntimeController 상태 전이 검증
    assert risk_engine.is_kill_switch_active() is True
    assert controller.status().state == "STOPPED"

    # UI Summary에 실제 킬스위치 상태 반영 확인
    summary = adapter.get_summary()
    assert summary["kill_switch_global"] is True
    assert "KILL SWITCH ACTIVE" in summary["alert_message"]
