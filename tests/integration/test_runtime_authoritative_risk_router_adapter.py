from dataclasses import dataclass

import pytest

from application.composition.runtime_authoritative_risk_router_adapter import (
RiskRouterContext,
route_from_runtime_authoritative_sources,
)
from core.position.position_aggregate import PositionAggregate
from shared.contracts.canonical import (
CanonicalAssetType,
CanonicalOrderCommand,
CanonicalOrderSide,
)


class PositionSource:
    def snapshot(self):
        return {"FUTURES:K200": PositionAggregate("BUY", 2, 350.0)}


class Account:
    total_balance = 1_000_000.0
    realized_pnl = 0.0
    used_margin = 0.0
    free_margin = 1_000_000.0


@dataclass
class Result:
    decision: str = "ALLOW"
    reduced_command: object = None
    rejection_reason: str | None = None


class Gate:
    def __init__(self, approved=True, token="TOKEN"):
        self.approved = approved
        self.token = token
        self.last_evaluation_result = Result("ALLOW" if approved else "DENY")

    def admit_order(self, *args):
        return self.approved, self.token, None


class Router:
    def __init__(self):
        self.calls = []

    def register_and_route(self, command, token):
        self.calls.append((command, token))
        return "ORDER"


def command():
    return CanonicalOrderCommand(
        client_order_id="ORD-1",
        track_id="TRACK4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=1,
        price=351.1,
        symbol="K200",
    )


def test_vssf_aggregate_style_source_reaches_risk_and_real_router_with_token():
    router = Router()
    result = route_from_runtime_authoritative_sources(
        command(),
        risk_gate=Gate(),
        context=RiskRouterContext(Account(), PositionSource(), router),
    )
# assert result.routed is True
    assert router.calls[0][0].client_order_id == "ORD-1"
    assert router.calls[0][1] == "TOKEN"


def test_deny_does_not_call_router():
    router = Router()
    result = route_from_runtime_authoritative_sources(
        command(),
        risk_gate=Gate(approved=False),
        context=RiskRouterContext(Account(), PositionSource(), router),
    )
# assert result.routed is False
    assert router.calls == []


def test_approved_without_token_fails_closed():
    with pytest.raises(RuntimeError, match="RISK_APPROVAL_TOKEN_REQUIRED"):
        route_from_runtime_authoritative_sources(
            command(),
            risk_gate=Gate(token=None),
            context=RiskRouterContext(Account(), PositionSource(), Router()),
        )
