"""Test Runtime UI Path — 실제 런타임 및 가상 환경 번들의 UI 투영 경로 검증.

UI Adapter가 실제 RuntimeController 및 VirtualEnvironmentBundle의 실제 상태를
훼손이나 위조 없이 Frontend DTO로 전달하는 결정적 런타임 경로를 검증합니다.
"""

from decimal import Decimal
from datetime import datetime

from contracts.types import CanonicalMarketTick, EnvironmentType
from environments.virtual.account.virtual_account import VirtualAccount
from environments.virtual.position.virtual_position import VirtualPosition
from environments.virtual.bundle import VirtualEnvironmentBundle
from application.environment_hub.hub import EnvironmentHub
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.runtime_controller.controller import RuntimeController
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


class ConcreteTestClock:
    def now(self):
        return datetime(2026, 9, 11, 10, 0, 0)


class ConcreteMarketFeed:
    def __init__(self):
        self.last_tick = CanonicalMarketTick(
            instrument_id="KOSPI200_202609",
            observed_at=datetime(2026, 9, 11, 10, 0, 0),
            price=Decimal("350.25"),
            volume=Decimal("500"),
            source_sequence=12,
        )


def test_runtime_ui_path_virtual_environment_projection():
    """실제 번들의 상태가 ControlTowerUIAdapter를 통해 일대일로 투영되는지 검증."""
    clock = ConcreteTestClock()
    account = VirtualAccount(cash=Decimal("75000000"), margin_used=Decimal("15000000"), clock=clock)
    position = VirtualPosition(instrument_id="201W9350", quantity=5, average_price=3.40, clock=clock)
    market = ConcreteMarketFeed()

    bundle = VirtualEnvironmentBundle(
        config=EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual_runtime"),
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
    controller.start(EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual_runtime"), RuntimePolicy())

    adapter = ControlTowerUIAdapter(runtime_controller=controller)

    # 1. Summary 검증
    summary = adapter.get_summary()
    tabs_map = {t["tab_id"]: t for t in summary["tabs"]}
    assert tabs_map["virtual_exchange"]["status"] == "OPEN"
    assert tabs_map["virtual_exchange"]["connection"] == "CONNECTED"
    assert tabs_map["virtual_broker"]["status"] == "OPERATIONAL"
    assert tabs_map["virtual_broker"]["connection"] == "CONNECTED"
    assert tabs_map["paper"]["status"] == "BLOCKED"
    assert tabs_map["live"]["status"] == "BLOCKED"

    # 2. Virtual Exchange Detail 검증 (실제 ConcreteMarketFeed 투영)
    ve = adapter.get_tab_detail("virtual_exchange")
    assert ve["connection_state"] == "CONNECTED"
    assert ve["market_state"] == "OPEN"
    assert ve["underlying_index_price"] == 350.25
    assert len(ve["recent_ticks"]) == 1
    assert ve["recent_ticks"][0]["code"] == "KOSPI200_202609"
    assert ve["recent_ticks"][0]["price"] == 350.25
    assert ve["recent_ticks"][0]["volume"] == 500.0

    # 3. Virtual Broker Detail 검증 (실제 VirtualAccount, VirtualPosition 투영)
    vb = adapter.get_tab_detail("virtual_broker")
    assert vb["connection_state"] == "CONNECTED"
    assert vb["broker_state"] == "OPERATIONAL"
    assert vb["cash_balance"] == 75000000.0
    assert vb["margin_used"] == 15000000.0
    assert vb["margin_available"] == 60000000.0
    assert len(vb["positions"]) == 1
    assert vb["positions"][0]["symbol"] == "201W9350"
    assert vb["positions"][0]["qty"] == 5
