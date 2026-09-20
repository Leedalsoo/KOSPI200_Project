from datetime import datetime
from decimal import Decimal
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_identity_source import KisFuturesIdentitySource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from application.composition.track3_futures_execution_plan_adapter import Track3FuturesExecutionPlanAdapter
from application.composition.track3_analytics_provider import build_track3_analytics_snapshot
from application.composition.virtual_futures_execution import VirtualFuturesExecutionBridge
from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from contracts.futures_contract_spec import FuturesProductType
from core.decision.decision_arbiter import DecisionArbiter
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track3_statistical_arbitrage import Track3MarketInput, Track3StatisticalArbitrage
from core.runtime.reference_execution_pipeline import approved_signal_to_command, DecisionCommandContext
from core.domain.market_models import MarketState


def _identity(product_type):
    raw = Path("fo_idx_code_mts.mst").read_bytes().decode("cp949", errors="replace")
    source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(raw))
    target = FuturesTargetConfiguration(underlying_short_code="2001", product_type=product_type)
    return KisFuturesIdentitySource(source, target).current_identity()


def _context(payload):
    as_of = datetime(2026, 9, 18, 10, 0)
    tick = type("Tick", (), {"instrument_id": "KOSPI200", "observed_at": as_of, "price": Decimal("500"), "volume": Decimal("100")})()
    return StrategyContext(
        market_state=MarketState(as_of=as_of, ticks={"KOSPI200": tick}, quality={}),
        strategy_id="Strategy_3_StatArb",
        input=StrategyInput(common=CommonStrategyInput(as_of=as_of, current_price=Decimal("500")), payload=payload),
        analytics=build_track3_analytics_snapshot(payload, run_id="track3-test", current_pnl=0.0, as_of=as_of),
    )


def _payload(multiplier):
    return Track3MarketInput(
        spread_history=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0),
        active_vol=0.1, base_vol=0.1, bid_ask_spread=0.02, current_price=500.0,
        options_legs=({"strike": 500, "price": 1.0, "current_market_price": 1.0, "qty": 1, "side": "BUY", "type": "CALL", "contract_multiplier": multiplier},),
        contract_multiplier=float(multiplier), market_stable=True, spread_normalizing=True,
        time_str="10:00:00", date_str="2026-09-18",
    )


def test_track3_futures_selector_and_multiplier_are_authoritative():
    standard = _identity(FuturesProductType.STANDARD)
    mini = _identity(FuturesProductType.MINI)
    assert standard.instrument_id == "A01609"
    assert standard.contract_multiplier == Decimal("250000")
    assert mini.instrument_id == "A05609"
    assert mini.contract_multiplier == Decimal("50000")


def test_track3_strategy_decision_command_and_virtual_execution_e2e():
    identity = _identity(FuturesProductType.STANDARD)
    strategy = Track3StatisticalArbitrage()
    context = _context(_payload(identity.contract_multiplier))
    result = strategy.evaluate_input(context.input.payload, context.analytics)
    assert result.status == "ENTER"
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(tick_sequence=1, context=context, result=result)
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations, price=500.0, timestamp="2026-09-18T10:00:00",
        account={"available_cash": 250_000_000},
        instrument_identity_provider=lambda _evaluation, _tick: identity,
    )
    approved = decision.arbitration.approved_signals
    assert len(approved) == 1
    signal = approved[0]
    assert signal.asset_type.value == "FUTURES"
    assert signal.instrument_id == identity.instrument_id
    assert signal.contract_multiplier == 250000.0
    command = RuntimeDecisionCommandAdapter().build_commands(evaluations, approved)[0]
    assert command.instrument_id == identity.instrument_id
    assert command.contract_multiplier == 250000.0
    assert command.asset_type.value == "FUTURES"

    plan = Track3FuturesExecutionPlanAdapter().build_plan(
        strategy_id=signal.track_id, group_id="T3-RUN-G1", side=signal.side.value,
        quantity=signal.qty, identity=identity,
    )
    bridge = VirtualFuturesExecutionBridge(bundle=create_virtual_runtime_bootstrap(initial_capital=250_000_000.0).bundle,
                                           run_id="T3-RUN", identity=identity)
    executed = bridge.execute(plan)
    assert executed.group_complete
    assert executed.reports[0].status == "FILLED"
    assert executed.reports[0].execution_id
    assert executed.reports[0].group_id == "T3-RUN-G1"
    assert executed.reports[0].leg_id == "FUTURES"
    assert bridge.position.contract_multiplier == Decimal("250000")
    assert bridge.position.identity_source == identity.identity_source
    assert bridge.provenance[executed.reports[0].execution_id]["client_order_id"] == "T3-RUN-G1-FUTURES"
    assert executed.pnl == Decimal("0.0")


def test_track3_mini_futures_virtual_execution_uses_krx_multiplier():
    identity = _identity(FuturesProductType.MINI)
    bridge = VirtualFuturesExecutionBridge(
        bundle=create_virtual_runtime_bootstrap(initial_capital=250_000_000.0).bundle,
        run_id="T3-MINI-RUN", identity=identity,
    )
    plan = Track3FuturesExecutionPlanAdapter().build_plan(
        strategy_id="Strategy_3_StatArb", group_id="T3-MINI-G1", side="SELL", quantity=1, identity=identity,
    )
    result = bridge.execute(plan)
    assert result.group_complete
    assert bridge.position.contract_multiplier == Decimal("50000")
    assert bridge.provenance[result.reports[0].execution_id]["contract_multiplier"] == "50000"
