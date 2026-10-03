from pathlib import Path

from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner


def test_high_speed_replay_reaches_real_virtual_runtime_boundary():
    dataset = Path("data/synthetic_market_data/1y_5min_v1")
    result = HighSpeedVirtualRuntimeReplayRunner(dataset, run_id="TEST-HS-RUNTIME").run(max_events=10)

    assert result.events == 10
    assert result.exhausted is False
    assert result.run_id == "TEST-HS-RUNTIME"
    assert result.pnl_status == "VSSF_ACCOUNT_PNL_CONNECTED"
    assert result.multi_leg_decisions >= 0
    assert result.net_pnl == result.realized_pnl + result.unrealized_pnl
    assert result.events_per_second > 0


def test_high_speed_replay_can_run_without_strategy_signals_being_forced():
    dataset = Path("data/synthetic_market_data/1y_5min_v1")
    result = HighSpeedVirtualRuntimeReplayRunner(dataset, run_id="TEST-HS-NO-FORCE").run(max_events=10)

    assert result.events == 10
    assert result.signals >= 0
    assert result.approved >= 0
    assert result.routed >= 0
    assert result.filled >= 0
