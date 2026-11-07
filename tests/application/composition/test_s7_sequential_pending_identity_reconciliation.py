from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"


def _proposal(tag_id: str, option_type: str, strike: Decimal):
    return StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        side="BUY",
        track_id="track7_volatility_skew_weekly_insurance",
        tag_id=tag_id,
        option_type=option_type,
        strike=strike,
    )


def test_s7_pending_call_reconciliation_keeps_original_expiry_after_market_tick_rolls():
    replay_adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=replay_adapter)
    ticks = list(HighSpeedReplayRunner(DATASET, synthetic_adapter=replay_adapter).events())
    put_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261112" and str(tick.option_type).upper() == "PUT"
    )
    call_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261112"
        and tick.timestamp == put_tick.timestamp
        and str(tick.option_type).upper() == "CALL"
    )
    other_expiry_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261109"
        and str(tick.option_type).upper() == "PUT"
        and tick.timestamp == put_tick.timestamp
    )

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
        run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    strategy._activate_expiry("20261112")
    strategy.state = strategy.state.__class__(
        entry_pending=True,
        expiry="20261112",
        put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        entry_stage="PUT_READY",
    )
    bridge.execution_result_callback = lambda plan, result: strategy.on_execution_result(
        plan.purpose, result
    )

    def freshness(plan, leg, identity, command):
        observed = datetime.fromisoformat(call_tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S7_PENDING_IDENTITY_RECONCILIATION_FIXTURE",
            policy_version="S7-PENDING-IDENTITY-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=sha256(
                f"{observed.isoformat()}|{command.instrument_id}".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    _publish_contract_scoped_replay_quote(
        put_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    _publish_contract_scoped_replay_quote(
        call_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    sources.set_tick(call_tick)
    bootstrap.bundle.market.publish_replay_tick(put_tick)
    bootstrap.bundle.market.publish_replay_tick(call_tick)

    put_plan = strategy.build_execution_plan(
        "Q25-S7-PENDING-IDENTITY-GROUP",
        proposal=_proposal("WEEKLY_INSURANCE_ENTRY_PUT", "PUT", Decimal("487.5")),
    )
    put_result = bridge.execute(put_plan)
    assert put_result.reports[0].status == "FILLED"
    assert strategy.state.entry_stage == "CALL_READY"

    call_plan = strategy.build_execution_plan(
        "IGNORED-CALL-GROUP-ID",
        proposal=_proposal("WEEKLY_INSURANCE_ENTRY_CALL", "CALL", Decimal("512.5")),
    )
    pending_limit = Decimal(str(call_tick.bid_price)) - Decimal("1.00")
    call_plan = replace(
        call_plan,
        legs=(replace(call_plan.legs[0], requested_price=pending_limit),),
    )
    call_result = bridge.execute(call_plan)
    assert call_result.reports[0].status == "NEW"
    assert call_result.pending_legs == 1
    assert strategy.state.entry_stage == "CALL_PENDING"

    client_order_id = call_result.reports[0].client_order_id
    stored_group_plan, stored_leg, stored_command = bridge.pending_legs[client_order_id]
    assert stored_command.client_order_id == client_order_id
    assert stored_leg.instrument_identity.expiry == "20261112"
    assert {
        leg.instrument_identity.expiry for leg in stored_group_plan.legs
    } == {"20261112"}

    # A later event for the other weekly expiry must not rebind the pending CALL.
    bootstrap.bundle.market.publish_replay_tick(other_expiry_tick)
    assert bootstrap.bundle.market.last_tick.expiry == "20261109"

    improved_call_tick = replace(
        call_tick,
        timestamp=(datetime.fromisoformat(call_tick.timestamp).replace(microsecond=0)
                   + timedelta(seconds=1)).isoformat(),
        bid_price=float(pending_limit - Decimal("0.01")),
        ask_price=float(pending_limit),
        last_price=float(pending_limit),
    )
    _publish_contract_scoped_replay_quote(
        improved_call_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    vssf.process_market_data(improved_call_tick)

    reconciled = bridge.process_pending_quotes()
    assert len(reconciled) == 1
    final = reconciled[0]
    assert final.group_complete is True
    assert final.pending_legs == 0
    assert final.reports[-1].client_order_id == client_order_id
    assert final.reports[-1].status == "FILLED"
    assert final.reports[-1].execution_id
    assert all(report.status != "REJECTED" for report in bridge.group_reports(call_plan.group_id))
    assert len(bridge.pending_legs) == 0
    assert strategy.state.entry_stage == "COMPLETE"
    assert strategy.state.insurance_active is True
    assert strategy.state.put_open is True
    assert strategy.state.call_open is True

    open_lots = bridge.position_lot_store.open_lots()
    assert len(open_lots) == 2
    assert {lot.instrument_identity.expiry for lot in open_lots} == {"20261112"}
    snapshot = bridge.position_groups.snapshot(call_plan.group_id)
    assert snapshot is not None
    assert {leg.instrument_id for leg in snapshot.legs} == {
        "SYNTHETIC_CONTRACT:strategy7_weekly:20261112:PUT:487.5",
        "SYNTHETIC_CONTRACT:strategy7_weekly:20261112:CALL:512.5",
    }

