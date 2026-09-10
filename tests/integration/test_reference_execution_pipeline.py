from dataclasses import dataclass, replace

import pytest

from core.runtime.reference_execution_pipeline import route_after_risk
from shared.contracts.canonical import (
CanonicalAssetType,
CanonicalOrderCommand,
CanonicalOrderSide,
CanonicalStrategySignal,
)


@dataclass
class FakeRiskResult:
    is_approved: bool
    decision: str
    rejection_reason: str | None = None
    reduced_command: object | None = None


class FakeGate:
    def __init__(self, result):
        self.result = result
        self.last_evaluation_result = None

    def admit_order(self, command, *_args, **_kwargs):
        self.last_evaluation_result = self.result
        if self.result.decision == "REDUCE":
            pass
            self.result.reduced_command = replace(command, qty=2)
        return self.result.is_approved, None, self.result.rejection_reason


class FakeRouter:
    def __init__(self):
        self.commands = []

    def register_and_route(self, command):
        self.commands.append(command)


def command(qty=4):
    return CanonicalOrderCommand(
        client_order_id="c1",
        track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=qty,
        price=100.0,
        symbol="KOSPI200F",
        tag_id="T",
    )


def test_allow_routes_original_effective_qty():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(True, "ALLOW")),
        account=object(),
        positions=object(),
        order_router=router,
    )
# assert out.routed is True
    assert out.decision == "ALLOW"
    assert router.commands[0].qty == 4


def test_reduce_routes_reduced_effective_qty():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(True, "REDUCE")),
        account=object(),
        positions=object(),
        order_router=router,
    )
# assert out.routed is True
    assert out.decision == "REDUCE"
    assert router.commands[0].qty == 2


def test_deny_fail_closed_without_router_call():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(False, "DENY", "NO")),
        account=object(),
        positions=object(),
        order_router=router,
    )
# assert out.routed is False
    assert router.commands == []
    assert out.rejection_reason == "NO"



from datetime import datetime
from decimal import Decimal

from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from core.runtime.reference_execution_pipeline import route_from_authoritative_sources


class PositionManager:
    positions = {
        "FUTURES:KOSPI200F": {
            "side": "BUY",
            "qty": 2,
            "avg_price": 100.0,
        }
    }


class MarginCalculator:
    def calculate_order_margin(self, command):
        return float(command.price) * int(command.qty)


def authoritative_account_snapshot():
    return AccountSnapshot(
        as_of=datetime(2026, 9, 6),
        balances={
            "cash": Decimal("50000000"),
            "realized_pnl": Decimal("0"),
            "margin_used": Decimal("1000"),
            "available_cash": Decimal("49999000"),
        },
        freshness=DataQuality(True, True, True, None),
    )


def gate(max_position):
    return RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=max_position),
            margin_engine=MarginCalculator(),
        )
    )


def test_authoritative_sources_reduce_then_route():
    router = FakeRouter()
    out = route_from_authoritative_sources(
        command(),
        risk_gate=gate(3),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
        allow_reduction=True,
    )
# assert out.approved is True
    assert out.decision == "REDUCE"
    assert router.commands[0].qty == 1


def test_authoritative_sources_deny_fail_closed():
    router = FakeRouter()
    out = route_from_authoritative_sources(
        command(),
        risk_gate=gate(2),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
        allow_reduction=False,
    )
# assert out.approved is False
# assert out.routed is False
    assert router.commands == []

# 이 확장은 기존 FakeGate가 아닌 Standard RiskEngine/RiskGate와 실제 기존 Account/Position adapter 계약을 함께 사용한다.


from core.decision.decision_arbiter import DecisionArbiter
from core.runtime.reference_execution_pipeline import (
DecisionCommandContext,
approved_signal_to_command,
)


def approved_signal():
    return CanonicalStrategySignal(
        signal_id="sig-1",
        track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=2,
        price=100.0,
        tag_id="gamma",
        symbol="KOSPI200F",
    )


def test_decision_to_command_to_authoritative_risk_to_router_allow():
    router = FakeRouter()
    approved = DecisionArbiter().arbitrate([approved_signal()], account=None).approved_signals
    command = approved_signal_to_command(
# approved[0],
        context=DecisionCommandContext(client_order_id="ord-1"),
    )

    out = route_from_authoritative_sources(
command,
        risk_gate=gate(5),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
    )

# assert out.approved is True
# assert out.routed is True
    assert router.commands[0].client_order_id == "ord-1"
    assert router.commands[0].qty == 2


def test_decision_to_command_requires_authoritative_client_order_id():
    approved = DecisionArbiter().arbitrate([approved_signal()], account=None).approved_signals

    with pytest.raises(ValueError, match="CLIENT_ORDER_ID_REQUIRED"):
        pass
        approved_signal_to_command(
# approved[0],
            context=DecisionCommandContext(client_order_id=""),
        )
