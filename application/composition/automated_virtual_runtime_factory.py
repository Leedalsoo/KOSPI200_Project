"""Authoritative composition for automated Virtual strategy execution."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.virtual_track3_runtime_input_source import VirtualTrack3RuntimeInputSource
from infrastructure.kis.track3_runtime_input_source import KISTrack3RuntimeInputSource
from application.composition.track2_option_contract_source import Track2OptionContractSource
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track7_option_contract_source import Track7OptionContractSource
from application.composition.track8_option_contract_source import Track8OptionContractSource
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore
from infrastructure.kis.track9_atm_iv_source import KISTrack9ATMIVSource
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_kospi200_daily_source import KISKOSPI200DailySource
from infrastructure.kis.track6_atm_volatility_source import KISTrack6ATMVolatilitySource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.account.track9_margin_read_model import VSSFTrack9MarginReadModel
from environments.virtual.authoritative_vssf.track9_position_execution_read_model import VirtualTrack9PositionExecutionReadModel
from application.strategy_hub.hub import StrategyHub
from application.composition.track2_execution_plan_adapter import Track2ExecutionPlanAdapter
from application.composition.market_calendar_hub import MarketCalendarHub
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.composition.execution_multi_leg_resolver_registry import ExecutionMultiLegResolverRegistry
from contracts.types import MultiLegExecutionPlan
from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from contracts.futures_contract_spec import FuturesProductType
from application.composition.futures_identity_source import KisFuturesIdentitySource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from application.composition.track3_hedge_identity_source import Track3HedgeIdentitySource
from application.composition.track3_multi_leg_execution_plan_adapter import Track3MultiLegExecutionPlanAdapter
from decimal import Decimal
from contracts.risk_guard import RiskGuardStatusSource
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry


def attach_standard_automated_loop(bootstrap, *, track3_runtime_input_source=None, strategy_keys=None, track9_iv_history_path=None, run_id=None, historical_observation_option_source=None, risk_guard_status_source: RiskGuardStatusSource | None = None, synthetic_runtime_sources=None, track4_greeks_provider=None, market_calendar_hub=None):
    """Attach all nine Standard strategies to the RuntimeController-owned VMS."""
    selected_keys = tuple(strategy_keys) if strategy_keys else STANDARD_STRATEGY_KEYS
    registry = build_standard_strategy_registry()
    strategy_hub = StrategyHub(registry, selected_keys)
    expiry_source = KisOptionMasterExpirySource(bootstrap.bundle.option_master)
    track2_option_iv_source = historical_observation_option_source or KISTrack2OptionIVSource(bootstrap.bundle.option_master)
    track9_iv_history_source = (
        KISTrack9IVObservationHistoryStore(track9_iv_history_path)
        if track9_iv_history_path else None
    )
    track9_atm_iv_source = (
        KISTrack9ATMIVSource(option_master=bootstrap.bundle.option_master, history_source=track9_iv_history_source)
        if track9_iv_history_source is not None else None
    )
    track9_iv_event_materializer = Track9IVEventMaterializer() if track9_atm_iv_source is not None else None
    kospi200_daily_source = KISKOSPI200DailySource(KISAuthManager.from_env(is_vts=True))
    track6_volatility_source = None
    if synthetic_runtime_sources is None:
        track6_volatility_source = KISTrack6ATMVolatilitySource(
            option_master=bootstrap.bundle.option_master,
            option_iv_source=track2_option_iv_source,
        )
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    if track3_runtime_input_source is not None:
        track3_source = track3_runtime_input_source
    elif synthetic_runtime_sources is not None:
        track3_source = VirtualTrack3RuntimeInputSource(
            bootstrap.bundle.market,
            bootstrap.bundle.account,
            vssf_runtime,
            bootstrap.bundle.option_master,
        )
    else:
        track3_source = KISTrack3RuntimeInputSource()
    fee_ledger = VirtualTrack9FeeLedger()
    margin_read_model = VSSFTrack9MarginReadModel(bootstrap.bundle.account)
    run_id = run_id or getattr(getattr(bootstrap, "run_context", None), "run_id", "")
    market_calendar_hub = market_calendar_hub or MarketCalendarHub(
        getattr(bootstrap.bundle.option_master, "calendar", None)
        or getattr(synthetic_runtime_sources, "calendar", None)
    )
    def identity(evaluation, tick):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            return None
        if str(proposal.asset_type) == "FUTURES":
            if futures_identity_source is None:
                raise ValueError("VIRTUAL_AUTHORITATIVE_FUTURES_IDENTITY_SOURCE_REQUIRED")
            observed_symbol = str(getattr(tick, "instrument_id", None) or getattr(tick, "symbol", None) or "").strip()
            if not observed_symbol:
                raise ValueError("VIRTUAL_AUTHORITATIVE_FUTURES_WS_IDENTITY_INPUT_REQUIRED")
            return futures_identity_source.identity_for_observed_symbol(observed_symbol)
        if tick is None or not tick.expiry or not proposal.option_type or proposal.strike is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_INPUT_REQUIRED")
        observed_candidates = tuple(dict.fromkeys(
            str(value).strip()
            for value in (
                getattr(tick, "instrument_id", None),
                getattr(tick, "symbol", None),
            )
            if value
        ))
        identity = None
        if synthetic_runtime_sources is None:
            for observed_symbol in observed_candidates:
                observed_identity = bootstrap.bundle.option_master.get_contract_identity(observed_symbol)
                if observed_identity is None:
                    continue
                same_target = (
                    str(observed_identity.option_type).upper() == str(proposal.option_type).upper()
                    and Decimal(str(observed_identity.strike)) == Decimal(str(proposal.strike))
                )
                if same_target:
                    identity = observed_identity
                    break
        if identity is None:
            identity = bootstrap.bundle.option_master.find_contract_identity(
                tick.expiry, proposal.option_type, proposal.strike
            )
        if identity is None or not identity.shrn_iscd:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_IDENTITY_NOT_FOUND")
        if identity.contract_multiplier is None:
            raise ValueError("VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_REQUIRED")
        return OptionInstrumentIdentity(
            instrument_id=(identity.stnd_iscd or identity.shrn_iscd),
            symbol=identity.shrn_iscd,
            expiry=identity.expiry.replace("-", "")[:8],
            option_type=identity.option_type,
            strike=identity.strike,
            contract_multiplier=identity.contract_multiplier,
            identity_source="OPTION_MASTER",
        )

    def context_builder(tick, state):
        observed_at = datetime.fromisoformat(tick.timestamp)
        if historical_observation_option_source is not None:
            historical_observation_option_source.set_as_of(observed_at)
        if synthetic_runtime_sources is not None:
            synthetic_runtime_sources.set_tick(tick)
        return provider.build(tick, state, bootstrap.bundle.account)

    track2_plan_adapter = Track2ExecutionPlanAdapter()
    track2_option_contract_source = Track2OptionContractSource(bootstrap.bundle.option_master)
    track3_plan_adapter = Track3MultiLegExecutionPlanAdapter()
    futures_master_path = Path(__file__).resolve().parents[2] / "fo_idx_code_mts.mst"
    futures_identity_source = None
    if futures_master_path.is_file():
        raw = futures_master_path.read_bytes().decode("cp949", errors="replace")
        futures_master = KisCurrentFuturesContractSource(parse_kis_futures_contracts(raw))
        futures_identity_source = KisFuturesIdentitySource(
            futures_master,
            FuturesTargetConfiguration(
                underlying_short_code="2001",
                product_type=FuturesProductType.STANDARD,
            ),
        )
    multi_leg_bridge = VirtualMultiLegExecutionBridge(
        bundle=bootstrap.bundle,
        run_id=run_id,
        option_master=bootstrap.bundle.option_master,
        futures_identity_source=futures_identity_source,
        risk_guard_status_source=(risk_guard_status_source or synthetic_runtime_sources),
    )

    def track1_fence_type_source():
        strategy = registry.get("TRACK1_TAIL_DEFENSE", "1.1.0")
        if strategy.state.active_fence_type in {"PUT", "CALL"}:
            return strategy.state.active_fence_type
        if not strategy.state.market_opened:
            return "PUT"
        return None



    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market,
        track9_fee_ledger=fee_ledger,
        track9_margin_read_model=margin_read_model,
        run_id=run_id,
        option_expiry_source=expiry_source,
        trading_calendar=market_calendar_hub,
        option_master=bootstrap.bundle.option_master,
        track2_option_iv_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else track2_option_iv_source),
        track4_greeks_provider=track4_greeks_provider,
        option_orderbook_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else historical_observation_option_source),
        volume_profile_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else None),
        basis_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else None),
        track2_metrics_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else None),
        track9_iv_event_materializer=track9_iv_event_materializer,
        track9_atm_iv_source=track9_atm_iv_source,
        track7_order_timeout_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else getattr(bootstrap.bundle, "track7_order_timeout_source", None)),
        track7_support_resistance_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else getattr(bootstrap.bundle, "track7_support_resistance_source", None)),
        risk_guard_status_source=(risk_guard_status_source if risk_guard_status_source is not None else synthetic_runtime_sources),
        track3_runtime_input_source=track3_source,
        track6_option_contract_source=Track6OptionContractSource(bootstrap.bundle.option_master),
        track7_option_contract_source=Track7OptionContractSource(bootstrap.bundle.option_master),
        track8_option_contract_source=Track8OptionContractSource(bootstrap.bundle.option_master),
        kospi200_daily_source=kospi200_daily_source,
        track6_volatility_source=track6_volatility_source,
        track1_fence_type_source=track1_fence_type_source,
        track1_position_lot_store=multi_leg_bridge.position_lot_store,
        track1_option_delta_source=historical_observation_option_source,
    )
    if synthetic_runtime_sources is not None:
        provider.track9_event_source = synthetic_runtime_sources
        from environments.high_speed.synthetic_runtime_sources import SyntheticEventRiskSource
        provider.track9_event_risk_source = SyntheticEventRiskSource(synthetic_runtime_sources)

    provider.track9_position_execution_source = VirtualTrack9PositionExecutionReadModel(multi_leg_bridge)

    execution_resolvers = ExecutionMultiLegResolverRegistry()

    def resolve_track2(evaluation, canonical):
        analytics = evaluation.context.analytics
        if analytics is None:
            raise ValueError("TRACK2_MULTI_LEG_ANALYTICS_REQUIRED")
        active = analytics.get("volatility.active")
        base = analytics.get("volatility.base")
        if active is None or base is None or getattr(active, "value", None) is None or getattr(base, "value", None) is None:
            raise ValueError("TRACK2_MULTI_LEG_VOLATILITY_REQUIRED")
        market_state = evaluation.context.market_state
        if market_state is None or "KOSPI200" not in market_state.ticks:
            raise ValueError("TRACK2_UNDERLYING_PRICE_REQUIRED")
        underlying = Decimal(str(market_state.ticks["KOSPI200"].price))
        expiry = track2_option_contract_source.nearest_expiry(as_of=market_state.as_of.date())
        selection = track2_option_contract_source.select(expiry=expiry, current_price=underlying)
        group_id = f"{run_id}-{canonical.signal_id}"
        return track2_plan_adapter.build_plan(
            approved_signal=canonical,
            strategy=registry.get("track2_asymmetric_trap", "1.0"),
            current_atm=selection.atm_strike,
            active_vol=float(active.value), base_vol=float(base.value), group_id=group_id,
        )

    def resolve_track3(evaluation, canonical):
        if futures_identity_source is None:
            raise ValueError("TRACK3_HEDGE_IDENTITY_SOURCE_REQUIRED")
        group_id = f"{run_id}-{canonical.signal_id}"
        observed_symbol = str(
            getattr(canonical, "instrument_id", None)
            or getattr(canonical, "symbol", None)
            or ""
        ).strip()
        if not observed_symbol:
            raise ValueError("TRACK3_WS_FUTURES_SYMBOL_REQUIRED")
        hedge_source = Track3HedgeIdentitySource(futures_identity_source)
        observed_identity = hedge_source.identity_for_observed_symbol(observed_symbol)
        return track3_plan_adapter.build_plan(
            strategy_id="Strategy_3_StatArb", group_id=group_id,
            side=canonical.side.value, quantity=canonical.qty,
            identity=observed_identity,
            hedge_identity_source=hedge_source,
        )

    def resolve_track6(evaluation, canonical):
        if str(getattr(evaluation.result, "direction", "")) != "BUY_INSURANCE":
            return None
        return registry.get("track6_daily_tail_insurance", "1.0").build_execution_plan(
            f"{run_id}-{canonical.signal_id}"
        )

    def resolve_track7(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise ValueError("TRACK7_EXECUTION_PROPOSAL_REQUIRED")
        strategy = registry.get("track7_volatility_skew_weekly_insurance", "1.0")
        if not isinstance(strategy, Track7VolatilitySkewWeeklyInsurance):
            raise ValueError("TRACK7_STRATEGY_REGISTRY_TYPE_REQUIRED")
        return strategy.build_execution_plan(f"{run_id}-{canonical.signal_id}", proposal=proposal)

    def resolve_track8(evaluation, canonical):
        return registry.get("track8_macro_regime_monthly_strangle", "2.0").build_execution_plan(
            f"{run_id}-{canonical.signal_id}"
        )

    execution_resolvers.register("track2_asymmetric_trap", resolve_track2)
    execution_resolvers.register("Strategy_3_StatArb", resolve_track3)
    execution_resolvers.register("track6_daily_tail_insurance", resolve_track6)
    execution_resolvers.register("track7_volatility_skew_weekly_insurance", resolve_track7)
    execution_resolvers.register("track8_macro_regime_monthly_strangle", resolve_track8)

    def multi_leg_plan_resolver(evaluation, canonical):
        strategy_id = str(getattr(evaluation.context, "strategy_id", "") or "")
        return execution_resolvers.resolve(strategy_id, evaluation, canonical)

    loop = AutomatedVirtualTradingLoop(
        bundle=bootstrap.bundle,
        strategy_hub=strategy_hub,
        run_id=run_id,
        fee_ledger=fee_ledger,
        context_builder=context_builder,
        identity_provider=identity,
        multi_leg_plan_resolver=multi_leg_plan_resolver,
        multi_leg_executor=multi_leg_bridge.execute,
        risk_guard_status_source=(risk_guard_status_source or synthetic_runtime_sources),
    )
    bootstrap.bundle.market.subscribe(loop.on_tick)
    return loop
