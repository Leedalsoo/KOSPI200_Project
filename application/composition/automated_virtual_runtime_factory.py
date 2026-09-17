"""Authoritative composition for automated Virtual strategy execution."""
from __future__ import annotations

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.virtual_track3_runtime_input_source import VirtualTrack3RuntimeInputSource
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore
from infrastructure.kis.track9_atm_iv_source import KISTrack9ATMIVSource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer
from application.strategy_hub.hub import StrategyHub
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry


def attach_standard_automated_loop(bootstrap, *, strategy_keys=None, track9_iv_history_path=None):
    """Attach all nine Standard strategies to the RuntimeController-owned VMS."""
    selected_keys = tuple(strategy_keys) if strategy_keys else STANDARD_STRATEGY_KEYS
    strategy_hub = StrategyHub(build_standard_strategy_registry(), selected_keys)
    expiry_source = KisOptionMasterExpirySource(bootstrap.bundle.option_master)
    track2_option_iv_source = KISTrack2OptionIVSource(bootstrap.bundle.option_master)
    track9_iv_history_source = (
        KISTrack9IVObservationHistoryStore(track9_iv_history_path)
        if track9_iv_history_path else None
    )
    track9_atm_iv_source = (
        KISTrack9ATMIVSource(option_master=bootstrap.bundle.option_master, history_source=track9_iv_history_source)
        if track9_iv_history_source is not None else None
    )
    track9_iv_event_materializer = Track9IVEventMaterializer() if track9_atm_iv_source is not None else None
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    track3_source = VirtualTrack3RuntimeInputSource(
        bootstrap.bundle.market,
        bootstrap.bundle.account,
        vssf_runtime,
        bootstrap.bundle.option_master,
    )
    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market,
        option_expiry_source=expiry_source,
        trading_calendar=getattr(bootstrap.bundle.option_master, "calendar", None),
        option_master=bootstrap.bundle.option_master,
        track2_option_iv_source=track2_option_iv_source,
        track9_iv_event_materializer=track9_iv_event_materializer,
        track9_atm_iv_source=track9_atm_iv_source,
        track7_order_timeout_source=getattr(bootstrap.bundle, "track7_order_timeout_source", None),
        track7_support_resistance_source=getattr(bootstrap.bundle, "track7_support_resistance_source", None),
        track3_runtime_input_source=track3_source,
    )

    def identity(evaluation, tick):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            return None
        if tick is None or not tick.expiry or not proposal.option_type or proposal.strike is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_INPUT_REQUIRED")
        identity = bootstrap.bundle.option_master.find_contract_identity(
            tick.expiry, proposal.option_type, proposal.strike
        )
        if identity is None or not identity.shrn_iscd:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_NOT_FOUND")
        if identity.contract_multiplier is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_REQUIRED")
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
        bundle=bootstrap.bundle,
        strategy_hub=strategy_hub,
        context_builder=lambda tick, state: provider.build(tick, state, bootstrap.bundle.account),
        identity_provider=identity,
    )
    bootstrap.bundle.market.subscribe(loop.on_tick)
    return loop
