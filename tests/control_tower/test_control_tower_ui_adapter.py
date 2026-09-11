"""Test Control Tower UI Adapter.

UI Adapter가 Strategy/Core 내부 구현을 노출하지 않고,
안정적인 읽기 전용 DTO를 5개 환경 탭에 제공하는지 검증합니다.
"""

from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from interfaces.control_tower.view_models import TabEnvironmentId


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


def test_ui_adapter_details_for_all_5_environments():
    adapter = ControlTowerUIAdapter()

    for tab_id in [t.value for t in TabEnvironmentId]:
        detail = adapter.get_tab_detail(tab_id)
        assert isinstance(detail, dict)
        assert detail.get("tab_id") == tab_id
        assert "error" not in detail

    # Paper / Live 환경은 명시적으로 차단/미연결 상태여야 함
    paper_detail = adapter.get_tab_detail("paper")
    assert paper_detail["connection_state"] == "DISCONNECTED"
    assert "blocked_reason" in paper_detail

    live_detail = adapter.get_tab_detail("live")
    assert live_detail["connection_state"] == "DISCONNECTED"
    assert live_detail["kill_switch_engaged"] is True
    assert "blocked_reason" in live_detail


def test_ui_adapter_returns_pure_dict_dto():
    """어댑터는 Core 도메인 객체가 아닌 순수 Python dict DTO만 반환하여 격리를 유지해야 함."""
    adapter = ControlTowerUIAdapter()
    detail = adapter.get_tab_detail("virtual_exchange")
    assert type(detail) is dict
    assert "recent_ticks" in detail
    assert isinstance(detail["recent_ticks"], list)
