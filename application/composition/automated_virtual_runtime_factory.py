"""Authoritative composition for automated Virtual strategy execution."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.virtual_track3_runtime_input_source import VirtualTrack3RuntimeInputSource
from application.composition.track2_option_contract_source import Track2OptionContractSource
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track7_option_contract_source import Track7OptionContractSource
from application.composition.track8_option_contract_source import Track8OptionContractSource
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore
from infrastructure.kis.track9_atm_iv_source import KISTrack9ATMIVSource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.account.track9_margin_read_model import VSSFTrack9MarginReadModel
from application.strategy_hub.hub import StrategyHub
from application.composition.track2_execution_plan_adapter import Track2ExecutionPlanAdapter
from application.composition.market_calendar_hub import MarketCalendarHub
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
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


def attach_standard_automated_loop(bootstrap, *, strategy_keys=None, track9_iv_history_path=None, run_id=None, historical_observation_option_source=None, risk_guard_status_source: RiskGuardStatusSource | None = None, market_calendar_hub=None):
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
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    track3_source = VirtualTrack3RuntimeInputSource(
        bootstrap.bundle.market,
        bootstrap.bundle.account,
        vssf_runtime,
        bootstrap.bundle.option_master,
    )
    fee_ledger = VirtualTrack9FeeLedger()
    margin_read_model = VSSFTrack9MarginReadModel(bootstrap.bundle.account)
    run_id = run_id or getattr(getattr(bootstrap, "run_context", None), "run_id", "")
    market_calendar_hub = market_calendar_hub or MarketCalendarHub(
        getattr(bootstrap.bundle.option_master, "calendar", None)
    )
    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market,
        track9_fee_ledger=fee_ledger,
        track9_margin_read_model=margin_read_model,
        run_id=run_id,
        option_expiry_source=expiry_source,
        trading_calendar=market_calendar_hub,
        option_master=bootstrap.bundle.option_master,
        track2_option_iv_source=track2_option_iv_source,
        option_orderbook_source=historical_observation_option_source,
        track9_iv_event_materializer=track9_iv_event_materializer,
        track9_atm_iv_source=track9_atm_iv_source,
        track7_order_timeout_source=getattr(bootstrap.bundle, "track7_order_timeout_source", None),
        track7_support_resistance_source=getattr(bootstrap.bundle, "track7_support_resistance_source", None),
        track3_runtime_input_source=track3_source,
        track6_option_contract_source=Track6OptionContractSource(bootstrap.bundle.option_master),
        track7_option_contract_source=Track7OptionContractSource(bootstrap.bundle.option_master),
        track8_option_contract_source=Track8OptionContractSource(bootstrap.bundle.option_master),
    )

    def identity(evaluation, tick):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            return None
        if str(proposal.asset_type) == "FUTURES":
            if futures_identity_source is None:
                raise ValueError("VIRTUAL_AUTHORITATIVE_FUTURES_IDENTITY_SOURCE_REQUIRED")
            return futures_identity_source.current_identity()
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

    def context_builder(tick, state):
        if historical_observation_option_source is not None:
            historical_observation_option_source.set_as_of(datetime.fromisoformat(tick.timestamp))
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
        risk_guard_status_source=risk_guard_status_source,
    )

    def multi_leg_plan_resolver(evaluation, canonical):
        strategy_id = str(getattr(evaluation.context, "strategy_id", "") or "")
        group_id = f"{run_id}-{canonical.signal_id}"
        if strategy_id == "track2_asymmetric_trap":
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
            selection = track2_option_contract_source.select(
                expiry=expiry, current_price=underlying
            )
            return track2_plan_adapter.build_plan(
                approved_signal=canonical,
                strategy=registry.get(strategy_id, "1.0"),
                current_atm=selection.atm_strike,
                active_vol=float(active.value),
                base_vol=float(base.value),
                group_id=group_id,
            )
        if strategy_id == "Strategy_3_StatArb":
            if futures_identity_source is None:
                raise ValueError("TRACK3_HEDGE_IDENTITY_SOURCE_REQUIRED")
            identity = futures_identity_source.current_identity()
            return track3_plan_adapter.build_plan(
                strategy_id=strategy_id,
                group_id=group_id,
                side=canonical.side.value,
                quantity=canonical.qty,
                identity=identity,
                hedge_identity_source=Track3HedgeIdentitySource(futures_identity_source),
            )
        if strategy_id == "track6_daily_tail_insurance":
            return registry.get(strategy_id, "1.0").build_execution_plan(group_id)
        if strategy_id == "track7_volatility_skew_weekly_insurance":
            proposal = evaluation.result.execution_proposal
            if proposal is None:
                raise ValueError("TRACK7_EXECUTION_PROPOSAL_REQUIRED")
            strategy = registry.get(strategy_id, "1.0")
            if not isinstance(strategy, Track7VolatilitySkewWeeklyInsurance):
                raise ValueError("TRACK7_STRATEGY_REGISTRY_TYPE_REQUIRED")
            return strategy.build_execution_plan(group_id, proposal=proposal)
        if strategy_id == "track8_macro_regime_monthly_strangle":
            return registry.get(strategy_id, "2.0").build_execution_plan(group_id)
        return None

    loop = AutomatedVirtualTradingLoop(
        bundle=bootstrap.bundle,
        strategy_hub=strategy_hub,
        run_id=run_id,
        fee_ledger=fee_ledger,
        context_builder=context_builder,
        identity_provider=identity,
        multi_leg_plan_resolver=multi_leg_plan_resolver,
        multi_leg_executor=multi_leg_bridge.execute,
        risk_guard_status_source=risk_guard_status_source,
    )
    bootstrap.bundle.market.subscribe(loop.on_tick)
    return loop
