from datetime import datetime
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

DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")


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
