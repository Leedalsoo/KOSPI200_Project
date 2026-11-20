from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil

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
from environments.high_speed.validation_only_s8_partial_fill import (
    ValidationOnlyS8PartialFillEngine,
)
from environments.high_speed.validation_only_s8_runtime_adapter import (
    S8ValidationOnlyRuntimeAdapter,
)
from environments.high_speed.virtual_runtime_replay import (
    _publish_contract_scoped_replay_quote,
)
from environments.virtual.clock import VirtualClock

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal"
MANIFEST = DATASET / "manifest.json"
RISK_PROFILE = ROOT / "config/validation_only/q25_s8_v3/normal/risk_profile.json"
PARTIAL_FILL_PROFILE = (
    ROOT / "config/validation_only/q25_s8_v3/normal/partial_fill_profile.json"
)
STRATEGY_ID = "track8_macro_regime_monthly_strangle"


def _run_mode(*, speed: float) -> dict[str, object]:
    replay_adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
    option_master = build_synthetic_option_master(
        DATASET,
        validation_only_adapter=replay_adapter,
    )
    validation_gate = S8ValidationOnlyRuntimeAdapter(
        dataset=DATASET,
        manifest_path=MANIFEST,
        risk_profile_path=RISK_PROFILE,
        partial_fill_profile_path=PARTIAL_FILL_PROFILE,
    )
    assert validation_gate.entry_quantity_per_leg == 3
    assert validation_gate.partial_fill_profile["execution_fill_schedule"] == [1, 2]

    mode = "FAST" if speed == float("inf") else "DETAILED"
    sources = SyntheticRuntimeSources()
    candidate_id = f"S8-CANDIDATE-MULTI-PARTIAL-{mode}"
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
        validation_candidate_id=candidate_id,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)

    run_id = bootstrap.run_context.run_id
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
    assert vssf.validation_candidate_id == candidate_id
    assert vssf.account.validation_candidate_id == candidate_id
    partial_engine = ValidationOnlyS8PartialFillEngine(validation_gate.partial_fill_profile)
    restore_partial_fill = partial_engine.install(vssf)

    initial_ticks = tuple(
        HighSpeedReplayRunner(DATASET, synthetic_adapter=replay_adapter).events()
    )
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

    try:
        report = HighSpeedReplayRunner(
            DATASET,
            synthetic_adapter=replay_adapter,
            clock=clock,
        ).run(speed=speed, on_event=on_tick)
    finally:
        restore_partial_fill()

    bridge = loop.multi_leg_bridge
    groups = bridge.position_groups.all()
    snapshots = tuple(bridge.position_groups.snapshot(group_id) for group_id in groups)
    lots = tuple(bridge.position_lot_store.history())
    close_events = tuple(bridge.position_lot_store.close_events())
    fee_rows = tuple(bridge.fee_ledger.query(run_id=run_id))
    strategy = loop.strategy_hub._orchestrator._registry.get(STRATEGY_ID, "2.0")
    assert report.events == 216
    assert report.exhausted is True
    assert vssf.metrics["market_ticks"] == 216
    assert vssf.metrics["order_commands"] == 6
    assert vssf.metrics["executions_issued"] == 9
    assert len(vssf.execution_engine.reports) == 9
    assert len(groups) == 2
    ordered_groups = sorted(groups.values(), key=lambda group: group.group_id)
    # The first pair completes. The later PUT is correctly rejected by the
    # validation premium cap after its CALL leg is filled; that CALL is closed.
    assert [len(group.legs) for group in ordered_groups] == [2, 1]
    assert all(
        leg.status.value == "FILLED"
        for group in groups.values()
        for leg in group.legs
    )

    # Each of the three BUY entry orders was first PARTIALLY_FILLED (1/3),
    # then FILLED (3/3) by the same VSSF order lifecycle.
    assert len(partial_engine.observations) == 3
    assert all(item.schedule == (1, 2) for item in partial_engine.observations)
    assert all(item.intermediate_status == "PARTIALLY_FILLED" for item in partial_engine.observations)
    assert all(item.intermediate_remaining_quantity == 2 for item in partial_engine.observations)
    assert all(item.final_status == "FILLED" for item in partial_engine.observations)
    assert all(item.final_filled_quantity == 3 for item in partial_engine.observations)
    assert all(item.final_remaining_quantity == 0 for item in partial_engine.observations)

    entry_reports = [
        item for item in vssf.execution_engine.reports
        if item.side.value == "BUY" and item.strategy_id == STRATEGY_ID
    ]
    assert len(entry_reports) == 6
    assert sorted(item.executed_qty for item in entry_reports) == [1, 1, 1, 2, 2, 2]
    assert len({item.exec_id for item in entry_reports}) == 6

    assert len(lots) == 6
    assert sorted(lot.opened_quantity for lot in lots) == [1, 1, 1, 2, 2, 2]
    assert len({lot.execution_id for lot in lots}) == 6
    assert len(close_events) == 6
    assert {event.source_lot_execution_id for event in close_events} == {
        lot.execution_id for lot in lots
    }
    assert all(event.quantity == lot.opened_quantity for event in close_events for lot in lots if event.source_lot_execution_id == lot.execution_id)
    assert bridge.position_lot_store.open_lots() == ()
    assert bridge.pending_legs == {}
    assert vssf.account.positions == {}
    assert strategy.state.entry_stage == "IDLE"
    assert strategy.state.is_active is False
    assert validation_gate._reserved == {}

    assert len(validation_gate.risk_audit_records) == 4
    assert [record["status"] for record in validation_gate.risk_audit_records] == [
        "ALLOW", "ALLOW", "ALLOW", "BLOCKED_VALIDATION_PREMIUM_LIMIT"
    ]
    assert [Decimal(str(record["validation_budget_overage_krw"])) for record in validation_gate.risk_audit_records] == [
        Decimal(0), Decimal(0), Decimal(0), Decimal(1165000)
    ]
    assert all(
        Decimal(str(record["operational_reference_overage_krw"])) > 0
        for record in validation_gate.risk_audit_records
    )

    assert len(fee_rows) == 9
    fee_total = sum((row.fee_amount for row in fee_rows), Decimal(0))
    assert fee_total == 0  # Zero-fee VSSF fixture; fee-inclusive PnL is not certified.

    group_realized = sum(
        (Decimal(str(snapshot.realized_pnl)) for snapshot in snapshots),
        Decimal(0),
    )
    group_unrealized = sum(
        (Decimal(str(snapshot.unrealized_pnl)) for snapshot in snapshots),
        Decimal(0),
    )
    group_total = group_realized + group_unrealized
    account_total = Decimal(str(vssf.account.realized_pnl)) + Decimal(
        str(vssf.account.unrealized_pnl)
    )
    assert group_unrealized == 0
    assert float(group_total) == pytest.approx(30000.0, abs=1e-6)
    assert float(account_total) == pytest.approx(30000.0, abs=1e-6)
    assert abs(account_total - group_total) <= Decimal("0.000001")

    return {
        "events": report.events,
        "orders": vssf.metrics["order_commands"],
        "execution_events": len(vssf.execution_engine.reports),
        "groups": len(groups),
        "lots": len(lots),
        "close_events": len(close_events),
        "fill_schedule": tuple(sorted(item.executed_qty for item in entry_reports)),
        "group_pnl": group_total,
        "account_pnl": account_total,
        "fees": fee_total,
        "risk_audit": tuple(
            (
                record["leg_id"],
                record["computed_gross_premium_krw"],
                record["validation_budget_overage_krw"],
                record["status"],
            )
            for record in validation_gate.risk_audit_records
        ),
        "flat": not bridge.position_lot_store.open_lots()
        and not bridge.pending_legs
        and not vssf.account.positions,
    }


def test_s8_current_natural_multicontract_partial_fill_fast_detailed_parity() -> None:
    fast = _run_mode(speed=float("inf"))
    detailed = _run_mode(speed=1.0)
    assert fast == detailed
    assert fast["flat"] is True

def test_s8_partial_fill_risk_profile_hash_is_line_ending_independent(tmp_path: Path) -> None:
    risk_bytes = RISK_PROFILE.read_bytes()
    normalized = risk_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf_path = tmp_path / "risk_profile_crlf.json"
    crlf_path.write_bytes(normalized.replace(b"\n", b"\r\n"))

    gate = S8ValidationOnlyRuntimeAdapter(
        dataset=DATASET,
        manifest_path=MANIFEST,
        risk_profile_path=crlf_path,
        partial_fill_profile_path=PARTIAL_FILL_PROFILE,
    )
    expected = json.loads(PARTIAL_FILL_PROFILE.read_text(encoding="utf-8"))[
        "risk_profile_sha256"
    ]
    assert gate.evidence.risk_profile_sha256 == expected


def test_s8_partial_fill_profile_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    tampered = json.loads(PARTIAL_FILL_PROFILE.read_text(encoding="utf-8"))
    tampered["entry_quantity_per_leg"] = 4
    profile_path = tmp_path / "partial_fill_profile.json"
    profile_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(
        PARTIAL_FILL_PROFILE.with_suffix(".json.sha256"),
        profile_path.with_suffix(".json.sha256"),
    )

    with pytest.raises(ValueError, match="S8_VALIDATION_PARTIAL_FILL_PROFILE_HASH_MISMATCH"):
        S8ValidationOnlyRuntimeAdapter(
            dataset=DATASET,
            manifest_path=MANIFEST,
            risk_profile_path=RISK_PROFILE,
            partial_fill_profile_path=profile_path,
        )

def test_s8_partial_fill_profile_nonzero_fee_is_rejected(tmp_path: Path) -> None:
    profile = json.loads(PARTIAL_FILL_PROFILE.read_text(encoding="utf-8"))
    profile["fee_per_fill_krw"] = 100
    profile_path = tmp_path / "partial_fill_profile.json"
    payload = (json.dumps(profile, indent=2) + "\n").encode("utf-8")
    profile_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    profile_path.with_suffix(".json.sha256").write_text(
        digest + "  " + profile_path.name + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="S8_VALIDATION_PARTIAL_FILL_FEE_UNSUPPORTED"):
        S8ValidationOnlyRuntimeAdapter(
            dataset=DATASET,
            manifest_path=MANIFEST,
            risk_profile_path=RISK_PROFILE,
            partial_fill_profile_path=profile_path,
        )
