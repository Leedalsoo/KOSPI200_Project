"""Test Control Tower 5 Environment Views.

5개 환경 탭(High-Speed Test, 가상거래소, 가상증권사, 모의투자, 실투자)의 뷰모델이
누락 없이 존재하고, 외부 미연결 시 가짜 성공 없이 DISCONNECTED/BLOCKED를 정직하게
표시하는지 검증합니다.
"""

from dataclasses import asdict
from interfaces.control_tower.view_models import (
    ControlTowerSummaryView,
    HighSpeedTestView,
    LiveTradingView,
    PaperTradingView,
    TabEnvironmentId,
    VirtualBrokerView,
    VirtualExchangeView,
)


def test_5_environment_tabs_enum_has_all_required_environments():
    expected_tabs = {
        "high_speed",
        "virtual_exchange",
        "virtual_broker",
        "paper",
        "live",
    }
    actual_tabs = {t.value for t in TabEnvironmentId}
    assert actual_tabs == expected_tabs, f"5개 탭 목록 불일치: {actual_tabs}"


def test_high_speed_test_view_defaults():
    view = HighSpeedTestView()
    assert view.tab_id == "high_speed"
    assert view.tab_name == "High-Speed Test"
    assert view.speed_multiplier == 100.0
    assert view.scenario_name == "SYNTHETIC_HIGH_SPEED"
    assert view.progress_ratio == 0.0
    assert isinstance(view.positions, list)


def test_virtual_exchange_view_defaults():
    view = VirtualExchangeView()
    assert view.tab_id == "virtual_exchange"
    assert view.tab_name == "가상거래소"
    assert view.market_state == "OPEN"
    assert view.connection_state == "CONNECTED"


def test_virtual_broker_view_defaults():
    view = VirtualBrokerView()
    assert view.tab_id == "virtual_broker"
    assert view.tab_name == "가상증권사"
    assert view.broker_state == "OPERATIONAL"
    assert view.account_number.startswith("VIRTUAL")
    assert view.cash_balance > 0


def test_paper_trading_view_enforces_fail_safe_disconnected_state():
    """모의투자 환경은 실제 KIS 서버 미연결 시 가짜 연결/성공을 표시하지 않아야 함."""
    view = PaperTradingView()
    assert view.tab_id == "paper"
    assert view.connection_state == "DISCONNECTED"
    assert view.runtime_state == "STOPPED"
    assert view.broker_ready is False
    assert view.cash_balance is None
    assert "openapivts.koreainvestment.com" in view.api_endpoint
    assert "미수행" in view.blocked_reason or "BLOCKED" in view.blocked_reason


def test_live_trading_view_enforces_fail_safe_blocked_state():
    """실투자 환경은 실계좌 미연결 시 가짜 LIVE 성공을 표시하지 않고 완전 차단 상태여야 함."""
    view = LiveTradingView()
    assert view.tab_id == "live"
    assert view.connection_state == "DISCONNECTED"
    assert view.runtime_state == "STOPPED"
    assert view.live_approval is False
    assert view.kill_switch_engaged is True
    assert view.execution_allowed is False
    assert view.total_margin is None
    assert "차단" in view.blocked_reason or "BLOCKED" in view.blocked_reason


def test_views_are_serializable_to_dict():
    """모든 뷰모델은 직렬화 가능한 dict로 안전하게 변환되어야 함."""
    views = [
        HighSpeedTestView(),
        VirtualExchangeView(),
        VirtualBrokerView(),
        PaperTradingView(),
        LiveTradingView(),
        ControlTowerSummaryView(),
    ]
    for v in views:
        d = asdict(v)
        assert isinstance(d, dict)
        assert len(d) > 0
