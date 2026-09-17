from datetime import datetime
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from contracts.types import OptionInstrumentIdentity
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.standard_registry import build_standard_strategy_registry
from application.strategy_hub.hub import StrategyHub
from core.strategy.track1_tail_defense import Track1Input
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from tests.support import build_test_option_master


def test_market_tick_to_strategy_orchestrator_oms_virtual_execution_and_control_tower():
    bootstrap = create_virtual_runtime_bootstrap(initial_capital=250_000_000.0, option_master=build_test_option_master())
    bundle = bootstrap.bundle
    registry = build_standard_strategy_registry()
    strategy_hub = StrategyHub(registry, (("TRACK1_TAIL_DEFENSE", "1.1.0"),))

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
        return OptionInstrumentIdentity(
            instrument_id="KOSPI200", symbol="KOSPI200", expiry="202609",
            option_type=proposal.option_type, strike=proposal.strike,
        )

    loop = AutomatedVirtualTradingLoop(
        bundle=bundle, strategy_hub=strategy_hub,
        context_builder=contexts, identity_provider=identity,
    )
    bundle.market.subscribe(loop.on_tick)
    tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    result = loop.last_result

    assert result is not None
    assert result.tick_sequence == tick.seq_id == 1
    assert result.signals == 3
    assert result.approved == 1
    assert result.routed == 1
    assert result.filled == 1
    assert result.rejected == 0
    assert result.execution_ids
    assert bundle.execution.reports()
    assert bundle.position.snapshot()

    balances = bundle.account.snapshot().balances
    assert balances["margin_used"] > 0
    assert balances["available_cash"] < Decimal("250000000")

    class Hub: active = bundle
    class Controller:
        environment_hub = Hub()
        def status(self): return type("Status", (), {"state": "RUNNING"})()

    view = ControlTowerUIAdapter(runtime_controller=Controller(), risk_engine=bootstrap.risk_engine).get_tab_detail("virtual_broker")
    assert len(view["recent_executions"]) == 1
    assert len(view["positions"]) == 1
    assert view["margin_used"] == float(balances["margin_used"])
    assert view["margin_available"] == float(balances["available_cash"])
    print("AUTOMATED_RUNTIME_LOOP_EVIDENCE", {"tick": tick.seq_id, "underlying": tick.underlying_price, "ask": tick.ask_price, "signals": result.signals, "approved": result.approved, "routed": result.routed, "filled": result.filled, "execution_ids": result.execution_ids, "positions": len(view["positions"]), "executions": len(view["recent_executions"]), "margin_used": balances["margin_used"], "margin_available": balances["available_cash"], "realized_pnl": balances["realized_pnl"], "unrealized_pnl": balances["unrealized_pnl"]})





