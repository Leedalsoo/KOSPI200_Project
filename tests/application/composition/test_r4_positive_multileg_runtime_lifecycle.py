from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.virtual.clock import VirtualClock

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.validation_only_trading_calendar import ValidationOnlyTradingCalendar
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote


DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")


def _fixture_identity(tick, option_master) -> OptionInstrumentIdentity:
    master_identity = option_master.get_contract_identity(tick.instrument_id)
    assert master_identity is not None
    assert master_identity.stnd_iscd is None
    return OptionInstrumentIdentity(
        master_identity.shrn_iscd, master_identity.shrn_iscd,
        master_identity.expiry, master_identity.option_type,
        Decimal(str(master_identity.strike)),
        Decimal(str(master_identity.contract_multiplier)),
        "DERIVED_SCENARIO_TEST_FIXTURE",
    )


def test_positive_multi_leg_virtual_execution_group_lifecycle():
    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    events = HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events()
    call_tick = next(events)
    put_tick = next(
        tick for tick in events
        if str(tick.option_type).upper() == "PUT"
        and str(tick.expiry) == str(call_tick.expiry)
        and float(tick.strike_price) == float(call_tick.strike_price)
    )
    call_identity = _fixture_identity(call_tick, option_master)
    put_identity = _fixture_identity(put_tick, option_master)
    assert call_identity.instrument_id != put_identity.instrument_id
    assert call_identity.expiry == put_identity.expiry
    assert call_identity.strike == put_identity.strike

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    original_loop = bootstrap.automated_loop
    if original_loop is not None:
        bootstrap.bundle.market.unsubscribe(original_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="R4-POSITIVE-MULTILEG-FIXTURE",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge

    def freshness(plan, leg, identity, command):
        observed_at = datetime.fromisoformat(call_tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="R4_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R4-TEST-FIXTURE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id, symbol=command.broker_symbol,
            source_instant=observed_at, received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{command.instrument_id}|R4-TEST".encode()
            ).hexdigest(),
        )
    bridge.freshness_verdict_provider = freshness

    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    for tick in (call_tick, put_tick):
        _publish_contract_scoped_replay_quote(
            tick, option_master=bootstrap.bundle.option_master,
            market=bootstrap.bundle.market, order_book=vssf_runtime.order_book,
        )
    sources.set_tick(call_tick)
    bootstrap.bundle.market.publish_replay_tick(call_tick)

    plan = MultiLegExecutionPlan(
        "R4-POSITIVE-MULTILEG-GROUP", "R4_TEST_MULTI_LEG",
        (
            ExecutionLeg("call-leg", "BUY", 1, option_type="CALL",
                         strike=call_identity.strike, instrument_identity=call_identity),
            ExecutionLeg("put-leg", "BUY", 1, option_type="PUT",
                         strike=put_identity.strike, instrument_identity=put_identity),
        ),
        purpose="R4_TEST_FIXTURE",
    )
    result = bridge.execute(plan)
    assert result.planned_legs == 2
    assert result.approved_legs == 2
    assert result.routed_legs == 2
    assert result.filled_legs == 2
    assert result.group_complete is True
    assert len(result.reports) == 2
    assert all(report.status == "FILLED" for report in result.reports)
    assert all(report.execution_id for report in result.reports)
    assert {lot.instrument_id for lot in bridge.position_lot_store.open_lots()} == {
        call_identity.instrument_id, put_identity.instrument_id,
    }
    assert len(bridge.position_groups.snapshot(plan.group_id).legs) == 2


def test_pending_virtual_order_fill_is_reconciled_to_callback_and_position():
    adapter = SyntheticReplayAdapter(DATASET)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    tick = next(
        item for item in HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events()
        if str(item.option_type).upper() == "CALL"
        and Decimal(str(item.bid_price)) > 0
        and Decimal(str(item.ask_price)) > Decimal(str(item.bid_price))
    )
    identity = _fixture_identity(tick, master)
    limit_price = Decimal(str(tick.bid_price)) - Decimal("1.00")
    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="Q25-PENDING-ORDER-RECONCILIATION",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    callbacks = []

    def freshness(plan, leg, contract_identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="Q25_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-PENDING-RECONCILE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE", tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY", instrument_id=command.instrument_id,
            symbol=command.broker_symbol, source_instant=observed, received_at=observed,
            evidence_sha256=sha256(f"{observed.isoformat()}|{command.instrument_id}".encode()).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    strategy_hub = loop.strategy_hub
    original_callback = strategy_hub.on_execution_result

    def capture_callback(strategy_id, purpose, result):
        callbacks.append(result)
        original_callback(strategy_id, purpose, result)

    strategy_hub.on_execution_result = capture_callback
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    _publish_contract_scoped_replay_quote(tick, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book)
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    plan = MultiLegExecutionPlan(
        group_id="Q25-PENDING-GROUP", strategy_id="TRACK1_TAIL_DEFENSE",
        purpose="Q25_PENDING_FILL_RECONCILIATION",
        legs=(ExecutionLeg("call-leg", "BUY", 1, option_type="CALL", strike=identity.strike,
                           requested_price=limit_price, instrument_identity=identity),),
    )
    initial = bridge.execute(plan)
    assert initial.routed_legs == 1 and initial.filled_legs == 0
    assert initial.pending_legs == 1 and initial.reports[0].status == "NEW"
    assert len(bridge.pending_legs) == 1
    assert bridge.position_lot_store.open_lots() == ()

    improved = __import__("dataclasses").replace(
        tick, timestamp=(datetime.fromisoformat(tick.timestamp) + __import__("datetime").timedelta(seconds=1)).isoformat(),
        bid_price=float(limit_price - Decimal("0.01")), ask_price=float(limit_price), last_price=float(limit_price),
    )
    _publish_contract_scoped_replay_quote(improved, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book)
    vssf.process_market_data(improved)
    results = bridge.process_pending_quotes()
    assert len(results) == 1
    final = results[0]
    assert final.group_complete and final.filled_legs == 1 and final.pending_legs == 0
    assert final.reports[0].status == "FILLED" and final.reports[0].execution_id
    assert len(bridge.pending_legs) == 0
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert bridge.position_lot_store.open_lots()[0].execution_id == final.reports[0].execution_id
    assert len(bridge.position_groups.snapshot(plan.group_id).legs) == 1
    assert vssf.metrics["order_commands"] == 1
    assert [item.reports[0].status for item in callbacks] == ["NEW", "FILLED"]


def test_multiple_partial_fills_reconcile_to_bridge_position_lots_once():
    adapter = SyntheticReplayAdapter(DATASET)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    tick = next(
        item for item in HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events()
        if str(item.option_type).upper() == "CALL"
        and Decimal(str(item.bid_price)) > 1
        and Decimal(str(item.ask_price)) > Decimal(str(item.bid_price))
    )
    identity = _fixture_identity(tick, master)
    limit_price = Decimal(str(tick.bid_price)) - Decimal("1.00")
    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="Q25-S8-MULTI-PARTIAL-BRIDGE",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge

    def freshness(plan, leg, contract_identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="Q25_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-S8-MULTI-PARTIAL-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE", tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY", instrument_id=command.instrument_id,
            symbol=command.broker_symbol, source_instant=observed, received_at=observed,
            evidence_sha256=sha256(f"{observed.isoformat()}|{command.instrument_id}|MULTI".encode()).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    plan = MultiLegExecutionPlan(
        group_id="Q25-S8-MULTI-PARTIAL-GROUP",
        strategy_id="TRACK1_TAIL_DEFENSE",
        purpose="Q25_S8_MULTI_PARTIAL_RECONCILIATION",
        legs=(ExecutionLeg(
            "call-leg", "BUY", 4, option_type="CALL", strike=identity.strike,
            requested_price=limit_price, instrument_identity=identity,
        ),),
    )
    initial = bridge.execute(plan)
    assert initial.routed_legs == 1
    assert initial.pending_legs == 1
    assert initial.reports[0].status == "NEW"
    client_order_id = initial.reports[0].client_order_id
    broker_command = bridge.pending_legs[client_order_id][2]
    fill_command = SimpleNamespace(**{
        **broker_command.__dict__,
        "option_type": identity.option_type,
        "strike": float(identity.strike),
        "expiry": identity.expiry,
        "contract_multiplier": identity.contract_multiplier,
        "identity_source": identity.identity_source,
    })
    fill_base_time = vssf._now()
    fill_times = (
        fill_base_time + timedelta(seconds=1),
        fill_base_time + timedelta(seconds=2),
    )
    for quantity, price, timestamp in (
        (1, float(limit_price), fill_times[0]),
        (2, float(limit_price + Decimal("0.01")), fill_times[1]),
    ):
        execution = vssf.execution_engine.execute_order(
            fill_command, price, quantity, timestamp=timestamp
        )
        vssf.account.apply_execution(execution)

    reconciled = bridge.process_pending_quotes()
    assert len(reconciled) == 1
    partial = reconciled[0]
    assert partial.reports[0].status == "PARTIALLY_FILLED"
    assert partial.reports[0].filled_quantity == 3
    assert partial.reports[0].remaining_quantity == 1
    assert [fill.execution_id for fill in partial.reports[0].execution_fills] == [
        "EXEC-000001", "EXEC-000002",
    ]
    assert [lot.execution_id for lot in bridge.position_lot_store.open_lots()] == [
        "EXEC-000001", "EXEC-000002",
    ]
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.position_groups.snapshot(plan.group_id).legs[0].execution_ids == (
        "EXEC-000001", "EXEC-000002",
    )
    assert bridge.process_pending_quotes() == ()

    # A later market match must execute only the one remaining contract, not
    # resubmit the original four-contract quantity.
    vssf.order_book.update_bid_ask(
        float(limit_price - Decimal("0.01")), float(limit_price), identity.instrument_id
    )
    vssf.clock.sleep_policy(3)
    vssf.process_pending_orders()
    fully_filled = vssf.query_order(client_order_id)
    assert fully_filled.status == "FILLED"
    assert fully_filled.executed_qty == 4
    assert fully_filled.remaining_qty == 0
    assert [fill.exec_id for fill in fully_filled.execution_fills] == [
        "EXEC-000001", "EXEC-000002", "EXEC-000003",
    ]

    terminal = bridge.process_pending_quotes()
    assert len(terminal) == 1
    assert terminal[0].reports[0].status == "FILLED"
    assert terminal[0].reports[0].filled_quantity == 4
    assert len(bridge.position_lot_store.history()) == 3
    assert bridge.leg_positions[identity.instrument_id].qty == 4
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 3
    assert bridge.position_groups.snapshot(plan.group_id).legs[0].execution_ids == (
        "EXEC-000001", "EXEC-000002", "EXEC-000003",
    )
    assert client_order_id not in bridge.pending_legs


def test_track8_ten_minute_timeout_cancel_reaches_bridge_and_strategy_hub():
    adapter = SyntheticReplayAdapter(DATASET)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    tick = next(
        item for item in HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events()
        if str(item.option_type).upper() == "CALL"
        and Decimal(str(item.bid_price)) > 0
        and Decimal(str(item.ask_price)) > Decimal(str(item.bid_price))
    )
    identity = _fixture_identity(tick, master)
    limit_price = Decimal(str(tick.bid_price)) - Decimal("1.00")
    assert limit_price > 0

    first_trading_day = datetime.fromisoformat(tick.timestamp).date()
    trading_days = []
    cursor = first_trading_day
    while len(trading_days) < 5:
        if cursor.weekday() < 5:
            trading_days.append(cursor)
        cursor += timedelta(days=1)
    retry_calendar = ValidationOnlyTradingCalendar(
        scenario_id="Q25-S8-TIMEOUT-CALLBACK",
        calendar_id="Q25-S8-RETRY-CALENDAR",
        trading_days=tuple(trading_days),
    )
    sources = SyntheticRuntimeSources(calendar=retry_calendar)
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("track8_macro_regime_monthly_strangle", "2.0"),),
        run_id="Q25-S8-TIMEOUT-CANCEL-CALLBACK",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    strategy = loop.strategy_hub._orchestrator._registry.get(
        "track8_macro_regime_monthly_strangle", "2.0"
    )
    strategy.runtime_config_verified = True
    strategy.risk_limits_available = True
    strategy.state = replace(
        strategy.state,
        entry_pending=True,
        entry_stage="CALL_READY",
        call_strike=identity.strike,
        qty_call=1,
        call_contract_multiplier=identity.contract_multiplier,
        expiry=str(identity.expiry).replace("-", ""),
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        side="BUY",
        track_id=strategy.strategy_id,
        tag_id="MONTHLY_STRANGLE_ENTRY_CALL",
        option_type="CALL",
        strike=identity.strike,
    )
    plan = strategy.build_execution_plan(
        "Q25-S8-TIMEOUT-GROUP", proposal=proposal
    )
    plan = replace(
        plan,
        legs=(replace(
            plan.legs[0],
            instrument_identity=identity,
            requested_price=limit_price,
        ),),
    )

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="Q25_SYNTHETIC_TIMEOUT_FIXTURE_ONLY",
            policy_version="Q25-S8-TIMEOUT-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=sha256(
                f"{observed.isoformat()}|{command.instrument_id}|S8-TIMEOUT".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    clock = VirtualClock(datetime.fromisoformat(tick.timestamp))
    vssf.attach_clock(clock)
    vssf.attach_timeout_source(
        Track7OrderTimeoutRuntimeSource(
            clock,
            Track7OrderTimeoutPolicy(
                Decimal("600"), "Q25-S8-VALIDATION-ONLY-10M"
            ),
        )
    )
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    initial = bridge.execute(plan)
    assert initial.pending_legs == 1
    assert initial.reports[0].status == "NEW"
    assert len(bridge.pending_legs) == 1
    assert strategy.state.entry_stage == "CALL_PENDING"

    clock.sleep_policy(599)
    assert vssf.process_timeouts() == ()
    assert vssf.query_order(initial.reports[0].client_order_id).status == "NEW"

    clock.sleep_policy(1)
    timed_out = vssf.process_timeouts()
    assert len(timed_out) == 1
    assert timed_out[0].status == "CANCELLED"
    assert vssf.query_order(initial.reports[0].client_order_id).status == "CANCELLED"

    reconciled = bridge.process_pending_quotes()
    assert len(reconciled) == 1
    final = reconciled[0]
    assert final.reports[0].status == "CANCELLED"
    assert final.pending_legs == 0
    assert len(bridge.pending_legs) == 0
    assert final.reports[0].lifecycle_reason == "TIMEOUT_10M"
    assert final.reports[0].submitted_at is not None
    assert strategy.state.entry_stage == "RETRY_WAIT"
    assert strategy.state.retry_leg == "call"
    assert strategy.state.retry_due_at is not None
    assert strategy.state.entry_pending is True
    assert bridge.position_lot_store.open_lots() == ()

    retry_context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(as_of=strategy.state.retry_due_at),
    )
    retry_signal = strategy.evaluate(retry_context)[0]
    retry_plan = strategy.build_execution_plan(
        "Q25-S8-RETRY-SIGNAL", proposal=retry_signal.execution_proposal
    )
    retry_plan = replace(
        retry_plan,
        legs=(replace(
            retry_plan.legs[0],
            instrument_identity=identity,
            requested_price=limit_price,
        ),),
    )
    retry_client_id = bridge._client_order_id(retry_plan, retry_plan.legs[0], identity)
    assert retry_plan.attempt_id == "CALL-RETRY-1"
    assert retry_client_id != initial.reports[0].client_order_id
    assert strategy.state.call_retry_count == 1
    assert vssf.metrics["order_commands"] == 1

    # A broker-confirmed REJECTED terminal report follows the same callback path.
    strategy.state = replace(
        strategy.state,
        entry_pending=True,
        entry_stage="CALL_READY",
        entry_group_id=None,
        entry_block_reason=None,
    )
    rejected_plan = strategy.build_execution_plan(
        "Q25-S8-REJECT-GROUP", proposal=proposal
    )
    rejected_plan = replace(
        rejected_plan,
        legs=(replace(
            rejected_plan.legs[0],
            instrument_identity=identity,
            requested_price=limit_price,
        ),),
    )
    submitted_rejected = bridge.execute(rejected_plan)
    assert submitted_rejected.pending_legs == 1
    rejected_client_id = submitted_rejected.reports[0].client_order_id
    bridge.ack.broker.query = lambda client_order_id: ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id=None,
        execution_id=None,
        status="REJECTED",
        filled_quantity=0,
        remaining_quantity=1,
        execution_price=None,
        execution_timestamp=None,
        fee=None,
        group_id=rejected_plan.group_id,
        leg_id="call",
        rejected_reason="SYNTHETIC_BROKER_REJECTED",
    )
    rejected_results = bridge.process_pending_quotes()
    assert len(rejected_results) == 1
    assert rejected_results[0].reports[0].status == "REJECTED"
    assert rejected_results[0].pending_legs == 0
    assert rejected_client_id not in bridge.pending_legs
    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "SYNTHETIC_BROKER_REJECTED"
    assert strategy.state.entry_pending is True
    assert bridge.position_lot_store.open_lots() == ()
    assert vssf.metrics["order_commands"] == 2

def test_t23_four_leg_virtual_group_reconciles_and_persists_u19_after_restart(tmp_path):
    import json
    from collections import defaultdict

    from application.composition.track2_u19_recovery import (
        ValidationOnlyTrack2U19RecoveryCoordinator,
    )
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot,
        U19ExecutionEvent,
        U19ExecutionLedgerSnapshot,
        U19Position,
    )
    from environments.virtual.position.track2_u19_recovery_store import (
        SqliteTrack2U19RecoveryStore,
    )

    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    events = tuple(HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events())
    grouped = defaultdict(dict)
    for tick in events:
        if str(tick.expiry) != "20261008":
            continue
        grouped[str(tick.timestamp)].setdefault(
            str(tick.option_type).upper(), {}
        )[float(tick.strike_price)] = tick

    selected_ticks = None
    for timestamp, by_type in grouped.items():
        calls = by_type.get("CALL", {})
        puts = by_type.get("PUT", {})
        common_strikes = sorted(set(calls) & set(puts))
        valid = [
            strike
            for strike in common_strikes
            if Decimal(str(calls[strike].bid_price)) > 0
            and Decimal(str(calls[strike].ask_price)) > Decimal(str(calls[strike].bid_price))
            and Decimal(str(puts[strike].bid_price)) > 0
            and Decimal(str(puts[strike].ask_price)) > Decimal(str(puts[strike].bid_price))
        ]
        if len(valid) >= 2:
            selected_ticks = (
                timestamp,
                calls[valid[0]],
                calls[valid[1]],
                puts[valid[0]],
                puts[valid[1]],
            )
            break
    assert selected_ticks is not None

    timestamp, call_low, call_high, put_low, put_high = selected_ticks
    selected = (call_low, call_high, put_low, put_high)
    identities = tuple(_fixture_identity(tick, option_master) for tick in selected)
    assert len({identity.instrument_id for identity in identities}) == 4

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="T23-FOUR-LEG-U19-RESTART",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="T23_SYNTHETIC_FIXTURE_ONLY",
            policy_version="T23-FOUR-LEG-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=sha256(
                f"{observed.isoformat()}|{command.instrument_id}|T23".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    for tick in selected:
        _publish_contract_scoped_replay_quote(
            tick,
            option_master=option_master,
            market=bootstrap.bundle.market,
            order_book=vssf.order_book,
        )
    sources.set_tick(call_low)
    bootstrap.bundle.market.publish_replay_tick(call_low)

    group_id = "T23-SYNTHETIC-FOUR-LEG-GROUP"
    strategy_id = "T23_SYNTHETIC_FOUR_LEG"
    legs = tuple(
        ExecutionLeg(
            leg_id=f"{str(tick.option_type).lower()}-{tick.strike_price}",
            side="BUY",
            quantity=1,
            option_type=str(tick.option_type).upper(),
            strike=identity.strike,
            instrument_identity=identity,
        )
        for tick, identity in zip(selected, identities, strict=True)
    )
    plan = MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose="T23_FOUR_LEG_VIRTUAL_RESTART",
        legs=legs,
    )

    result = bridge.execute(plan)
    assert result.planned_legs == 4
    assert result.routed_legs == 4
    assert result.filled_legs == 4
    assert result.pending_legs == 0
    assert result.group_complete is True
    assert len(result.reports) == 4
    assert all(report.status == "FILLED" for report in result.reports)
    assert all(report.group_id == group_id for report in result.reports)
    assert {report.leg_id for report in result.reports} == {
        leg.leg_id for leg in legs
    }

    lots = bridge.position_lot_store.open_lots()
    fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    assert len(lots) == 4
    assert len(fees) == 4
    assert {lot.group_id for lot in lots} == {group_id}
    assert {lot.leg_id for lot in lots} == {leg.leg_id for leg in legs}
    assert len({lot.execution_id for lot in lots}) == 4

    broker_positions = tuple(
        U19Position(
            instrument_id=lot.instrument_id,
            signed_quantity=(
                Decimal(lot.remaining_quantity)
                if lot.side == "BUY"
                else -Decimal(lot.remaining_quantity)
            ),
        )
        for lot in lots
    )
    ledger_positions = broker_positions
    execution_events = tuple(
        U19ExecutionEvent(
            report.execution_id,
            sha256(
                json.dumps(
                    {
                        "execution_id": report.execution_id,
                        "client_order_id": report.client_order_id,
                        "group_id": report.group_id,
                        "leg_id": report.leg_id,
                        "filled_quantity": report.filled_quantity,
                        "execution_price": str(report.execution_price),
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
        for report in result.reports
    )
    as_of = max(
        report.execution_timestamp for report in result.reports
    ) + timedelta(seconds=1)
    broker_payload = {
        "group_id": group_id,
        "positions": [
            (item.instrument_id, str(item.signed_quantity))
            for item in broker_positions
        ],
    }
    ledger_payload = {
        "group_id": group_id,
        "positions": [
            (item.instrument_id, str(item.signed_quantity))
            for item in ledger_positions
        ],
        "execution_events": [
            (event.execution_id, event.fingerprint)
            for event in execution_events
        ],
    }
    digest = lambda value: sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    checkpoint_path = tmp_path / "t23-four-leg-u19.sqlite3"
    first_store = SqliteTrack2U19RecoveryStore(checkpoint_path)
    first_decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        first_store
    ).recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="T23-BROKER-INITIAL",
            as_of=as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id,
            snapshot_id="T23-LEDGER-INITIAL",
            as_of=as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions,
            complete=True,
            payload_sha256=digest(ledger_payload),
            execution_events=execution_events,
        ),
    )
    assert first_decision.restore_allowed is True, first_decision.__dict__
    assert first_decision.new_entry_enabled is False
    assert first_decision.order_submission_enabled is False

    reopened_store = SqliteTrack2U19RecoveryStore(checkpoint_path)
    persisted = reopened_store.load_latest(group_id)
    assert persisted is not None
    assert persisted["status"] == first_decision.status.value
    assert len(persisted["execution_events"]) == 4

    before_lots = bridge.position_lot_store.history()
    before_fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    reopened_decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="T23-BROKER-REOPEN",
            as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id,
            snapshot_id="T23-LEDGER-REOPEN",
            as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions,
            complete=True,
            payload_sha256=digest(ledger_payload),
            execution_events=execution_events + execution_events,
        ),
    )
    assert reopened_decision.restore_allowed is True
    assert len(reopened_decision.execution_events) == 4
    assert bridge.position_lot_store.history() == before_lots
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == before_fees
    assert len(bridge.position_lot_store.open_lots()) == 4
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 4

def test_t25_four_leg_partial_fill_cancel_race_exactly_once(tmp_path):
    import json
    from collections import defaultdict

    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    events = tuple(HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events())
    grouped = defaultdict(dict)
    for tick in events:
        if str(tick.expiry) != "20261008":
            continue
        grouped[str(tick.timestamp)].setdefault(
            str(tick.option_type).upper(), {}
        )[float(tick.strike_price)] = tick

    selected_ticks = None
    for timestamp, by_type in grouped.items():
        calls = by_type.get("CALL", {})
        puts = by_type.get("PUT", {})
        valid_calls = [
            strike for strike, tick in calls.items()
            if Decimal(str(tick.bid_price)) > 1
            and Decimal(str(tick.ask_price)) > Decimal(str(tick.bid_price))
        ]
        valid_puts = [
            strike for strike, tick in puts.items()
            if Decimal(str(tick.bid_price)) > 1
            and Decimal(str(tick.ask_price)) > Decimal(str(tick.bid_price))
        ]
        if len(valid_calls) >= 2 and len(valid_puts) >= 2:
            selected_ticks = (
                timestamp,
                calls[valid_calls[0]],
                calls[valid_calls[1]],
                puts[valid_puts[0]],
                puts[valid_puts[1]],
            )
            break
    assert selected_ticks is not None

    timestamp, call_low, call_high, put_low, put_high = selected_ticks
    selected = (call_low, call_high, put_low, put_high)
    identities = tuple(_fixture_identity(tick, option_master) for tick in selected)
    assert len({identity.instrument_id for identity in identities}) == 4

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="T25-FOUR-LEG-PARTIAL-CANCEL-RACE",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="T25_SYNTHETIC_FIXTURE_ONLY",
            policy_version="T25-FOUR-LEG-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=sha256(
                f"{observed.isoformat()}|{command.instrument_id}|T25".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    for tick in selected:
        _publish_contract_scoped_replay_quote(
            tick,
            option_master=option_master,
            market=bootstrap.bundle.market,
            order_book=vssf.order_book,
        )
    sources.set_tick(call_low)
    bootstrap.bundle.market.publish_replay_tick(call_low)

    group_id = "T25-SYNTHETIC-FOUR-LEG-GROUP"
    legs = tuple(
        ExecutionLeg(
            leg_id=f"{str(tick.option_type).lower()}-{tick.strike_price}",
            side="BUY",
            quantity=2,
            option_type=str(tick.option_type).upper(),
            strike=identity.strike,
            requested_price=Decimal(str(tick.bid_price)) - Decimal("1.00"),
            instrument_identity=identity,
        )
        for tick, identity in zip(selected, identities, strict=True)
    )
    plan = MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id="T25_SYNTHETIC_FOUR_LEG",
        purpose="T25_PARTIAL_MULTI_LEG_CANCEL_RACE",
        legs=legs,
    )
    initial = bridge.execute(plan)
    assert initial.routed_legs == 4
    assert initial.pending_legs == 4
    assert all(report.status == "NEW" for report in initial.reports)

    commands = {
        client_order_id: pending[2]
        for client_order_id, pending in bridge.pending_legs.items()
    }
    leg_by_id = {leg.leg_id: leg for leg in legs}
    identity_by_leg = {
        leg.leg_id: identity
        for leg, identity in zip(legs, identities, strict=True)
    }
    client_by_leg = {
        pending[1].leg_id: client_order_id
        for client_order_id, pending in bridge.pending_legs.items()
    }

    fill_base = vssf._now()
    for index, leg in enumerate(legs):
        command = commands[client_by_leg[leg.leg_id]]
        identity = identity_by_leg[leg.leg_id]
        fill_command = SimpleNamespace(**{
            **command.__dict__,
            "option_type": identity.option_type,
            "strike": float(identity.strike),
            "expiry": identity.expiry,
            "contract_multiplier": identity.contract_multiplier,
            "identity_source": identity.identity_source,
            "symbol": identity.instrument_id,
        })
        execution = vssf.execution_engine.execute_order(
            fill_command,
            float(leg.requested_price),
            1,
            timestamp=fill_base + timedelta(seconds=index + 1),
        )
        vssf.account.apply_execution(execution)

    partial_results = bridge.process_pending_quotes()
    assert len(partial_results) == 4
    assert all(
        item.reports[0].status == "PARTIALLY_FILLED"
        for item in partial_results
    )
    assert all(item.reports[0].filled_quantity == 1 for item in partial_results)
    assert len(bridge.position_lot_store.history()) == 4
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 4

    late_leg = legs[0]
    late_client_id = client_by_leg[late_leg.leg_id]
    late_identity = identity_by_leg[late_leg.leg_id]
    original_cancel = vssf.cancel_order
    late_execution_ids = []

    def cancel_with_late_fill(client_order_id, *, lifecycle_reason="MANUAL"):
        if client_order_id != late_client_id:
            return original_cancel(
                client_order_id,
                lifecycle_reason=lifecycle_reason,
            )
        pending_command = vssf.order_book.get_pending_order(client_order_id)
        assert pending_command is not None
        vssf.order_book.update_bid_ask(
            float(late_leg.requested_price) - 0.01,
            float(late_leg.requested_price),
            late_identity.instrument_id,
        )
        late_execution = vssf._execute(
            pending_command,
            float(late_leg.requested_price),
            vssf._now(),
            quantity=1,
        )
        late_execution_ids.append(late_execution.exec_id)
        return original_cancel(
            client_order_id,
            lifecycle_reason=lifecycle_reason,
        )

    vssf.cancel_order = cancel_with_late_fill
    cancelled = bridge.cancel_pending_order(
        late_client_id,
        reason="T25_SYNTHETIC_CANCEL_RACE",
    )
    assert len(late_execution_ids) == 1
    assert cancelled.reports[0].status == "FILLED"
    assert cancelled.reports[0].filled_quantity == 2
    assert cancelled.reports[0].remaining_quantity == 0
    assert late_client_id not in bridge.pending_legs

    for leg in legs[1:]:
        client_order_id = client_by_leg[leg.leg_id]
        command = commands[client_order_id]
        identity = identity_by_leg[leg.leg_id]
        fill_command = SimpleNamespace(**{
            **command.__dict__,
            "option_type": identity.option_type,
            "strike": float(identity.strike),
            "expiry": identity.expiry,
            "contract_multiplier": identity.contract_multiplier,
            "identity_source": identity.identity_source,
            "symbol": identity.instrument_id,
        })
        vssf._execute(
            vssf.order_book.get_pending_order(client_order_id),
            float(leg.requested_price),
            vssf._now(),
            quantity=1,
        )

    vssf.process_pending_orders()
    terminal_results = bridge.process_pending_quotes()
    assert len(terminal_results) == 3
    assert all(item.reports[0].status == "FILLED" for item in terminal_results)
    assert bridge.pending_legs == {}

    final_reports = {
        cancelled.reports[0].client_order_id: cancelled.reports[0],
        **{
            item.reports[0].client_order_id: item.reports[0]
            for item in terminal_results
        },
    }
    assert len(final_reports) == 4
    assert all(report.group_id == group_id for report in final_reports.values())
    assert all(report.filled_quantity == 2 for report in final_reports.values())
    assert all(len(report.execution_fills) == 2 for report in final_reports.values())
    assert late_execution_ids[0] in {
        fill.execution_id
        for fill in final_reports[late_client_id].execution_fills
    }

    history_before_replay = bridge.position_lot_store.history()
    fees_before_replay = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    positions_before_replay = {
        key: dict(value) for key, value in vssf.account.positions.items()
    }
    assert len(history_before_replay) == 8
    assert len(fees_before_replay) == 8
    assert len({lot.execution_id for lot in history_before_replay}) == 8

    for leg in legs:
        client_order_id = client_by_leg[leg.leg_id]
        bridge._apply_reconciled_execution(
            plan=plan,
            leg=leg_by_id[leg.leg_id],
            identity=identity_by_leg[leg.leg_id],
            broker_command=commands[client_order_id],
            report=final_reports[client_order_id],
        )

    assert bridge.position_lot_store.history() == history_before_replay
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == fees_before_replay
    assert vssf.account.positions == positions_before_replay
    assert len(bridge.position_lot_store.open_lots()) == 8
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 8

    from application.composition.track2_u19_recovery import (
        ValidationOnlyTrack2U19RecoveryCoordinator,
    )
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot,
        U19ExecutionEvent,
        U19ExecutionLedgerSnapshot,
        U19Position,
    )
    from environments.virtual.execution.vssf_command_context_provider import (
        CanonicalVSSFCommandContextProvider,
    )
    from environments.virtual.execution.vssf_execution_adapter import (
        VSSFExecutionAdapter,
    )
    from environments.virtual.position.track2_u19_recovery_store import (
        SqliteTrack2U19RecoveryStore,
    )

    # Recreated adapter resolves all four persisted orders without its old cache.
    restarted_adapter = VSSFExecutionAdapter(
        CanonicalVSSFCommandContextProvider(),
        vssf,
    )
    for client_order_id, command in commands.items():
        queried = restarted_adapter.query(client_order_id)
        assert queried is not None
        assert queried.group_id == group_id
        assert queried.leg_id == command.leg_id

    broker_positions = tuple(
        U19Position(
            instrument_id=instrument_id,
            signed_quantity=(
                Decimal(str(position["qty"]))
                if str(position["side"]).upper() == "BUY"
                else -Decimal(str(position["qty"]))
            ),
        )
        for instrument_id, position in sorted(vssf.account.positions.items())
    )
    ledger_quantity = defaultdict(Decimal)
    for lot in history_before_replay:
        signed = Decimal(lot.remaining_quantity)
        ledger_quantity[lot.instrument_id] += (
            signed if lot.side == "BUY" else -signed
        )
    ledger_positions = tuple(
        U19Position(instrument_id, quantity)
        for instrument_id, quantity in sorted(ledger_quantity.items())
    )
    assert broker_positions == ledger_positions

    execution_events = tuple(
        U19ExecutionEvent(
            lot.execution_id,
            sha256(
                json.dumps(
                    {
                        "execution_id": lot.execution_id,
                        "client_order_id": lot.client_order_id,
                        "group_id": lot.group_id,
                        "leg_id": lot.leg_id,
                        "instrument_id": lot.instrument_id,
                        "quantity": lot.remaining_quantity,
                        "execution_timestamp": lot.execution_timestamp.isoformat(),

                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
        for lot in history_before_replay
    )
    as_of = max(
        fill.execution_timestamp
        for report in final_reports.values()
        for fill in report.execution_fills
    ) + timedelta(seconds=1)

    def digest(value):
        return sha256(
            json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    broker_payload = {
        "group_id": group_id,
        "positions": [
            (item.instrument_id, str(item.signed_quantity))
            for item in broker_positions
        ],
    }
    ledger_payload = {
        "group_id": group_id,
        "positions": [
            (item.instrument_id, str(item.signed_quantity))
            for item in ledger_positions
        ],
        "execution_events": [
            (event.execution_id, event.fingerprint)
            for event in execution_events
        ],
    }
    checkpoint_path = tmp_path / "t25-four-leg-u19.sqlite3"
    first_decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="T25-BROKER-INITIAL",
            as_of=as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id,
            snapshot_id="T25-LEDGER-INITIAL",
            as_of=as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions,
            complete=True,
            payload_sha256=digest(ledger_payload),
            execution_events=execution_events,
        ),
    )
    assert first_decision.restore_allowed is True

    persisted = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)
    assert persisted is not None
    assert len(persisted["execution_events"]) == 8

    reopened = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="T25-BROKER-REOPEN",
            as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id,
            snapshot_id="T25-LEDGER-REOPEN",
            as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions,
            complete=True,
            payload_sha256=digest(ledger_payload),
            execution_events=execution_events + execution_events,
        ),
    )
    assert reopened.restore_allowed is True
    assert len(reopened.execution_events) == 8
    assert bridge.position_lot_store.history() == history_before_replay
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == fees_before_replay
