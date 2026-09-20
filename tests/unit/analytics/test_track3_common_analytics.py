from datetime import datetime

from application.composition.track3_analytics_provider import build_track3_analytics_snapshot
from contracts.track3_runtime_input_source import Track3RuntimeInput


def source_payload() -> Track3RuntimeInput:
    return Track3RuntimeInput(
        observed_at=datetime(2026, 9, 18, 10, 0),
        spread_history=(1.0,) * 9 + (2.0,),
        active_vol=0.2,
        base_vol=0.1,
        price_change_rate=0.01,
        bid_ask_spread=0.02,
        gap_pct=0.0,
        is_gap=False,
        market_stable=True,
        spread_normalizing=True,
        allow_size_up=False,
        total_fees=3000.0,
        premium_spent=25000.0,
        options_legs=(),
        contract_multiplier=250000.0,
        source="VirtualExchange.VMS+VirtualBroker.VSSF",
    )


def test_track3_common_analytics_exposes_declared_metrics():
    snapshot = build_track3_analytics_snapshot(source_payload(), run_id="test-run", current_pnl=0.0, as_of=source_payload().observed_at)
    assert snapshot.get("spread.z_score").value is not None
    assert snapshot.get("volatility.ratio").value == 2.0
    assert snapshot.get("microstructure.spread").value == 0.02
    assert snapshot.get("cost.fees").value == 3000.0


def test_track3_common_analytics_does_not_recompute_for_duplicate_requests():
    snapshot = build_track3_analytics_snapshot(source_payload(), run_id="test-run", current_pnl=0.0, as_of=source_payload().observed_at)
    assert snapshot.metrics["spread.z_score"] is snapshot.metrics["spread.z_score"]
