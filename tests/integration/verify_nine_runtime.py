from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from core.strategy.standard_registry import build_standard_strategy_registry, STANDARD_STRATEGY_KEYS
from core.strategy.orchestrator import StrategyOrchestrator
from contracts.types import OptionInstrumentIdentity

bootstrap = create_virtual_runtime_bootstrap()
orchestrator = StrategyOrchestrator(build_standard_strategy_registry(), STANDARD_STRATEGY_KEYS)
provider = StandardRuntimeInputProvider(bootstrap.bundle.market)

def identity(evaluation):
    proposal = evaluation.result.execution_proposal
    if proposal is None:
        return None
    return OptionInstrumentIdentity(
        instrument_id="KOSPI200", symbol="KOSPI200", expiry="202609",
        option_type=proposal.option_type, strike=proposal.strike,
    )

loop = AutomatedVirtualTradingLoop(
    bundle=bootstrap.bundle,
    strategy_orchestrator=orchestrator,
    context_builder=lambda tick, state: provider.build(tick, state, bootstrap.bundle.account),
    identity_provider=identity,
)
tick = next(bootstrap.bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
result = loop.on_tick(tick)
print("RUNTIME_STRATEGIES", len(STANDARD_STRATEGY_KEYS))
print("RESULT", result)
print("EXECUTIONS", len(bootstrap.bundle.execution.reports()))
print("POSITIONS", len(bootstrap.bundle.position.snapshot()))
print("CONTROLLER_STATE", bootstrap.runtime_controller.status())


