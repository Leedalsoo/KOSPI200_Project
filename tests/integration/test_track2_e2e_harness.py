from datetime import datetime
from decimal import Decimal

import pytest

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.track2_execution_plan_adapter import Track2ExecutionPlanAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track2 import build_track2_evaluators
from core.strategy.contracts import StrategyContext
from core.strategy.standard_registry import build_standard_strategy_registry
from core.strategy.orchestrator import StrategyOrchestrator


def build_master() -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    for option_type in ("CALL", "PUT"):
        for strike in (Decimal("490"), Decimal("495"), Decimal("500"), Decimal("505"), Decimal("510")):
            master.register_contract_identity(
                KisOptionContractIdentity(
                    f"T2-{option_type[0]}-{strike}", None, "2026-09-10",
                    option_type, strike, contract_multiplier=Decimal("250000"),
                )
            )
    return master
def make_context(as_of: datetime, price: Decimal) -> StrategyContext:
    from core.domain.market_models import MarketState
    tick = type("Tick", (), {
        "instrument_id": "KOSPI200",
        "observed_at": as_of,
        "price": price,
        "volume": Decimal("500"),
    })()
    observations = {
        "bbw_window": (0.30, 0.20, 0.10),
        "volume_window": (100.0, 100.0, 500.0),
        "basis": Decimal("1.0"),
        "put_iv": Decimal("0.15"),
        "call_iv": Decimal("0.20"),
        "poc_price": Decimal("495"),
        "bid_qtys": tuple(Decimal("100") for _ in range(5)),
        "ask_qtys": tuple(Decimal("1") for _ in range(5)),
        "active_vol": Decimal("0.15"),
        "base_vol": Decimal("0.20"),
    }
    market = MarketSnapshot("T2-RUN-A", as_of, AnalyticsProvenance("TEST"), None, observations)
    keys = (
        ("volatility.bbw", ("bbw_window",)), ("volume.z_score", ("volume_window",)),
        ("microstructure.obi", ("bid_qtys", "ask_qtys")), ("futures.basis", ("basis",)),
        ("options.put_iv", ("put_iv",)), ("options.call_iv", ("call_iv",)),
        ("volume_profile.poc", ("poc_price",)), ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
    )
    requests = tuple(AnalyticsRequest(k, "tick", 20, deps, 1.0, "authoritative", "1") for k, deps in keys)
    analytics = AnalyticsEngine(build_track2_evaluators()).evaluate(market, requests)
    return StrategyContext(
        market_state=MarketState(as_of=as_of, ticks={"KOSPI200": tick}, quality={}),
        strategy_id="track2_asymmetric_trap",
        analytics=analytics,
    )
def seed_quotes(bundle, expiry: str = "202609") -> None:
    for option_type in ("CALL", "PUT"):
        for strike in (490.0, 495.0, 500.0, 505.0, 510.0):
            identity = bundle.option_master.find_contract_identity(
                expiry, option_type, Decimal(str(strike))
            )
            assert identity is not None
            bundle.market.publish_authoritative_option_quote(
                (option_type, strike, expiry),
                {
                    "bid": Decimal("1.00"),
                    "ask": Decimal("1.10"),
                    "last": Decimal("1.05"),
                    "contract_multiplier": identity.contract_multiplier,
                    "shrn_iscd": identity.shrn_iscd,
                    "timestamp": "2026-09-09T10:00:00",
                },
            )
def test_track2_e2e_authoritative_input_to_execution_and_run_isolation():
    bootstrap = create_virtual_runtime_bootstrap(
        initial_capital=250_000_000.0, option_master=build_master()
    )
    bundle = bootstrap.bundle
    seed_quotes(bundle)

    registry = build_standard_strategy_registry()
    orchestrator = StrategyOrchestrator(
        registry, (("track2_asymmetric_trap", "1.0"),)
    )
    as_of = datetime(2026, 9, 9, 10, 0)
    context = make_context(as_of, Decimal("500"))
    result = orchestrator.run({"track2_asymmetric_trap": context})
    assert result.failures == ()
    assert any(s.reason == "ASYMMETRIC_TRAP_ENTRY" for s in result.signals)

    evaluation = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1, context=context, result=result
    )
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())

    def identity_provider(ev, tick=None):
        return OptionInstrumentIdentity(
            instrument_id="T2-P-490",
            symbol="T2-P-490",
            expiry="202609",
            option_type="PUT",
            strike=Decimal("490"),
            contract_multiplier=Decimal("250000"),
            identity_source="OPTION_MASTER",
        )

    decision = adapter.arbitrate(
        evaluation, price=500.0, timestamp=as_of.isoformat(),
        account=bundle.account.snapshot(),
        instrument_identity_provider=identity_provider,
    )
    assert decision.arbitration.approved_signals
    approved = decision.arbitration.approved_signals[0]
    plan = Track2ExecutionPlanAdapter().build_plan(
        approved_signal=approved,
        strategy=registry.get("track2_asymmetric_trap", "1.0"),
        current_atm=Decimal("500"),
        active_vol=0.15,
        base_vol=0.20,
        group_id="T2-RUN-A-G1",
    )
    assert len(plan.legs) == 4
    assert {leg.side for leg in plan.legs} == {"BUY", "SELL"}

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, run_id="T2-RUN-A", option_master=bundle.option_master
    )
    executed = bridge.execute(plan)
    assert executed.group_complete
    assert executed.filled_legs == 4
    assert len(executed.reports) == 4
    assert all(r.execution_id for r in executed.reports)

    snapshot = bundle.position.snapshot()
    assert snapshot
    assert bridge.group_reports("T2-RUN-A-G1")
    assert bridge.risk_approvals("T2-RUN-A-G1")
    assert bridge.provenance

    run_b = VirtualMultiLegExecutionBridge(
        bundle=create_virtual_runtime_bootstrap(
            initial_capital=250_000_000.0, option_master=build_master()
        ).bundle,
        run_id="T2-RUN-B",
        option_master=build_master(),
    )
    assert run_b.group_reports("T2-RUN-A-G1") == ()
    assert run_b.provenance == {}
def test_track2_e2e_exit_timeout_reversal_is_strategy_owned():
    from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap

    strategy = Track2AsymmetricTrap()
    context = make_context(datetime(2026, 9, 9, 10, 0), Decimal("500"))
    assert strategy.evaluate(context)

    strategy._short_switch_at = datetime(2026, 9, 9, 10, 0)
    signals = strategy.evaluate_trap(
        Decimal("500"), datetime(2026, 9, 9, 10, 16)
    )
    assert signals
    assert signals[0].reason == "SHORT_SWITCH_TIMEOUT_EXIT"
