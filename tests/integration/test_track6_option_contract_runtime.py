from decimal import Decimal
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import MultiLegExecutionPlan
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6MarketInput


def _master():
    master = InMemoryOptionContractMaster()
    for option_type, strike in (("CALL", Decimal("337.5")), ("PUT", Decimal("337.5")),
                               ("CALL", Decimal("350")), ("PUT", Decimal("350")),
                               ("CALL", Decimal("362.5")), ("PUT", Decimal("362.5"))):
        master.register_contract_identity(KisOptionContractIdentity(
            shrn_iscd=f"T6-{option_type[0]}-{strike}", stnd_iscd=None,
            expiry="202609", option_type=option_type, strike=strike,
            contract_multiplier=Decimal("250000"),
        ))
    return master


def test_track6_pair_plan_executes_two_listed_legs_with_provenance():
    master = _master()
    selection = Track6OptionContractSource(master).select(expiry="202609", current_price=Decimal("351"))
    strategy = Track6DailyTailInsurance()
    data = Track6MarketInput(
        strategy.strategy_id, Decimal("351"), Decimal("2"), Decimal("1"), Decimal("1000000"),
        "2026-09-04", listed_put_strike=selection.put.strike,
        listed_call_strike=selection.call.strike, contract_multiplier=selection.put.contract_multiplier,
    )
    strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=data)))
    plan = strategy.build_execution_plan("T6-G1")
    assert plan is not None
    assert len(plan.legs) == 2
    bootstrap = create_virtual_runtime_bootstrap(option_master=master)
    market = bootstrap.bundle.market
    market._option_quotes[("PUT", 337.5, "202609")] = {"bid": 1.0, "ask": 1.1, "last": 1.05, "contract_multiplier": Decimal("250000"), "shrn_iscd": "T6-P-337.5"}
    market._option_quotes[("CALL", 362.5, "202609")] = {"bid": 1.2, "ask": 1.3, "last": 1.25, "contract_multiplier": Decimal("250000"), "shrn_iscd": "T6-C-362.5"}
    bridge = VirtualMultiLegExecutionBridge(bundle=bootstrap.bundle, run_id="T6-RUN", option_master=master)
    result = bridge.execute(plan)
    assert result.group_complete is True
    assert result.planned_legs == 2
    assert result.filled_legs == 2
    assert [report.group_id for report in result.reports] == ["T6-G1", "T6-G1"]
    assert all(report.execution_id for report in result.reports)
    snapshot = bridge.position_groups.snapshot("T6-G1")
    assert snapshot is not None and snapshot.complete is True
    assert len(snapshot.legs) == 2
    assert snapshot.total_pnl != 0
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 2
    assert all(lot.run_id == "T6-RUN" for lot in lots)
    assert all(lot.group_id == "T6-G1" for lot in lots)
    assert all(lot.execution_id for lot in lots)
    assert all(lot.contract_multiplier == Decimal("250000") for lot in lots)

