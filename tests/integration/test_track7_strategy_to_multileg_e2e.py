from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.track7_analytics_provider import build_track7_analytics_snapshot
from application.composition.track7_option_contract_source import Track7OptionContractSource
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from core.decision.decision_arbiter import DecisionArbiter
from contracts.types import OptionInstrumentIdentity
from contracts.analytics import AnalyticsProvenance, MarketSnapshot
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance, Track7ExecutionInput
from tests.risk_guard_test_support import allow_risk_guard
from tests.support import build_test_option_master


def test_track7_strategy_decision_risk_multileg_execution_position_pnl_e2e():
    master = build_test_option_master()
    bootstrap = create_virtual_runtime_bootstrap(
        initial_capital=500_000_000.0,
        option_master=master,
        risk_guard_status_source=allow_risk_guard(),
    )
    selection = Track7OptionContractSource(master).select(
        expiry="20260910", strike=Decimal("350")
    )
    data = SimpleNamespace(
        price=Decimal("350"),
        option_iv=Decimal("30"),
        put_iv=Decimal("40"),
        ma_1m=Decimal("350"),
        ma_3m=Decimal("349"),
        ma_5m=Decimal("348"),
        ma_10m=Decimal("347"),
        support=Decimal("340"),
        resistance=Decimal("360"),
        is_new_week_start=False,
        is_expiry_day=False,
        is_week_end=False,
        order_timeout=False,
    )
    as_of = datetime(2026, 9, 8, 10, 0)
    analytics = build_track7_analytics_snapshot(
        data, run_id="TRACK7-E2E-001", as_of=as_of
    )
    context = StrategyContext(
        MarketState(as_of=as_of, ticks={}, quality={}),
        "track7_volatility_skew_weekly_insurance",
        StrategyInput(
            payload=Track7ExecutionInput(
                strategy_id="track7_volatility_skew_weekly_insurance",
                expiry="20260910",
                listed_put_strike=selection.strike,
                listed_call_strike=selection.strike,
                contract_multiplier=selection.contract_multiplier,
            )
        ),
        analytics=analytics,
    )
    strategy = Track7VolatilitySkewWeeklyInsurance()
    signals = strategy.evaluate(context)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.option_type == "PUT"
    assert signal.execution_proposal.side == "BUY"

    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1,
        context={strategy.strategy_id: context},
        result=SimpleNamespace(signals=tuple(signals), failures=()),
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=350.0,
        timestamp=as_of.isoformat(),
        account=bootstrap.bundle.account.snapshot(),
        instrument_identity_provider=lambda _evaluation, _tick: OptionInstrumentIdentity(
            instrument_id=selection.put.shrn_iscd,
            symbol=selection.put.shrn_iscd,
            expiry=selection.put.expiry,
            option_type=selection.put.option_type,
            strike=selection.put.strike,
            contract_multiplier=selection.put.contract_multiplier,
            identity_source="OPTION_MASTER",
        ),
        multi_leg_plan_resolver=lambda _evaluation, canonical: strategy.build_execution_plan(
            "TRACK7-E2E-G1", proposal=signal.execution_proposal
        ),
    )
    assert len(decision.canonical_signals) == 1
    assert len(decision.arbitration.approved_signals) == 1
    assert len(decision.multi_leg_decisions) == 1
    plan = decision.multi_leg_decisions[0].plan
    assert len(plan.legs) == 2
    assert plan.legs[0].option_type == "PUT"
    assert plan.legs[0].side == "BUY"
    assert plan.legs[1].option_type == "CALL"
    assert plan.legs[1].side == "SELL"

    market = bootstrap.bundle.market
    market._option_quotes[("PUT", 350.0, "20260910")] = {
        "bid": 10.0, "ask": 10.2, "last": 10.1,
        "contract_multiplier": Decimal("250000"), "shrn_iscd": selection.put.shrn_iscd,
    }
    market._option_quotes[("CALL", 350.0, "20260910")] = {
        "bid": 9.0, "ask": 9.2, "last": 9.1,
        "contract_multiplier": Decimal("250000"), "shrn_iscd": selection.call.shrn_iscd,
    }

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bootstrap.bundle,
        run_id="TRACK7-E2E-001",
        option_master=master,
        risk_guard_status_source=allow_risk_guard(),
    )
    result = bridge.execute(plan)
    assert result.group_complete is True
    assert result.planned_legs == 2
    assert result.routed_legs == 2
    assert result.filled_legs == 2

    reports = tuple(result.reports)
    assert len(reports) == 2
    assert all(report.execution_id for report in reports)
    assert {report.leg_id for report in reports} == {"primary", "secondary"}

    positions = bootstrap.bundle.position.snapshot()
    assert len(positions) == 2
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 2
    assert all(lot.run_id == "TRACK7-E2E-001" for lot in lots)
    assert all(lot.group_id == "TRACK7-E2E-G1" for lot in lots)
    balances = bootstrap.bundle.account.snapshot().balances
    assert balances["margin_used"] > 0
    assert balances["unrealized_pnl"] is not None

    print("TRACK7_E2E_EVIDENCE", {
        "run_id": "TRACK7-E2E-001",
        "skew": analytics.get("options.skew").value,
        "signal": signal.direction,
        "group_id": result.group_id,
        "execution_ids": [report.execution_id for report in reports],
        "filled_legs": result.filled_legs,
        "positions": len(positions),
        "margin_used": balances["margin_used"],
        "unrealized_pnl": balances["unrealized_pnl"],
    })

