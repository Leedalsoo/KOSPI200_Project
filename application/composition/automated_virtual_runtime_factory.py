"""Authoritative composition for automated Virtual strategy execution."""
from __future__ import annotations
from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from application.strategy_hub.hub import StrategyHub
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry

def attach_standard_automated_loop(bootstrap, *, strategy_keys=None):
    """Attach all nine Standard strategies to the RuntimeController-owned VMS."""
    selected_keys = tuple(strategy_keys) if strategy_keys else STANDARD_STRATEGY_KEYS
    strategy_hub = StrategyHub(build_standard_strategy_registry(), selected_keys)
    expiry_source = KisOptionMasterExpirySource(bootstrap.bundle.option_master)
    track2_option_iv_source = KISTrack2OptionIVSource(bootstrap.bundle.option_master)
    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market, option_expiry_source=expiry_source,
        track2_option_iv_source=track2_option_iv_source
    )
    def identity(evaluation):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            return None
        return OptionInstrumentIdentity(instrument_id="KOSPI200", symbol="KOSPI200", expiry="202609", option_type=proposal.option_type, strike=proposal.strike)
    loop = AutomatedVirtualTradingLoop(
        bundle=bootstrap.bundle, strategy_hub=strategy_hub,
        context_builder=lambda tick, state: provider.build(tick, state, bootstrap.bundle.account),
        identity_provider=identity,
    )
    bootstrap.bundle.market.subscribe(loop.on_tick)
    return loop
