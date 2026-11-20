from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import (
    attach_standard_automated_loop,
)
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import (
    SyntheticRuntimeSources,
    build_synthetic_option_master,
)
from environments.high_speed.validation_only_s8_runtime_adapter import (
    S8ValidationOnlyRuntimeAdapter,
)
from environments.high_speed.virtual_runtime_replay import (
    _publish_contract_scoped_replay_quote,
)
from environments.virtual.clock import VirtualClock

ROOT = Path(__file__).resolve().parents[3]
STRATEGY_ID = "track8_macro_regime_monthly_strangle"
EXPECTED_PNL = {
    "high_vol": Decimal(-627500),
    "normal": Decimal(-465000),
}
EXPECTED_DATASET_SHA256 = {
    "high_vol": "fda113074213919b2037cbaf8c3076406f4efe92d5d2b45ae6b935f37df84050",
    "normal": "6667d0d0a7b700ceaa927289ad1bce6454342c8577af1ee0d3b6dc65aecdc48a",
}


def _run_scenario(regime: str, *, speed: float) -> dict[str, object]:
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    replay_adapter = SyntheticReplayAdapter(folder, manifest_path=folder / "manifest.json")
    option_master = build_synthetic_option_master(folder, validation_only_adapter=replay_adapter)
    validation_gate = S8ValidationOnlyRuntimeAdapter(
        dataset=folder,
        manifest_path=folder / "manifest.json",
        risk_profile_path=ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json",
    )
    assert validation_gate.entry_quantity_per_leg == 1
    assert validation_gate.evidence.dataset_sha256 == EXPECTED_DATASET_SHA256[regime]

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)

    mode = "FAST" if speed == float("inf") else "DETAILED"
    run_id = f"S8-CURRENT-NATURAL-{regime.upper()}-{mode}"
    validation_gate.bind_run_id(run_id)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=((STRATEGY_ID, "2.0"),),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
        validation_only_s8_runtime_adapter=validation_gate,
    )
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    initial_ticks = tuple(HighSpeedReplayRunner(folder, synthetic_adapter=replay_adapter).events())
    assert len(initial_ticks) == 216
    clock = VirtualClock(datetime.fromisoformat(initial_ticks[0].timestamp))

    def on_tick(tick) -> None:
        _publish_contract_scoped_replay_quote(
            tick,
            option_master=option_master,
            market=bootstrap.bundle.market,
            order_book=vssf.order_book,
        )
        sources.set_tick(tick)
        bootstrap.bundle.market.publish_replay_tick(tick)

    report = HighSpeedReplayRunner(
        folder,
        synthetic_adapter=replay_adapter,
        clock=clock,
    ).run(speed=speed, on_event=on_tick)
    assert report.events == 216
    assert report.exhausted is True

    bridge = loop.multi_leg_bridge
    groups = bridge.position_groups.all()
    snapshots = tuple(bridge.position_groups.snapshot(group_id) for group_id in groups)
    lots = tuple(bridge.position_lot_store.history())
    close_events = tuple(bridge.position_lot_store.close_events())
    fee_rows = tuple(bridge.fee_ledger.query(run_id=run_id))
    strategy = loop.strategy_hub._orchestrator._registry.get(STRATEGY_ID, "2.0")

    assert vssf.metrics["market_ticks"] == 216
    assert vssf.metrics["order_commands"] == 8
    assert vssf.metrics["executions_issued"] == 8
    assert len(groups) == 2
    assert all(len(group.legs) == 2 for group in groups.values())
    assert all(leg.status.value == "FILLED" for group in groups.values() for leg in group.legs)
    assert len(lots) == 4
    assert len(close_events) == 4
    assert {event.source_lot_execution_id for event in close_events} == {
        lot.execution_id for lot in lots
    }
    assert all(event.quantity == 1 for event in close_events)
    assert bridge.position_lot_store.open_lots() == ()
    assert bridge.pending_legs == {}
    assert vssf.account.positions == {}
    assert strategy.state.entry_stage == "IDLE"
    assert strategy.state.is_active is False

    assert len(validation_gate.risk_audit_records) == 4
    assert all(Decimal(str(record["validation_budget_overage_krw"])) == 0 for record in validation_gate.risk_audit_records)
    assert any(Decimal(str(record["operational_reference_overage_krw"])) > 0 for record in validation_gate.risk_audit_records)
    assert validation_gate._reserved == {}

    assert len(fee_rows) == 8
    fee_total = sum((row.fee_amount for row in fee_rows), Decimal(0))
    assert fee_total == 0  # VSSF fee source is zero in this validation fixture.

    group_realized = sum((Decimal(str(snapshot.realized_pnl)) for snapshot in snapshots), Decimal(0))
    group_unrealized = sum((Decimal(str(snapshot.unrealized_pnl)) for snapshot in snapshots), Decimal(0))
    group_total = group_realized + group_unrealized
    account_total = Decimal(str(vssf.account.realized_pnl)) + Decimal(str(vssf.account.unrealized_pnl))
    assert group_unrealized == 0
    assert float(group_total) == pytest.approx(float(EXPECTED_PNL[regime]), abs=1e-6)
    assert float(account_total) == pytest.approx(float(EXPECTED_PNL[regime]), abs=1e-6)
    assert abs(account_total - group_total) <= Decimal("0.000001")

    return {
        "events": report.events,
        "orders": vssf.metrics["order_commands"],
        "executions": vssf.metrics["executions_issued"],
        "groups": len(groups),
        "lots": len(lots),
        "close_events": len(close_events),
        "group_pnl": group_total,
        "account_pnl": account_total,
        "fees": fee_total,
        "risk_audit": tuple(
            (record["leg_id"], record["computed_gross_premium_krw"], record["validation_budget_overage_krw"])
            for record in validation_gate.risk_audit_records
        ),
        "flat": not bridge.position_lot_store.open_lots() and not bridge.pending_legs and not vssf.account.positions,
    }


@pytest.mark.parametrize("regime", ["high_vol", "normal"])
def test_s8_natural_strategyhub_runtime_fast_detailed_parity_and_flat(regime: str) -> None:
    fast = _run_scenario(regime, speed=float("inf"))
    detailed = _run_scenario(regime, speed=1.0)
    assert fast == detailed
    assert fast["flat"] is True
