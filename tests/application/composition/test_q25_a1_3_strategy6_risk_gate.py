from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext,
    route_from_runtime_authoritative_sources,
)
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOptionType,
    CanonicalOrderCommand,
    CanonicalOrderSide,
)


class _MarginEngine:
    def __init__(self, required_margin: Decimal = Decimal("1000")) -> None:
        self.required_margin = required_margin

    def calculate_order_margin(self, command) -> float:
        return float(self.required_margin * command.qty)


class _RiskGuard:
    def __init__(self, allowed: bool | None = True) -> None:
        self.allowed = allowed

    def snapshot(self):
        if self.allowed is None:
            return None
        return RiskGuardStatusSnapshot(
            observed_at=datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc),
            admission_allowed=self.allowed,
            kill_switch_engaged=not self.allowed,
            health_level=SensorLevel.GREEN if self.allowed else SensorLevel.BLOCKED,
            reason="TEST_ALLOWED" if self.allowed else "TEST_BLOCKED",
            decision_version="q25-a1-3-test-v1",
        )


class _PositionSource:
    def snapshot(self):
        return {}


class _RouterSpy:
    def __init__(self) -> None:
        self.calls = []

    def register_and_route(self, command, token, *, freshness_verdict=None):
        self.calls.append((command, token, freshness_verdict))


def _command(*, qty: int = 1) -> CanonicalOrderCommand:
    return CanonicalOrderCommand(
        client_order_id="q25-a1-3-s6-risk-gate-1",
        track_id="track6_daily_tail_insurance",
        asset_type=CanonicalAssetType.OPTION,
        side=CanonicalOrderSide.BUY,
        qty=qty,
        price=1.0,
        option_type=CanonicalOptionType.PUT,
        strike=500.0,
        symbol="SYNTHETIC-OPT-1",
        expiry="20261105",
        tag_id="S6_VALIDATION_ONLY",
        strategy_id="track6_daily_tail_insurance",
        instrument_id="SYNTHETIC-INSTRUMENT-1",
        contract_multiplier=250000.0,
        identity_source="SYNTHETIC_VALIDATION_ONLY",
    )


def _freshness(*, instrument_id: str = "SYNTHETIC-INSTRUMENT-1", symbol: str = "SYNTHETIC-OPT-1"):
    return FreshnessVerdict(
        status=FreshnessStatus.FRESH,
        reason="SYNTHETIC_VALIDATION_ONLY_NOT_PRODUCTION_EVIDENCE",
        policy_version="q25-a1-3-test-v1",
        environment="VIRTUAL",
        instrument_id=instrument_id,
        symbol=symbol,
    )


def _run(*, qty: int = 1, config: RiskConfig | None = None,
         guard_allowed: bool | None = True, freshness=None, free_margin: str = "100000"):
    router = _RouterSpy()
    engine = RiskEngine(
        config=config or RiskConfig(max_order_qty=50, max_position_per_instrument=10),
        margin_engine=_MarginEngine(),
    )
    gate = RiskGate(engine, risk_guard_status_source=_RiskGuard(guard_allowed))
    account = SimpleNamespace(balances={
        "cash": "1000000",
        "realized_pnl": "0",
        "margin_used": "0",
        "available_cash": free_margin,
    })
    context = RiskRouterContext(
        account_snapshot=account,
        position_source=_PositionSource(),
        order_router=router,
    )
    result = route_from_runtime_authoritative_sources(
        _command(qty=qty),
        risk_gate=gate,
        context=context,
        freshness_verdict=_freshness() if freshness is ... else freshness,
    )
    return result, router, gate


def test_strategy6_risk_gate_routes_only_after_real_riskengine_approval():
    result, router, gate = _run(freshness=...)

    assert result.approved is True
    assert result.routed is True
    assert result.decision == "ALLOW"
    assert gate.last_evaluation_result is not None
    assert gate.last_evaluation_result.token is not None
    assert len(router.calls) == 1
    assert router.calls[0][1] == gate.last_evaluation_result.token


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"qty": 51, "freshness": ...}, "EXCEEDED_MAX_ORDER_QTY"),
        ({"guard_allowed": False, "freshness": ...}, "RISK_GUARD_BLOCKED"),
        ({"guard_allowed": None, "freshness": ...}, "RISK_GUARD_STATUS_UNAVAILABLE"),
        ({"freshness": None}, "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED"),
        ({"freshness": _freshness(instrument_id="OTHER")}, "MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH"),
        ({"free_margin": "1", "freshness": ...}, "INSUFFICIENT_FREE_MARGIN"),
    ],
)
def test_strategy6_risk_gate_denial_never_routes(kwargs, reason):
    result, router, _gate = _run(**kwargs)

    assert result.approved is False
    assert result.routed is False
    assert result.rejection_reason is not None
    assert reason in result.rejection_reason
    assert router.calls == []


def test_strategy6_risk_gate_kill_switch_denies_without_routing():
    router = _RouterSpy()
    engine = RiskEngine(margin_engine=_MarginEngine())
    engine.trigger_kill_switch("TEST_ONLY")
    gate = RiskGate(engine, risk_guard_status_source=_RiskGuard(True))
    context = RiskRouterContext(
        account_snapshot=SimpleNamespace(balances={
            "cash": "1000000", "realized_pnl": "0", "margin_used": "0", "available_cash": "100000",
        }),
        position_source=_PositionSource(),
        order_router=router,
    )

    result = route_from_runtime_authoritative_sources(
        _command(), risk_gate=gate, context=context, freshness_verdict=_freshness(),
    )

    assert result.approved is False
    assert result.routed is False
    assert "REJECTED_BY_KILL_SWITCH" in (result.rejection_reason or "")
    assert router.calls == []
