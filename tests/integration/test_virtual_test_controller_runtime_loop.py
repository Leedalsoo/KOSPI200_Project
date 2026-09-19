from datetime import datetime
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.control_tower_hub import ControlTowerHub
from application.runtime_hub.hub import RuntimeHub
from application.strategy_hub.hub import StrategyHub
from contracts.types import OptionInstrumentIdentity
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.standard_registry import build_standard_strategy_registry
from core.strategy.track1_tail_defense import Track1Input
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from interfaces.control_tower.virtual_test_controller import VirtualTestController


def test_next_tick_runs_standard_strategy_loop_through_controller_to_virtual_execution_position_pnl():
    master = InMemoryOptionContractMaster()
    for option_type in ("CALL", "PUT"):
        for strike in (335, 337.5, 342.5, 350, 362.5, 365):
            master.register_contract_identity(KisOptionContractIdentity(
                shrn_iscd=f"TEST-{option_type[0]}-{strike}", stnd_iscd=None, expiry="202609",
                option_type=option_type, strike=Decimal(str(strike)), contract_multiplier=Decimal("250000"),
            ))
    bootstrap = create_virtual_runtime_bootstrap(option_master=master)
    bundle = bootstrap.bundle
    strategy_hub = StrategyHub(
        build_standard_strategy_registry(),
        (("TRACK1_TAIL_DEFENSE", "1.1.0"),),
    )

    def contexts(tick, market_state):
        as_of = datetime.fromisoformat(tick.timestamp)
        return {"TRACK1_TAIL_DEFENSE": StrategyContext(
            market_state=market_state,
            strategy_id="TRACK1_TAIL_DEFENSE",
            input=StrategyInput(
                common=CommonStrategyInput(as_of=as_of, current_price=Decimal(str(tick.underlying_price))),
                payload=Track1Input(days_to_expiry=10.0, current_time=as_of, active_vol=1.0, base_vol=1.0),
            ),
        )}

    def identity(evaluation, tick):
        proposal = evaluation.result.execution_proposal
        identity = bundle.option_master.find_contract_identity(
            tick.expiry, proposal.option_type, proposal.strike
        )
        assert identity is not None
        return OptionInstrumentIdentity(
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            expiry=identity.expiry.replace("-", "")[:6],
            option_type=identity.option_type,
            strike=identity.strike,
            contract_multiplier=identity.contract_multiplier,
            identity_source="OPTION_MASTER",
        )

    loop = AutomatedVirtualTradingLoop(
        bundle=bundle, strategy_hub=strategy_hub, run_id="TEST-RUN-NEXT-TICK",
        context_builder=contexts, identity_provider=identity,
    )
    runtime_hub = RuntimeHub(loop)
    controller = VirtualTestController(market=bundle.market, tick_handler=runtime_hub.on_tick)
    tower = ControlTowerHub(
        runtime_controller=bootstrap.runtime_controller,
        ui_adapter=bootstrap.ui_adapter,
        strategy_hub=strategy_hub,
        virtual_test_controller=controller,
    )

    tower.virtual_test_action("ARM")
    tower.virtual_test_action("START")
    result_view = tower.virtual_test_action("NEXT_TICK")

    result = loop.last_result
    assert result is not None
    assert result.tick_sequence == result_view["tick"].seq_id == 1
    assert result.signals == 3
    assert result.approved == 1
    assert result.routed == 1
    assert result.filled == 1
    assert result.execution_ids
    assert bundle.execution.reports()
    assert bundle.position.snapshot()

    balances = bundle.account.snapshot().balances
    assert balances["margin_used"] > 0
    assert "realized_pnl" in balances
    assert "unrealized_pnl" in balances
    assert result_view["runtime_result"]["filled"] == 1
    assert result_view["processed_ticks"] == 1
