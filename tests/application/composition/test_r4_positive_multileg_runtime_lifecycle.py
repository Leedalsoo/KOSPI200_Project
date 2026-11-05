from dataclasses import replace
from datetime import date, datetime, timedelta
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
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
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
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
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
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
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
