"""Authoritative composition for automated Virtual strategy execution."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from decimal import Decimal

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.virtual_track3_runtime_input_source import VirtualTrack3RuntimeInputSource
from infrastructure.kis.track3_runtime_input_source import KISTrack3RuntimeInputSource
from application.composition.track2_option_contract_source import Track2OptionContractSource
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track7_option_contract_source import Track7OptionContractSource
from application.composition.track8_option_contract_source import Track8OptionContractSource
from application.composition.track9_option_contract_source import Track9OptionContractSource
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from core.strategy.track5_gap_divergence import Track5GapDivergence
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore
from infrastructure.kis.track9_atm_iv_source import KISTrack9ATMIVSource
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_kospi200_daily_source import KISKOSPI200DailySource
from infrastructure.kis.track6_atm_volatility_source import KISTrack6ATMVolatilitySource
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.track2_market_metrics_source import KISTrack2MarketMetricsSource
from infrastructure.kis.track2_market_observation_sink import KISTrack2MarketObservationSink
from infrastructure.kis.volume_profile_source import KISVolumeProfileSource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.account.track9_margin_read_model import VSSFTrack9MarginReadModel
from environments.virtual.authoritative_vssf.track9_position_execution_read_model import VirtualTrack9PositionExecutionReadModel
from application.strategy_hub.hub import StrategyHub
from application.composition.track2_execution_plan_adapter import Track2ExecutionPlanAdapter
from application.composition.market_calendar_hub import MarketCalendarHub
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.composition.authoritative_option_quote_freshness_provider import AuthoritativeOptionQuoteFreshnessProvider
from application.composition.execution_multi_leg_resolver_registry import ExecutionMultiLegResolverRegistry
from contracts.types import MultiLegExecutionPlan, ExecutionLeg
from infrastructure.kis.instrument_master_provider import KisFuturesInstrumentMasterProvider
from infrastructure.kis.kis_index_option_master_source import KIS_INDEX_MASTER_URL
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity, require_futures_identity
from application.composition.futures_identity_source import KisFuturesIdentitySource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from application.composition.track3_hedge_identity_source import Track3HedgeIdentitySource
from application.composition.track3_multi_leg_execution_plan_adapter import Track3MultiLegExecutionPlanAdapter
from decimal import Decimal
from contracts.risk_guard import RiskGuardStatusSource
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry
from environments.high_speed.validation_only_track6_gates import apply_track6_validation_gates
from environments.high_speed.validation_only_track6_execution import Track6SyntheticFreshnessProvider
from core.strategy.track6_order_lifecycle import Track6LifecycleConfig
from environments.high_speed.track6_validation_state_store import Track6ValidationStateStore

logger = logging.getLogger(__name__)


def attach_standard_automated_loop(bootstrap, *, track3_runtime_input_source=None, strategy_keys=None, track9_iv_history_path=None, run_id=None, historical_observation_option_source=None, risk_guard_status_source: RiskGuardStatusSource | None = None, synthetic_runtime_sources=None, track4_greeks_provider=None, market_calendar_hub=None, validation_only_track6_signal_mode: bool = False, validation_only_track6_execution_gate=None, validation_only_s8_runtime_adapter=None, validation_only_track6_lifecycle_config: Track6LifecycleConfig | None = None):
    """Attach all nine Standard strategies to the RuntimeController-owned VMS."""
    selected_keys = tuple(strategy_keys) if strategy_keys else STANDARD_STRATEGY_KEYS
    run_id = run_id or getattr(getattr(bootstrap, "run_context", None), "run_id", "")
    registry = build_standard_strategy_registry()
    track6_validation_gate_evidence = None
    if validation_only_track6_execution_gate is not None:
        if validation_only_track6_signal_mode or synthetic_runtime_sources is None:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_MODE_CONFLICT")
        selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in selected_keys}
        if "track6_daily_tail_insurance" not in selected_ids:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_STRATEGY_NOT_SELECTED")
        validation_only_track6_execution_gate.apply_to_strategy(
            registry.get("track6_daily_tail_insurance", "1.0"), synthetic_sources=synthetic_runtime_sources
        )
        track6_validation_gate_evidence = validation_only_track6_execution_gate.evidence
    if validation_only_track6_signal_mode:
        if synthetic_runtime_sources is None:
            raise ValueError("TRACK6_VALIDATION_SYNTHETIC_RUNTIME_REQUIRED")
        selected_strategy_ids = {
            key[0] if isinstance(key, tuple) else str(key)
            for key in selected_keys
        }
        if "track6_daily_tail_insurance" not in selected_strategy_ids:
            raise ValueError("TRACK6_VALIDATION_STRATEGY_NOT_SELECTED")
        track6_validation_gate_evidence = apply_track6_validation_gates(
            registry.get("track6_daily_tail_insurance", "1.0"),
            validation_only_synthetic=True,
            synthetic_runtime_sources=synthetic_runtime_sources,
        )
    if validation_only_s8_runtime_adapter is not None:
        if validation_only_track6_execution_gate is not None or validation_only_track6_signal_mode:
            raise ValueError("S8_VALIDATION_GATE_MODE_CONFLICT")
        selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in selected_keys}
        if "track8_macro_regime_monthly_strangle" not in selected_ids or synthetic_runtime_sources is None:
            raise ValueError("S8_VALIDATION_STRATEGY_OR_SOURCE_REQUIRED")
        validation_only_s8_runtime_adapter.apply_to_strategy(
            registry.get("track8_macro_regime_monthly_strangle", "2.0"),
            synthetic_sources=synthetic_runtime_sources,
        )
    if validation_only_track6_lifecycle_config is not None:
        if synthetic_runtime_sources is None or validation_only_track6_execution_gate is None:
            raise ValueError("TRACK6_SEQUENTIAL_LIFECYCLE_REQUIRES_VALIDATION_ONLY_SYNTHETIC_GATE")
        strategy = registry.get("track6_daily_tail_insurance", "1.0")
        state_store = Track6ValidationStateStore(
            Path("reports/synth/q25_s6_runtime_state"), run_id=run_id,
        )
        strategy.configure_validation_lifecycle(
            validation_only_track6_lifecycle_config, state_store=state_store, run_id=run_id,
        )
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
    kospi200_daily_source = synthetic_runtime_sources if synthetic_runtime_sources is not None else KISKOSPI200DailySource(KISAuthManager.from_env(is_vts=True))
    if synthetic_runtime_sources is not None:
        from environments.high_speed.synthetic_runtime_sources import SyntheticTrack6VolatilitySource
        track6_volatility_source = SyntheticTrack6VolatilitySource(synthetic_runtime_sources, bootstrap.bundle.option_master)
    else:
        track6_volatility_source = KISTrack6ATMVolatilitySource(
            option_master=bootstrap.bundle.option_master,
            option_iv_source=track2_option_iv_source,
        )
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    if validation_only_track6_lifecycle_config is not None:
        strategy = registry.get("track6_daily_tail_insurance", "1.0")
        def track6_restart_reconciliation(data, lifecycle):
            selected = next((item for item in data.ranked_candidates
                             if item.rank == lifecycle.snapshot.selected_rank), None)
            if selected is None:
                return {}, {}, False
            account_positions = getattr(vssf_runtime.account, "positions", {})
            def qty(instrument_id):
                value = account_positions.get(instrument_id, 0)
                return int(getattr(value, "quantity", getattr(value, "qty", value)) or 0)
            positions = {
                "put": qty(selected.put_identity.instrument_id),
                "call": qty(selected.call_identity.instrument_id),
            }
            expected = lifecycle.snapshot.working_client_order_id
            if not expected:
                return {}, positions, True
            report = vssf_runtime.query_order(expected)
            if report is None or str(getattr(report, "client_order_id", "")) != expected:
                return {}, positions, False
            return {expected: report}, positions, True
        strategy.restart_reconciliation_provider = track6_restart_reconciliation
        def track6_restore_group_budget(data, lifecycle):
            snapshot = lifecycle.snapshot
            if not any(snapshot.filled_quantity.values()):
                return
            selected = next((item for item in data.ranked_candidates
                             if item.rank == snapshot.selected_rank), None)
            if selected is None or not snapshot.group_id:
                raise ValueError("TRACK6_RESTART_GROUP_BUDGET_RESTORE_EVIDENCE_MISSING")
            premiums = {}
            for leg, identity in (("put", selected.put_identity), ("call", selected.call_identity)):
                quantity = int(snapshot.filled_quantity.get(leg, 0) or 0)
                price = snapshot.average_fill_price.get(leg)
                if quantity <= 0:
                    continue
                if price is None or snapshot.client_order_ids.get(leg) is None:
                    raise ValueError("TRACK6_RESTART_GROUP_BUDGET_FILL_EVIDENCE_MISSING")
                premiums[leg] = {
                    "client_order_id": snapshot.client_order_ids[leg],
                    "instrument_id": identity.instrument_id,
                    "premium_krw": str(Decimal(str(price)) * Decimal(str(identity.contract_multiplier)) * quantity),
                }
            validation_only_track6_execution_gate.sync_group_reservation(snapshot.group_id, premiums)
        strategy.restart_reconciliation_restore_provider = track6_restore_group_budget
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
    if synthetic_runtime_sources is not None:
        retry_calendar = (
            getattr(synthetic_runtime_sources, "calendar", None)
            or getattr(market_calendar_hub, "calendar", None)
        )
        if (
            getattr(retry_calendar, "source_type", None) == "SYNTHETIC"
            and getattr(retry_calendar, "authoritative", True) is False
            and callable(getattr(retry_calendar, "is_retry_window_open", None))
        ):
            registry.get("track8_macro_regime_monthly_strangle", "2.0").retry_calendar = retry_calendar
    def identity(evaluation, tick, *, asset_type=None):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            return None
        if str(getattr(proposal, "tag_id", "")) == "DAILY_TAIL_INSURANCE_FORCE_CLOSE":
            # Canonical arbitration needs one concrete identity; the resolver below
            # still builds the complete close plan from every open S6 PositionLot.
            open_lots = tuple(
                lot for lot in multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.strategy_id == "track6_daily_tail_insurance"
                and lot.remaining_quantity > 0
            )
            if not open_lots or open_lots[0].instrument_identity is None:
                raise ValueError("TRACK6_FORCE_CLOSE_OPEN_LOT_IDENTITY_REQUIRED")
            return open_lots[0].instrument_identity
        resolved_asset_type = str(asset_type or proposal.asset_type).upper()
        if resolved_asset_type == "FUTURES":
            if synthetic_runtime_sources is not None:
                from contracts.futures_identity_source_port import FuturesInstrumentIdentity
                # Synthetic replay ticks expose the underlying as a MarketTick,
                # which intentionally has no broker futures contract field. Use the
                # synthetic KRX-standard product specification explicitly rather than
                # consulting the live/current KIS futures master.
                multiplier = Decimal("250000")
                product_type = FuturesProductType.STANDARD
                observed_symbol = str(
                    getattr(tick, "underlying_symbol", None)
                    or getattr(tick, "symbol", None)
                    or getattr(tick, "instrument_id", "")
                ).strip()
                if not observed_symbol:
                    raise ValueError("VIRTUAL_SYNTHETIC_FUTURES_SYMBOL_REQUIRED")
                # Keep the synthetic Futures identity distinct from the option
                # replay tick symbol so VSSF cannot mark a Futures position with
                # an option premium from the shared synthetic MarketTick.
                futures_symbol = f"{observed_symbol}_FUTURES"
                return FuturesInstrumentIdentity(
                    instrument_id=futures_symbol,
                    symbol=futures_symbol,
                    product_type=product_type,
                    contract_multiplier=multiplier,
                    identity_source="SYNTHETIC:high-speed-market-model-v2",
                )
            if futures_identity_source is None:
                raise ValueError("VIRTUAL_AUTHORITATIVE_FUTURES_IDENTITY_SOURCE_REQUIRED")
            timestamp = (getattr(tick, "timestamp", None) or getattr(tick, "observed_at", None)) if tick is not None else None
            if not timestamp:
                raise ValueError("VIRTUAL_AUTHORITATIVE_FUTURES_AS_OF_REQUIRED")
            return futures_identity_source.identity_for_as_of(datetime.fromisoformat(str(timestamp)))
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
        if identity is None and (validation_only_track6_execution_gate is not None or validation_only_s8_runtime_adapter is not None):
            # Execution validation may only route an identity already present in the
            # manifest-adapted dataset Option Master. Never invoke the synthetic
            # fallback identity generator for an unlisted contract.
            requested_expiry = str(tick.expiry).replace("-", "")[:8]
            identity = next((
                candidate for candidate in bootstrap.bundle.option_master.list_contract_identities()
                if str(candidate.expiry).replace("-", "")[:8] == requested_expiry
                and str(candidate.option_type).upper() == str(proposal.option_type).upper()
                and candidate.strike is not None
                and Decimal(str(candidate.strike)) == Decimal(str(proposal.strike))
                and str(getattr(candidate, "shrn_iscd", "")).startswith("SYNTHETIC_CONTRACT:")
            ), None)
        elif identity is None:
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
    track2_basis_source = None
    track2_metrics_source = None
    track2_volume_profile_source = None
    track2_market_observation_sink = None
    if synthetic_runtime_sources is None:
        track2_basis_source = KISBasisSource()
        track2_metrics_source = KISTrack2MarketMetricsSource()
        track2_volume_profile_source = KISVolumeProfileSource()
        track2_market_observation_sink = KISTrack2MarketObservationSink(
            basis_source=track2_basis_source,
            metrics_source=track2_metrics_source,
            volume_profile_source=track2_volume_profile_source,
        )
    track2_option_contract_source = Track2OptionContractSource(bootstrap.bundle.option_master)
    track3_plan_adapter = Track3MultiLegExecutionPlanAdapter()
    futures_identity_source = None
    if synthetic_runtime_sources is None:
        try:
            futures_master = KisFuturesInstrumentMasterProvider(
                source_url=KIS_INDEX_MASTER_URL,
            ).current_mini_futures_source(underlying_short_code="2001")
            futures_identity_source = KisFuturesIdentitySource(
                futures_master,
                FuturesTargetConfiguration(
                    underlying_short_code="2001",
                    product_type=FuturesProductType.MINI,
                ),
            )
        except Exception as exc:
            # Keep the Virtual runtime available, but never fall back to a stale local master.
            logger.warning("VIRTUAL_FUTURES_IDENTITY_SOURCE_UNAVAILABLE: %s", exc)
    def on_multi_leg_execution_result(plan, result):
        strategy_hub.on_execution_result(plan.strategy_id, plan.purpose or "", result)
        if (validation_only_s8_runtime_adapter is not None
                and plan.strategy_id == "track8_macro_regime_monthly_strangle"
                and bool(getattr(result, "position_flat", False))):
            validation_only_s8_runtime_adapter.release_all_groups()
        if (validation_only_track6_execution_gate is not None
                and validation_only_track6_lifecycle_config is not None
                and plan.strategy_id == "track6_daily_tail_insurance"):
            lifecycle = getattr(strategy, "lifecycle", None)
            if (bool(getattr(result, "position_flat", False))
                    and int(getattr(result, "pending_legs", 0) or 0) == 0):
                validation_only_track6_execution_gate.release_group(plan.group_id)
            elif lifecycle is not None and any(lifecycle.snapshot.filled_quantity.values()):
                put_identity = getattr(strategy.state, "put_instrument_identity", None)
                call_identity = getattr(strategy.state, "call_instrument_identity", None)
                if put_identity is not None and call_identity is not None and lifecycle.snapshot.group_id:
                    premiums = {}
                    for leg, identity in (("put", put_identity), ("call", call_identity)):
                        quantity = int(lifecycle.snapshot.filled_quantity.get(leg, 0) or 0)
                        price = lifecycle.snapshot.average_fill_price.get(leg)
                        if quantity > 0 and price is not None and lifecycle.snapshot.client_order_ids.get(leg):
                            premiums[leg] = {
                                "client_order_id": lifecycle.snapshot.client_order_ids[leg],
                                "instrument_id": identity.instrument_id,
                                "premium_krw": str(Decimal(str(price)) * Decimal(str(identity.contract_multiplier)) * quantity),
                            }
                    if premiums:
                        validation_only_track6_execution_gate.sync_group_reservation(lifecycle.snapshot.group_id, premiums)

    multi_leg_bridge = VirtualMultiLegExecutionBridge(
        bundle=bootstrap.bundle,
        run_id=run_id,
        option_master=bootstrap.bundle.option_master,
        futures_identity_source=futures_identity_source,
        option_expiry_source=expiry_source,
        risk_guard_status_source=(risk_guard_status_source or synthetic_runtime_sources),
        execution_result_callback=on_multi_leg_execution_result,
        freshness_verdict_provider=(
            Track6SyntheticFreshnessProvider(
                option_master=bootstrap.bundle.option_master, market=bootstrap.bundle.market,
                max_age_seconds=validation_only_track6_execution_gate.evidence.max_quote_age_seconds,
                synthetic_sources=synthetic_runtime_sources,
            ) if validation_only_track6_execution_gate is not None else (
                (lambda plan, _leg, identity, command: validation_only_s8_runtime_adapter.freshness_verdict(
                    plan=plan, identity=identity, command=command,
                    option_master=bootstrap.bundle.option_master,
                    market=bootstrap.bundle.market, synthetic_sources=synthetic_runtime_sources,
                )) if validation_only_s8_runtime_adapter is not None else AuthoritativeOptionQuoteFreshnessProvider(
                    option_master=bootstrap.bundle.option_master,
                evidence_provider=(
                    lambda _plan, _leg, _identity, command: (
                        historical_observation_option_source.get_freshness_evidence(
                            str(command.broker_symbol or command.instrument_id or "")
                        )
                        if historical_observation_option_source is not None
                        else None
                    )
                ),
                )
            )
        ),
        validation_order_gate=(
            validation_only_track6_execution_gate.validate_group
            if validation_only_track6_execution_gate is not None
            else validation_only_s8_runtime_adapter.validate_group
            if validation_only_s8_runtime_adapter is not None
            else None
        ),
    )

    def track1_fence_type_source():
        strategy = registry.get("TRACK1_TAIL_DEFENSE", "1.1.0")
        if strategy.state.active_fence_type in {"PUT", "CALL"}:
            return strategy.state.active_fence_type
        if not strategy.state.market_opened:
            return "PUT"
        return None



    track9_option_contract_source = (
        Track9OptionContractSource(
            orderbook_source=historical_observation_option_source,
            s1_position_lot_store=multi_leg_bridge.position_lot_store,
            run_id=run_id,
        )
        if synthetic_runtime_sources is None and historical_observation_option_source is not None
        else None
    )
    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market,
        track9_fee_ledger=fee_ledger,
        track9_margin_read_model=margin_read_model,
        run_id=run_id,
        option_expiry_source=expiry_source,
        trading_calendar=market_calendar_hub,
        option_master=bootstrap.bundle.option_master,
        track6_option_mark_max_age_seconds=(
            track6_validation_gate_evidence.max_quote_age_seconds
            if track6_validation_gate_evidence is not None else None
        ),
        track2_option_iv_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else track2_option_iv_source),
        track4_greeks_provider=track4_greeks_provider,
        option_orderbook_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else historical_observation_option_source),
        volume_profile_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else track2_volume_profile_source),
        basis_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else track2_basis_source),
        track2_metrics_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else track2_metrics_source),
        track9_iv_event_materializer=track9_iv_event_materializer,
        track9_atm_iv_source=track9_atm_iv_source,
        track7_order_timeout_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else getattr(bootstrap.bundle, "track7_order_timeout_source", None)),
        track7_support_resistance_source=(synthetic_runtime_sources if synthetic_runtime_sources is not None else getattr(bootstrap.bundle, "track7_support_resistance_source", None)),
        risk_guard_status_source=(risk_guard_status_source if risk_guard_status_source is not None else synthetic_runtime_sources),
        track3_runtime_input_source=track3_source,
        track6_option_contract_source=Track6OptionContractSource(bootstrap.bundle.option_master),
        track6_first_rank=(validation_only_track6_lifecycle_config.first_rank
                           if validation_only_track6_lifecycle_config is not None else None),
        track7_option_contract_source=Track7OptionContractSource(bootstrap.bundle.option_master),
        track8_option_contract_source=Track8OptionContractSource(bootstrap.bundle.option_master),
        validation_only_s8_runtime_adapter=validation_only_s8_runtime_adapter,
        track9_option_contract_source=track9_option_contract_source,
        kospi200_daily_source=kospi200_daily_source,
        track6_volatility_source=track6_volatility_source,
        track1_fence_type_source=track1_fence_type_source,
        track1_position_lot_store=multi_leg_bridge.position_lot_store,
        track1_option_delta_source=historical_observation_option_source,
        strategy_keys=tuple(
            key[0] if isinstance(key, tuple) else str(key)
            for key in selected_keys
        ),
    )
    if synthetic_runtime_sources is not None:
        provider.track9_event_source = synthetic_runtime_sources
        from environments.high_speed.synthetic_runtime_sources import SyntheticEventRiskSource
        provider.track9_event_risk_source = SyntheticEventRiskSource(synthetic_runtime_sources)

    provider.track9_position_execution_source = VirtualTrack9PositionExecutionReadModel(multi_leg_bridge)
    provider.track2_market_observation_sink = track2_market_observation_sink

    execution_resolvers = ExecutionMultiLegResolverRegistry(
        registry.definitions_by_strategy_id(selected_keys)
    )

    def resolve_track2(evaluation, canonical):
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is not None and str(getattr(proposal, "tag_id", "")).upper() == "TRAP_CLOSE":
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track2_asymmetric_trap",
                purpose="TRAP_CLOSE",
            )
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
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is not None and str(getattr(proposal, "tag_id", "")).upper() == "CLOSE_STAT_ARB":
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="Strategy_3_StatArb",
                purpose="CLOSE_STAT_ARB",
            )
        group_id = f"{run_id}-{canonical.signal_id}"
        observed_symbol = str(
            getattr(canonical, "instrument_id", None)
            or getattr(canonical, "symbol", None)
            or ""
        ).strip()
        if not observed_symbol:
            raise ValueError("TRACK3_WS_FUTURES_SYMBOL_REQUIRED")
        if synthetic_runtime_sources is not None:
            market_tick = next(iter(evaluation.context.market_state.ticks.values()))
            observed_identity = identity(evaluation, market_tick)
            class _SyntheticHedgeIdentitySource:
                def current_identity(self):
                    return observed_identity
                def identity_for_observed_symbol(self, _symbol):
                    return observed_identity
            hedge_source = _SyntheticHedgeIdentitySource()
        else:
            if futures_identity_source is None:
                raise ValueError("TRACK3_HEDGE_IDENTITY_SOURCE_REQUIRED")
            hedge_source = Track3HedgeIdentitySource(futures_identity_source)
            observed_identity = hedge_source.identity_for_observed_symbol(observed_symbol)
        return track3_plan_adapter.build_plan(
            strategy_id="Strategy_3_StatArb", group_id=group_id,
            side=canonical.side.value, quantity=canonical.qty,
            identity=observed_identity,
            hedge_identity_source=hedge_source,
        )

    def futures_identity_for_evaluation(evaluation):
        if synthetic_runtime_sources is not None:
            market_state = evaluation.context.market_state
            if market_state is None or not market_state.ticks:
                raise ValueError("FUTURES_MARKET_TICK_REQUIRED")
            observed_identity = identity(evaluation, next(iter(market_state.ticks.values())), asset_type="FUTURES")
            if not isinstance(observed_identity, FuturesInstrumentIdentity):
                raise ValueError("FUTURES_AUTHORITATIVE_IDENTITY_REQUIRED")
            return observed_identity
        return require_futures_identity(futures_identity_source)

    def build_futures_single_leg_plan(strategy_id, evaluation, canonical, *, group_id, purpose):
        instrument_identity = futures_identity_for_evaluation(evaluation)
        return MultiLegExecutionPlan(
            group_id=group_id,
            strategy_id=strategy_id,
            purpose=purpose,
            legs=(ExecutionLeg(
                leg_id=f"futures-{str(getattr(canonical, 'tag_id', '') or purpose).lower()}",
                side=canonical.side.value,
                quantity=int(canonical.qty),
                position_role="NONE",
                instrument_identity=instrument_identity,
            ),),
        )

    def resolve_track1(evaluation, canonical):
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is None or str(getattr(proposal, "asset_type", "")).upper() != "FUTURES":
            return None
        tag = str(getattr(proposal, "tag_id", "") or "").upper()
        if tag == "FUTURES_UNWIND":
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="TRACK1_TAIL_DEFENSE",
                purpose="FUTURES_UNWIND",
            )
        return build_futures_single_leg_plan(
            "TRACK1_TAIL_DEFENSE", evaluation, canonical,
            group_id=f"{run_id}-TRACK1_TAIL_DEFENSE-FUTURES-HEDGE",
            purpose=tag or "FUTURES_HEDGE",
        )

    def resolve_track4(evaluation, canonical):
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is None or str(getattr(proposal, "asset_type", "")).upper() != "FUTURES":
            return None
        tag = str(getattr(proposal, "tag_id", "") or "").upper()
        if tag in {"UNWIND_FUT_HEDGE", "PROFIT_TAKEN_TRAILING_STOP"}:
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track4_gamma_scalping",
                purpose=tag,
            )
        return build_futures_single_leg_plan(
            "track4_gamma_scalping", evaluation, canonical,
            group_id=f"{run_id}-track4_gamma_scalping-FUTURES-HEDGE",
            purpose=tag or "GAMMA_REBALANCE",
        )

    def resolve_track6(evaluation, canonical):
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is not None and str(getattr(proposal, "side", "")).upper() == "SELL":
            tag = str(getattr(proposal, "tag_id", "") or "DAILY_TAIL_INSURANCE_CLOSE")
            close_scope = {}
            if tag in {"DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT", "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL"}:
                close_scope = {
                    "option_type": str(getattr(proposal, "option_type", "") or ""),
                    "strike": Decimal(str(getattr(proposal, "strike"))),
                }
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track6_daily_tail_insurance",
                purpose=tag,
                asset_type="OPTION",
                **close_scope,
            )
        direction = str(getattr(evaluation.result, "direction", ""))
        if direction not in {"BUY_INSURANCE", "BUY_INSURANCE_OPPOSITE"}:
            return None
        strategy = registry.get("track6_daily_tail_insurance", "1.0")
        if strategy.sequential_lifecycle_enabled:
            group_id = f"{run_id}-track6-{strategy.state.bought_date or evaluation.context.analytics.as_of.strftime('%Y%m%d')}"
            return strategy.build_sequential_execution_plan(
                group_id, now=evaluation.context.analytics.as_of,
                client_order_id_factory=multi_leg_bridge._client_order_id,
            )
        return strategy.build_execution_plan(f"{run_id}-{canonical.signal_id}")

    def resolve_track7(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise ValueError("TRACK7_EXECUTION_PROPOSAL_REQUIRED")
        if str(getattr(proposal, "side", "")).upper() == "SELL":
            strategy = registry.get("track7_volatility_skew_weekly_insurance", "1.0")
            strategy.mark_exit_pending()
            tag = str(getattr(proposal, "tag_id", "") or "")
            if tag in {"WEEKLY_INSURANCE_CLOSE_PUT", "WEEKLY_INSURANCE_CLOSE_CALL"}:
                return multi_leg_bridge.build_close_plan_from_open_lots(
                    strategy_id="track7_volatility_skew_weekly_insurance",
                    purpose=tag,
                    asset_type="OPTION",
                    option_type=str(getattr(proposal, "option_type", "") or ""),
                    strike=Decimal(str(getattr(proposal, "strike"))),
                    expiry=strategy.state.expiry,
                )
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track7_volatility_skew_weekly_insurance",
                purpose="WEEKLY_INSURANCE_CLOSE",
            )
        strategy = registry.get("track7_volatility_skew_weekly_insurance", "1.0")
        if not isinstance(strategy, Track7VolatilitySkewWeeklyInsurance):
            raise ValueError("TRACK7_STRATEGY_REGISTRY_TYPE_REQUIRED")
        return strategy.build_execution_plan(f"{run_id}-{canonical.signal_id}", proposal=proposal)

    def resolve_track8(evaluation, canonical):
        proposal = getattr(evaluation.result, "execution_proposal", None)
        if proposal is not None and str(getattr(proposal, "side", "")).upper() == "SELL":
            strategy = registry.get("track8_macro_regime_monthly_strangle", "2.0")
            tag = str(getattr(proposal, "tag_id", "") or "")
            if tag in {"MONTHLY_STRANGLE_CLOSE_CALL", "MONTHLY_STRANGLE_CLOSE_PUT"}:
                return multi_leg_bridge.build_close_plan_from_open_lots(
                    strategy_id="track8_macro_regime_monthly_strangle",
                    purpose=tag,
                    asset_type="OPTION",
                    option_type=str(getattr(proposal, "option_type", "") or ""),
                    strike=Decimal(str(getattr(proposal, "strike"))),
                    expiry=strategy.state.expiry,
                )
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track8_macro_regime_monthly_strangle",
                purpose="MONTHLY_STRANGLE_CLOSE",
            )
        strategy = registry.get("track8_macro_regime_monthly_strangle", "2.0")
        return strategy.build_execution_plan(
            f"{run_id}-{canonical.signal_id}", proposal=proposal
        )

    def resolve_track5(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise ValueError("TRACK5_EXECUTION_PROPOSAL_REQUIRED")
        strategy = registry.get("track5_gap_divergence", "2.0")
        if not isinstance(strategy, Track5GapDivergence):
            raise ValueError("TRACK5_STRATEGY_REGISTRY_TYPE_REQUIRED")
        tag = str(getattr(proposal, "tag_id", "") or "").upper()
        if str(getattr(proposal, "asset_type", "")).upper() == "FUTURES":
            if tag == "GAP_DIVERGENCE_FUTURES_FIRST_EXIT":
                return multi_leg_bridge.build_close_plan_from_open_lots(
                    strategy_id="track5_gap_divergence",
                    purpose="TRACK5_GAP_HEDGE_FUTURES_EXIT",
                    asset_type="FUTURES", leg_id_prefix="MINI_FUTURES_EXIT",
                )
            if tag == "GAP_DIVERGENCE_TERMINAL_EXIT":
                return multi_leg_bridge.build_close_plan_from_open_lots(
                    strategy_id="track5_gap_divergence",
                    purpose="TRACK5_GAP_HEDGE_TERMINAL_EXIT",
                )
        if str(getattr(proposal, "asset_type", "")).upper() == "OPTION" and str(getattr(proposal, "side", "")).upper() == "SELL":
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track5_gap_divergence",
                purpose="TRACK5_GAP_HEDGE_OPTION_EXIT",
                asset_type="OPTION", leg_id_prefix="OPTION_EXIT",
            )
        if str(getattr(proposal, "asset_type", "")).upper() == "OPTION" and str(getattr(proposal, "side", "")).upper() == "BUY":
            return strategy.build_execution_plan(
                f"{run_id}-{canonical.signal_id}",
                proposal=proposal,
            )
        futures_identity = futures_identity_for_evaluation(evaluation)
        return strategy.build_execution_plan(
            f"{run_id}-{canonical.signal_id}",
            proposal=proposal,
            futures_identity=futures_identity,
        )

    def resolve_track9(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise ValueError("TRACK9_EXECUTION_PROPOSAL_REQUIRED")
        if str(getattr(proposal, "side", "")).upper() == "SELL":
            strategy = registry.get("track9_event_overnight_insurance", "3.0")
            strategy.mark_exit_pending()
            return multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id="track9_event_overnight_insurance",
                purpose="OVERNIGHT_INSURANCE_CLOSE",
            )
        strategy = registry.get("track9_event_overnight_insurance", "3.0")
        return strategy.build_execution_plan(
            f"{run_id}-{canonical.signal_id}", proposal=proposal
        )

    execution_resolvers.register("TRACK1_TAIL_DEFENSE", resolve_track1)
    execution_resolvers.register("track2_asymmetric_trap", resolve_track2)
    execution_resolvers.register("track4_gamma_scalping", resolve_track4)
    execution_resolvers.register("track5_gap_divergence", resolve_track5)
    execution_resolvers.register("Strategy_3_StatArb", resolve_track3)
    execution_resolvers.register("track6_daily_tail_insurance", resolve_track6)
    execution_resolvers.register("track7_volatility_skew_weekly_insurance", resolve_track7)
    execution_resolvers.register("track8_macro_regime_monthly_strangle", resolve_track8)
    execution_resolvers.register("track9_event_overnight_insurance", resolve_track9)

    def multi_leg_plan_resolver(evaluation, canonical):
        strategy_id = str(getattr(evaluation.context, "strategy_id", "") or "")
        return execution_resolvers.resolve(strategy_id, evaluation, canonical)

    def process_pending_multi_leg(tick=None):
        strategy = registry.get("track6_daily_tail_insurance", "1.0")
        if strategy.sequential_lifecycle_enabled and strategy.lifecycle is not None and tick is not None:
            now = datetime.fromisoformat(str(tick.timestamp))
            action = strategy.lifecycle_clock_action(now)
            if action is not None and action.kind in {"CANCEL", "CANCEL_AND_RECONCILE"} and action.client_order_id:
                multi_leg_bridge.cancel_pending_order(action.client_order_id)
        return multi_leg_bridge.process_pending_quotes()

    loop = AutomatedVirtualTradingLoop(
        bundle=bootstrap.bundle,
        strategy_hub=strategy_hub,
        run_id=run_id,
        fee_ledger=fee_ledger,
        context_builder=context_builder,
        identity_provider=identity,
        multi_leg_plan_resolver=multi_leg_plan_resolver,
        multi_leg_executor=multi_leg_bridge.execute,
        pending_multi_leg_processor=process_pending_multi_leg,
        risk_guard_status_source=(risk_guard_status_source or synthetic_runtime_sources),
        signal_observation_only=validation_only_track6_signal_mode,
    )
    loop.track6_validation_gate_evidence = track6_validation_gate_evidence
    bootstrap.bundle.market.subscribe(loop.on_tick)
    subscribe_quote_only = getattr(bootstrap.bundle.market, "subscribe_quote_only", None)
    if callable(subscribe_quote_only):
        subscribe_quote_only(loop.on_quote_only_tick)
    loop.track2_market_observation_sink = track2_market_observation_sink
    # Expose the actual execution bridge used by the loop so Run/Control Tower
    # read models observe the same PositionGroup/ExecutionReport registry.
    loop.multi_leg_bridge = multi_leg_bridge
    return loop
