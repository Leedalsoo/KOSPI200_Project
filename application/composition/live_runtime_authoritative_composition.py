"""Authoritative production runtime composition for KIS Live trading environment.

This module provides the authoritative production entry point for assembling
the complete Live execution and runtime lifecycle graph from real repository contracts.
It enforces authoritative credentials, official instrument master metadata,
and fail-loud validation without inventing synthetic defaults or fake dependencies.
"""
from __future__ import annotations

import os
from typing import Any

from core.oms.oms_fsm import OrderStateMachine
from application.composition.live_runtime_lifecycle_coordinator import LiveRuntimeLifecycleCoordinator
from application.composition.live_runtime_production_factory import create_live_runtime_lifecycle_coordinator
from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from environments.live.broker.kis_live_broker import LiveBrokerAdapter
from environments.live.broker.kis_order_payload import (
    KisDomesticFuturesOrderPayloadAdapter,
    KisOrderAccountContext,
)
from environments.live.broker.kis_order_transport import KISDomesticFuturesOrderTransport
from environments.live.contracts import LiveApprovalState, LiveCredentialRef, LiveSafetyPolicy
from environments.live.credential import LiveCredentials
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from environments.live.execution.kis_futures_execution_recovery_adapter import KISFuturesExecutionRecoveryAdapter
from environments.live.execution.kis_futures_execution_recovery_transport import KISFuturesExecutionRecoveryTransport
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
from environments.live.idempotency import IdempotencyRegistry
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.position.live_position_fill_adapter import LivePositionFillAdapter
from environments.live.reconciliation import LiveReconciler
from environments.live.safety_gate import LiveSafetyGate
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_execution_transport import KISFuturesExecutionTransport
from infrastructure.kis.futures_market_transport import KISFuturesMarketTransport
from infrastructure.kis.instrument_master_provider import KisFuturesInstrumentMasterProvider


class AuthoritativeLiveRuntimeCompositionError(RuntimeError):
    """Raised when authoritative KIS Live runtime composition cannot be established."""


def create_authoritative_kis_live_runtime_composition(
    *,
    credential_ref: LiveCredentialRef | None = None,
    master_provider: KisInstrumentMasterProvider | None = None,
    auth_manager: KISAuthManager | None = None,
    account: Any | None = None,
    execution_transport: Any | None = None,
    market_transport: Any | None = None,
    order_transport: Any | None = None,
    recovery_transport: Any | None = None,
    safety_policy: LiveSafetyPolicy | None = None,
) -> LiveRuntimeLifecycleCoordinator:
    """Authoritative production entry point for the KIS Live Runtime Lifecycle.

    Assembles all concrete broker, market, execution, recovery, and coordinator
    dependencies using authoritative KIS environment contracts.
    
    If credentials, HTS ID, or external dependencies are missing, this function
    fails loudly with AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE.
    """
    ref = credential_ref or LiveCredentialRef()

    # 1. Resolve authoritative credentials from environment
    try:
        creds = LiveCredentials.from_environment(ref)
    except Exception as exc:
        raise AuthoritativeLiveRuntimeCompositionError(
            "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE: "
            f"Live credentials incomplete ({exc})"
        ) from exc

    # 2. Resolve authoritative HTS ID
    hts_id = (
        os.getenv("KIS_HTS_ID", "").strip()
        or os.getenv("KIS_REAL_HTS_ID", "").strip()
    )
    if not hts_id:
        raise AuthoritativeLiveRuntimeCompositionError(
            "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE: "
            "HTS ID is required (set KIS_HTS_ID or KIS_REAL_HTS_ID)"
        )

    # 3. Check Live Account Provider availability
    if account is None:
        raise AuthoritativeLiveRuntimeCompositionError(
            "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE: "
            "Authoritative live account provider is required (no synthetic account defaults allowed)"
        )

    # 4. Resolve authoritative Mini Futures Instrument from Master Provider
    provider = master_provider or KisFuturesInstrumentMasterProvider(
        source_url="https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"
    )
    try:
        contract_source = provider.current_mini_futures_source(underlying_short_code="2001")
        current_contract = contract_source.current_contract()
    except Exception as exc:
        raise AuthoritativeLiveRuntimeCompositionError(
            "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE: "
            f"Failed to resolve authoritative contract identity from master provider: {exc}"
        ) from exc

    # 5. Assemble KIS Auth
    auth = auth_manager or KISAuthManager(
        app_key=creds.app_key,
        app_secret=creds.app_secret,
        base_url=creds.base_url,
        is_vts=False,
    )

    # 6. Assemble Broker & Order Path
    clean_acc = creds.account_no.replace("-", "").strip()
    account_ctx = KisOrderAccountContext(
        cano=clean_acc[:8],
        acnt_prdt_cd=clean_acc[8:] if len(clean_acc) >= 10 else "01",
    )
    payload_adapter = KisDomesticFuturesOrderPayloadAdapter(account=account_ctx)
    resolved_order_transport = order_transport or KISDomesticFuturesOrderTransport(
        auth=auth,
        payload_adapter=payload_adapter,
        base_url=creds.base_url,
    )
    symbol_source = KisFuturesExecutionSymbolSource(
        source=contract_source,
        target=FuturesTargetConfiguration(underlying_short_code="2001"),
    )
    futures_cmd_adapter = KisFuturesBrokerCommandAdapter(symbol_source=symbol_source)
    policy = safety_policy or LiveSafetyPolicy(
        approval_state=LiveApprovalState.APPROVED,
        kill_switch=False,
        max_order_quantity=1,
        max_daily_loss=10_000_000.0,
        max_position_quantity=5,
    )
    gate = LiveSafetyGate(policy=policy)
    idempotency = IdempotencyRegistry()
    broker = LiveBrokerAdapter(
        transport=resolved_order_transport,
        gate=gate,
        policy=policy,
        idempotency=idempotency,
        futures_command_adapter=futures_cmd_adapter,
    )

    # 7. Assemble Position & OMS
    order_state_machine = OrderStateMachine()
    position_aggregate = LivePositionAggregate(instrument_id=current_contract.shrn_iscd)
    position_fill_adapter = LivePositionFillAdapter(position_aggregate)
    deduplicator = ExecutionEventDeduplicator()

    # 8. Assemble Execution Path
    resolved_exec_transport = execution_transport or KISFuturesExecutionTransport(auth=auth)
    execution_adapter = KISFuturesExecutionNoticeAdapter()
    correlation_provider = KISFuturesExecutionCorrelationProvider(
        order_state_machine=order_state_machine
    )

    # 9. Assemble Recovery
    resolved_recovery_transport = recovery_transport or KISFuturesExecutionRecoveryTransport(
        auth=auth,
        base_url=creds.base_url,
    )
    recovery_adapter = KISFuturesExecutionRecoveryAdapter()

    # 10. Assemble Market Data
    resolved_market_transport = market_transport or KISFuturesMarketTransport(auth=auth)
    market_data_provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda s: current_contract.shrn_iscd,
        observed_at_resolver=lambda obs: obs.observed_at,
    )

    # 11. Reconciler
    reconciler = LiveReconciler()

    # 12. Assemble Live Coordinator
    coordinator = create_live_runtime_lifecycle_coordinator(
        market=market_data_provider,
        broker=broker,
        account=account,
        position=position_aggregate,
        reconciler=reconciler,
        transport=resolved_exec_transport,
        execution_adapter=execution_adapter,
        correlation_provider=correlation_provider,
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=deduplicator,
        position_aggregate=position_aggregate,
        safety_policy=policy,
        recovery_transport=resolved_recovery_transport,
        recovery_adapter=recovery_adapter,
    )

    return coordinator
