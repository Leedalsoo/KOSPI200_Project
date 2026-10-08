import json
from pathlib import Path

from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner


def _write_report(result, output_path: Path) -> None:
    payload = {
        "dataset": result.dataset,
        "run_id": result.run_id,
        "events": result.events,
        "signals": result.signals,
        "approved": result.approved,
        "routed": result.routed,
        "filled": result.filled,
        "rejected": result.rejected,
        "exhausted": result.exhausted,
        "events_per_second": result.events_per_second,
        "pnl_status": result.pnl_status,
        "multi_leg_decisions": result.multi_leg_decisions,
        "strategy_signal_counts": dict(result.strategy_signal_counts),
        "strategy_status": [
            {
                "strategy_id": s.strategy_id,
                "reaction_signals": s.reaction_signals,
                "execution_signals": s.execution_signals,
                "non_execution_signals": s.non_execution_signals,
                "unavailable": s.unavailable,
                "runtime_failures": s.runtime_failures,
                "decision_rejected": s.decision_rejected,
                "risk_rejected": s.risk_rejected,
                "approved": s.approved,
                "routed": s.routed,
                "filled_quantity": s.filled_quantity,
            }
            for s in result.strategy_status
        ],
        "realized_pnl": result.realized_pnl,
        "unrealized_pnl": result.unrealized_pnl,
        "net_pnl": result.net_pnl,
        "execution_ids": list(result.execution_ids),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def test_high_speed_3m_49140_event_e2e_report():
    dataset = Path("data/synthetic_market_data/3m_5min_baseline_v1")
    output = Path("verification/results/high_speed_3m_5min_e2e_20261007.json")
    result = HighSpeedVirtualRuntimeReplayRunner(dataset, run_id="TEST-HS-3M-49140").run()
    _write_report(result, output)

    assert output.exists()
    assert result.events == 49140
    assert result.exhausted is True
    assert result.pnl_status == "VSSF_ACCOUNT_PNL_CONNECTED"
    assert result.net_pnl == result.realized_pnl + result.unrealized_pnl
    assert result.events_per_second > 0
    strategy_ids = {s.strategy_id for s in result.strategy_status}
    assert strategy_ids == {f"track{i}" for i in range(1, 10)}
    assert all(s.runtime_failures >= 0 for s in result.strategy_status)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["events"] == 49140
    assert saved["exhausted"] is True
    assert len(saved["strategy_status"]) == 9
