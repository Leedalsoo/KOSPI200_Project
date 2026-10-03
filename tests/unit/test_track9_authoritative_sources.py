from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from application.composition.track9_analytics_provider import build_track9_analytics_snapshot
from contracts.track9_authoritative_sources import Track9EventRiskSnapshot
from environments.virtual.authoritative_vssf.track9_position_execution_read_model import VirtualTrack9PositionExecutionReadModel

def test_virtual_track9_position_execution_source_uses_execution_and_open_lots():
    report = SimpleNamespace(
        status="FILLED", execution_id="e1", execution_price=Decimal("2.5"),
        filled_quantity=2
    )
    bridge = SimpleNamespace(
        run_id="run1",
        groups={"g1": (report,)},
        execution_legs={"e1": {
            "strategy_id": "track9_event_overnight_insurance",
            "side": "BUY", "asset_type": "OPTION",
            "contract_multiplier": Decimal("250000"),
        }},
        option_position_attribution=SimpleNamespace(snapshot=lambda: (
            SimpleNamespace(strategy_id="track9_event_overnight_insurance", side="SELL", remaining_quantity=3),
        )),
        insurance_position=SimpleNamespace(snapshot=lambda: (
            SimpleNamespace(strategy_id="track9_event_overnight_insurance", position_role=SimpleNamespace(NONE="NONE"), remaining_quantity=1),
        )),
    )
    source = VirtualTrack9PositionExecutionReadModel(bridge)
    snapshot = source.snapshot(run_id="run1", strategy_id="track9_event_overnight_insurance")
    assert snapshot is not None
    assert snapshot.active_sell_qty == 3
    assert snapshot.insurance_qty == 1
    assert snapshot.premium_spent == Decimal("1250000")

def test_track9_analytics_accepts_authoritative_source_values():
    data = SimpleNamespace(iv_spike=Decimal("1"), iv_crush=Decimal("0"))
    snapshot = build_track9_analytics_snapshot(
        data, run_id="run1", as_of=datetime.now(timezone.utc),
        active_sell_qty=3, insurance_qty=1, event_upcoming={"id": "E1"},
        event_budget=Decimal("100000"), estimated_event_cost=Decimal("25000"),
        premium_spent=Decimal("1250000"),
    )
    assert snapshot.get("portfolio.active_sell_qty").value == 3
    assert snapshot.get("portfolio.insurance_qty").value == 1
    assert snapshot.get("events.upcoming").value == {"id": "E1"}
    assert snapshot.get("portfolio.event_budget").value == Decimal("100000")
    assert snapshot.get("portfolio.estimated_event_cost").value == Decimal("25000")
    assert snapshot.get("portfolio.premium_spent").value == Decimal("1250000")
