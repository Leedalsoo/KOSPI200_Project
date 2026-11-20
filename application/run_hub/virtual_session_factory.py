from __future__ import annotations
from contracts.trading_date import parse_trading_date

import hashlib
import os
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Any

from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.control_tower_hub import ControlTowerHub
from application.option_program_read_model import OptionProgramReadModel
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.hub import EnvironmentHub
from application.run_hub.contracts import RunContext
from application.run_hub.hub import RunSession
from application.runtime_hub.hub import RuntimeHub
from application.runtime_controller.controller import RuntimeController
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.types import EnvironmentType
from contracts.risk_guard import RiskGuardStatusSource
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from core.risk.risk_guard import RiskGuard
from application.composition.validation_only_runtime_auto_stop_switch import (
    SqliteRuntimeStopSwitchStateStore,
    ValidationOnlyRuntimeAutoStopSwitch,
)
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource
from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource
from infrastructure.kis.historical_futures_observation_replay import HistoricalFuturesObservationReplay
from infrastructure.kis.historical_index_price_observation_replay import HistoricalIndexPriceObservationReplay
from infrastructure.kis.track3_runtime_input_source import KISTrack3RuntimeInputSource
from application.composition.track7_support_resistance_source import Track7AuthoritativeSupportResistanceSource
from application.composition.market_calendar_hub import MarketCalendarHub
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from interfaces.control_tower.virtual_test_controller import VirtualTestController
from application.composition.virtual_risk_guard_status_source import VirtualRiskGuardStatusSource


def attach_validation_only_s2_quote_only_replay(loop, bundle, evidence_chain):
    """Attach four manifest-bound no-trade S2 quote events to an isolated Virtual loop."""
    loop.runtime_evidence_supervisor = evidence_chain.supervisor
    loop.validation_only_s2_evidence_chain = evidence_chain
    bundle.market.set_authoritative_option_quote_provider(
        evidence_chain.alternative_provider.option_quotes_at
    )
    candidate_ticks = evidence_chain.alternative_provider.build_quote_only_ticks()
    expected_event_keys = tuple(
        (tick.timestamp, tick.seq_id, tick.instrument_id, tick.leg_role)
        for tick in candidate_ticks
    )
    if (
        len(candidate_ticks) != 4
        or len({tick.timestamp for tick in candidate_ticks}) != 1
        or len({tick.seq_id for tick in candidate_ticks}) != 4
        or len({tick.instrument_id for tick in candidate_ticks}) != 4
        or len({tick.leg_role for tick in candidate_ticks}) != 4
    ):
        raise ValueError("T10_S2_QUOTE_ONLY_CANDIDATE_SET_OR_TIME_ALIGNMENT_INVALID")
    candidate_tick = candidate_ticks[0]
    loop.validation_only_s2_candidate_ticks = candidate_ticks
    loop.validation_only_s2_candidate_tick = candidate_tick

    def replay_validation_only_s2_candidate():
        before = len(loop.quote_only_events)
        for tick in candidate_ticks:
            bundle.market.publish_replay_tick(tick)
        events = tuple(loop.quote_only_events[before:])
        if len(events) != len(expected_event_keys):
            raise ValueError("T10_S2_QUOTE_ONLY_REPLAY_EVENT_COUNT_MISMATCH")
        actual_event_keys = tuple(
            (event.get("timestamp"), event.get("seq_id"), event.get("instrument_id"), event.get("leg_role"))
            for event in events
        )
        if actual_event_keys != expected_event_keys:
            raise ValueError("T10_S2_QUOTE_ONLY_REPLAY_EVENT_IDENTITY_OR_ORDER_MISMATCH")
        return events

    loop.replay_validation_only_s2_candidate = replay_validation_only_s2_candidate
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )
    loop.validation_only_u21_quote_policy_adapter = ValidationOnlyU21QuotePolicyAdapter(
        evidence_chain.alternative_provider,
    )
    loop.validation_only_s2_replay = True
    loop.signal_observation_only = True
    return candidate_tick


def create_virtual_run_session(
    context: RunContext,
    option_master: Any,
    risk_guard_status_source: RiskGuardStatusSource | None = None,
    track4_greeks_source: KISTrack4GreeksRealtimeSource | None = None,
    runtime_evidence_supervisor=None,
    *,
    validation_only_s2_replay: bool = False,
    validation_only_s2_original_source_root: str | Path | None = None,
    validation_only_s2_notion_decision_refs: tuple[str, ...] = (
        "No.1534", "No.1535", "No.1538", "No.1554", "No.1555",
    ),
) -> RunSession:
    if validation_only_s2_replay:
        if str(context.environment).upper() != "VIRTUAL":
            raise ValueError("T10_S2_REPLAY_VIRTUAL_ENVIRONMENT_REQUIRED")
        if str(context.scenario or "").upper() != "CALM":
            raise ValueError("T10_S2_REPLAY_CALM_SCENARIO_REQUIRED")
        if runtime_evidence_supervisor is not None:
            raise ValueError("T10_S2_REPLAY_SUPERVISOR_IS_FACTORY_MANAGED")
        if option_master is not None:
            raise ValueError("T10_S2_REPLAY_EXTERNAL_OPTION_MASTER_FORBIDDEN")
        if context.historical_store_path is not None:
            raise ValueError("T10_S2_REPLAY_USES_PINNED_SCENARIO_TICK_ONLY")
        if context.strategy_keys:
            raise ValueError("T10_S2_REPLAY_STRATEGIES_MUST_BE_EMPTY")
        if validation_only_s2_original_source_root is None:
            raise ValueError("T10_S2_REPLAY_ORIGINAL_SOURCE_ROOT_REQUIRED")
        if not Path(validation_only_s2_original_source_root).is_dir():
            raise ValueError("T10_S2_REPLAY_ORIGINAL_SOURCE_ROOT_NOT_FOUND")
    elif validation_only_s2_original_source_root is not None:
        raise ValueError("T10_S2_SOURCE_ROOT_REQUIRES_EXPLICIT_REPLAY_MODE")
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=option_master,
        contract_mappings={},
        initial_capital=float(context.initial_capital or 250_000_000.0),
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name=f"run_{context.run_id}")
    # Virtual automated replay uses the established Track7 5-second limit;
    # generic RuntimePolicy remains neutral for other environments.
    policy = RuntimePolicy(track7_order_timeout_seconds=5.0)
    holder: dict[str, Any] = {}
    def build(_config: EnvironmentConfig, _policy: RuntimePolicy):
        bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(_config, _policy)
        holder["bundle"] = bundle
        return bundle
    environment_hub = EnvironmentHub(EnvironmentFactory(virtual_builder=build))
    controller = RuntimeController(environment_hub)
    controller.start(config, policy)
    virtual_risk_guard = risk_guard_status_source or VirtualRiskGuardStatusSource(controller)
    bundle = environment_hub.active
    if bundle is None:
        raise RuntimeError("VIRTUAL_RUN_ENVIRONMENT_NOT_ACTIVE")
    if context.historical_store_path:
        historical_path = Path(context.historical_store_path)
        if historical_path.is_file():
            from environments.virtual.market.historical_market_store import HistoricalMarketStore
            if historical_path.name.endswith(".observations.jsonl"):
                base_path = Path(str(historical_path)[: -len(".observations.jsonl")])
                store = HistoricalMarketStore(base_path)
                bundle.market.load_historical_observation_store(store, source=context.historical_source)
            else:
                store = HistoricalMarketStore(historical_path)
                bundle.market.load_historical_store(store, source=context.historical_source)
    historical_observation_option_source = None
    if context.historical_store_path and Path(context.historical_store_path).name.endswith(".observations.jsonl"):
        base_path = Path(str(context.historical_store_path)[: -len(".observations.jsonl")])
        from environments.virtual.market.historical_market_store import HistoricalMarketStore
        historical_observation_option_source = HistoricalObservationOptionSource(HistoricalMarketStore(base_path).load_observations())
        bundle.market.set_authoritative_option_quote_provider(
            historical_observation_option_source.latest_authoritative_option_quotes
        )

    market_calendar_hub = MarketCalendarHub(getattr(bundle.option_master, "calendar", None))
    if context.historical_daily_store_path:
        daily_path = Path(context.historical_daily_store_path)
        if daily_path.is_file():
            from contracts.historical_daily_store import HistoricalDailyStore
            from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider
            from application.composition.track7_classic_pivot_provider import Track7ClassicPivotProvider
            daily_store = HistoricalDailyStore(daily_path)
            calendar = getattr(bundle.option_master, "calendar", None)
            if calendar is not None:
                bundle.track7_support_resistance_source = Track7AuthoritativeSupportResistanceSource(
                    Track7ClassicPivotProvider(HistoricalMarketDailyOHLCProvider(daily_store, market_calendar_hub))
                )
    if context.scenario:
        scenario_engine = getattr(bundle.market, "scenario", None)
        if scenario_engine is not None:
            scenario_engine.set_scenario(context.scenario)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    risk_engine = RiskEngine(config=RiskConfig(), margin_engine=vssf.margin_engine)
    stop_state_root = Path(
        os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    ) / "KOSPI200_Project" / "validation_only_runtime_stop_switch"
    run_key = hashlib.sha256(context.run_id.encode("utf-8")).hexdigest()
    runtime_stop_switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=RiskGuard(),
        risk_engine=risk_engine,
        state_store=SqliteRuntimeStopSwitchStateStore(stop_state_root / f"{run_key}.sqlite3"),
    )
    strategy_hub = None
    track3_replay_source = None
    if historical_observation_option_source is not None:
        from environments.virtual.market.historical_market_store import HistoricalMarketStore
        base_path = Path(str(context.historical_store_path)[: -len(".observations.jsonl")])
        track3_replay_source = KISTrack3RuntimeInputSource(
            initial_options=HistoricalMarketStore(base_path).load_observations(),
        )
    loop = attach_standard_automated_loop(
        type("Bootstrap", (), {"bundle": bundle})(),
        strategy_keys=context.strategy_keys,
        track9_iv_history_path=context.track9_iv_history_path,
        run_id=context.run_id,
        historical_observation_option_source=historical_observation_option_source,
        risk_guard_status_source=virtual_risk_guard,
        risk_engine=risk_engine,
        validation_only_runtime_stop_switch=runtime_stop_switch,
        runtime_evidence_supervisor=runtime_evidence_supervisor,
        market_calendar_hub=market_calendar_hub,
        track4_greeks_provider=track4_greeks_source,
        track3_runtime_input_source=track3_replay_source,
    )
    strategy_hub = loop.strategy_hub
    loop.runtime_stop_state_path = stop_state_root / f"{run_key}.sqlite3"
    execution_bridge = loop.multi_leg_bridge
    validation_only_s2_evidence_chain = None
    if validation_only_s2_replay:
        from application.composition.validation_only_s2_source_evidence_providers import (
            build_validation_only_s2_runtime_evidence_chain,
        )

        vssf_runtime = bundle.execution._authoritative_execute.__self__.vssf_runtime
        u19_state_root = stop_state_root.parent / "validation_only_runtime_u19_recovery"
        validation_only_s2_evidence_chain = build_validation_only_s2_runtime_evidence_chain(
            project_root=Path(__file__).resolve().parents[2],
            original_source_root=validation_only_s2_original_source_root,
            run_id=context.run_id,
            bridge=execution_bridge,
            vssf_runtime=vssf_runtime,
            stop_switch=runtime_stop_switch,
            risk_guard_status_source=virtual_risk_guard,
            u19_state_store_path=u19_state_root / f"{run_key}.sqlite3",
            notion_decision_refs=validation_only_s2_notion_decision_refs,
        )
        if validation_only_s2_evidence_chain.supervisor.stop_switch is not runtime_stop_switch:
            raise ValueError("T10_S2_SUPERVISOR_X2_INSTANCE_MISMATCH")
        attach_validation_only_s2_quote_only_replay(
            loop,
            bundle,
            validation_only_s2_evidence_chain,
        )
    bundle.broker_api.attach_group_read_model(
        snapshot_reader=execution_bridge.position_groups.snapshot,
        reports_reader=execution_bridge.group_reports,
        group_ids_reader=lambda: tuple(execution_bridge.position_groups.all().keys()),
        group_reader=execution_bridge.position_groups.get,
    )
    raw_futures_path = None
    if context.historical_store_path and Path(context.historical_store_path).name.endswith(".observations.jsonl"):
        base_path = Path(str(context.historical_store_path)[: -len(".observations.jsonl")])
        candidate = base_path.parent / "kis_vts_websocket_raw.jsonl"
        if candidate.is_file():
            raw_futures_path = candidate
    if raw_futures_path is not None and loop.track2_market_observation_sink is not None:
        session_partition = Path(context.historical_store_path).parent.name
        loop.track2_market_observation_sink.session_date = parse_trading_date(session_partition)
        futures_replay = HistoricalFuturesObservationReplay(raw_futures_path)
        index_replay = HistoricalIndexPriceObservationReplay(raw_futures_path)
        bundle.market.set_futures_observation_replay(futures_replay)
        bundle.market.set_index_price_observation_replay(index_replay)
        bundle.market.subscribe_futures_observation(loop.track2_market_observation_sink.on_observation)
        bundle.market.subscribe_index_price_observation(loop.track2_market_observation_sink.basis_source.update_index)
        if track3_replay_source is not None:
            bundle.market.subscribe_futures_observation(
                lambda observation: track3_replay_source.update_futures(observation, session_date=loop.track2_market_observation_sink.session_date)
            )
            bundle.market.subscribe_index_price_observation(track3_replay_source.update_index)
    runtime_hub = RuntimeHub(loop)
    option_program_read_model = OptionProgramReadModel(
        runtime_controller=controller,
        runtime_hub=runtime_hub,
        strategy_hub=strategy_hub,
        bundle=bundle,
        context=context,
    )
    adapter = ControlTowerUIAdapter(
        runtime_controller=controller,
        broker_api=bundle.broker_api,
        option_program_read_model=option_program_read_model,
    )
    virtual_test_controller = VirtualTestController(market=bundle.market, tick_handler=runtime_hub.on_tick)
    tower = ControlTowerHub(
        runtime_controller=controller,
        ui_adapter=adapter,
        strategy_hub=strategy_hub,
        run_context=context,
        virtual_test_controller=virtual_test_controller,
    )
    return RunSession(
        context=context,
        runtime_controller=controller,
        bundle=bundle,
        strategy_hub=strategy_hub,
        runtime_hub=runtime_hub,
        ui_adapter=adapter,
        control_tower_hub=tower,
    )
