from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote

DATASET = Path("data/derived_scenario/q25_a4_s6_rank5_rank6_v2")
MANIFEST = Path("reports/synth/Q25_A4_S6_RANK5_RANK6_MANIFEST_20261106_v2.json")


def _fixture_identity(tick, option_master):
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


def test_virtual_bridge_explicit_cancel_reconciles_terminal_status_and_clears_pending():
    adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
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
        run_id="Q25-PENDING-EXPLICIT-CANCEL",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(plan, leg, contract_identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="Q25_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-EXPLICIT-CANCEL-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE", tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY", instrument_id=command.instrument_id,
            symbol=command.broker_symbol, source_instant=observed, received_at=observed,
            evidence_sha256=sha256(f"{observed.isoformat()}|{command.instrument_id}".encode()).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)
    plan = MultiLegExecutionPlan(
        group_id="Q25-EXPLICIT-CANCEL-GROUP", strategy_id="TRACK1_TAIL_DEFENSE",
        purpose="Q25_EXPLICIT_CANCEL_RECONCILIATION",
        legs=(ExecutionLeg(
            "call-leg", "BUY", 1, option_type="CALL", strike=identity.strike,
            requested_price=limit_price, instrument_identity=identity,
        ),),
    )
    initial = bridge.execute(plan)
    assert initial.pending_legs == 1 and initial.reports[0].status == "NEW"
    client_order_id = initial.reports[0].client_order_id

    cancelled = bridge.cancel_pending_order(client_order_id)
    assert cancelled.pending_legs == 0
    assert cancelled.reports[0].status == "CANCELLED"
    assert client_order_id not in bridge.pending_legs
    assert bridge.position_lot_store.open_lots() == ()
    assert cancelled.position_flat is True


def test_virtual_bridge_delayed_fill_reconciles_callback_and_position():
    adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
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
        run_id="Q25-A4-PENDING-FILL-RECONCILIATION",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    callbacks = []
    original_callback = loop.strategy_hub.on_execution_result

    def capture_callback(strategy_id, purpose, result):
        callbacks.append(result)
        original_callback(strategy_id, purpose, result)

    loop.strategy_hub.on_execution_result = capture_callback

    def freshness(plan, leg, contract_identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="Q25_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-A4-PENDING-RECONCILE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE", tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY", instrument_id=command.instrument_id,
            symbol=command.broker_symbol, source_instant=observed, received_at=observed,
            evidence_sha256=sha256(f"{observed.isoformat()}|{command.instrument_id}".encode()).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)
    plan = MultiLegExecutionPlan(
        group_id="Q25-A4-PENDING-FILL-GROUP", strategy_id="TRACK1_TAIL_DEFENSE",
        purpose="Q25_A4_PENDING_FILL_RECONCILIATION",
        legs=(ExecutionLeg(
            "call-leg", "BUY", 1, option_type="CALL", strike=identity.strike,
            requested_price=limit_price, instrument_identity=identity,
        ),),
    )
    initial = bridge.execute(plan)
    assert initial.routed_legs == 1 and initial.filled_legs == 0
    assert initial.pending_legs == 1 and initial.reports[0].status == "NEW"
    assert len(bridge.pending_legs) == 1
    assert bridge.position_lot_store.open_lots() == ()

    improved = replace(
        tick,
        timestamp=(datetime.fromisoformat(tick.timestamp) + timedelta(seconds=1)).isoformat(),
        bid_price=float(limit_price - Decimal("0.01")),
        ask_price=float(limit_price),
        last_price=float(limit_price),
    )
    _publish_contract_scoped_replay_quote(
        improved, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book,
    )
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
