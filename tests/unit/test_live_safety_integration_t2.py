from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot
from core.risk.risk_guard import RiskGuard
from environments.live.contracts import LiveApproval, LiveApprovalState, LiveSafetyPolicy
from environments.live.safety_gate import LiveSafetyGate


NOW = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)

def new_guard():
    guard = RiskGuard()
    guard.reset()
    return guard


def health(observed_at=NOW, level=SensorLevel.GREEN):
    return TradingHealthSnapshot(observed_at, (SensorSnapshot("market", level, observed_at),))


def gate():
    policy = LiveSafetyPolicy(
        approval_state=LiveApprovalState.APPROVED,
        kill_switch=False,
        max_order_quantity=10,
        max_daily_loss=10_000_000.0,
        max_position_quantity=100,
    )
    return LiveSafetyGate(
        policy,
        risk_guard=new_guard(),
        sensor_max_delay_seconds=30.0,
        approval_validity_seconds=900.0,
        now=lambda: NOW,
        allow_liquidation_reduction=True,
    )


def approve(g):
    g.approve(LiveApproval("operator", NOW.isoformat(), "T2 test"))


def test_risk_guard_is_required_and_health_is_enforced():
    g = gate()
    approve(g)
    result = g.evaluate(2, health=health(), daily_pnl=Decimal("0"), current_position_quantity=0)
    assert result.allowed is True
    blocked = g.evaluate(2, health=health(level=SensorLevel.YELLOW), daily_pnl=Decimal("0"), current_position_quantity=0)
    assert blocked.allowed is False
    assert blocked.reason == "risk guard blocked: TRADING_HEALTH_DEGRADED"


def test_daily_loss_engages_risk_guard():
    g = gate()
    approve(g)
    result = g.evaluate(2, health=health(), daily_pnl=Decimal("-10000000.01"), current_position_quantity=0)
    assert result.allowed is False
    assert result.reason == "DAILY_LOSS_LIMIT_EXCEEDED"
    assert g.risk_guard.kill_switch.engaged is True


def test_stale_sensor_and_expired_approval_are_blocked():
    g = gate()
    approve(g)
    stale = health(NOW - timedelta(seconds=31))
    assert g.evaluate(1, health=stale, daily_pnl=Decimal("0"), current_position_quantity=0).allowed is False
    g.revoke()
    g.approve(LiveApproval("operator", (NOW - timedelta(seconds=901)).isoformat(), "expired"))
    result = g.evaluate(1, health=health(), daily_pnl=Decimal("0"), current_position_quantity=0)
    assert result.reason == "live approval is expired"



def test_liquidation_reduction_is_allowed_only_by_explicit_policy():
    g = gate()
    approve(g)
    result = g.evaluate(
        20,
        health=health(),
        daily_pnl=Decimal("0"),
        current_position_quantity=90,
        order_purpose="LIQUIDATION",
        position_role="CLOSE",
    )
    assert result.allowed is False

    policy = LiveSafetyPolicy(
        approval_state=LiveApprovalState.APPROVED,
        kill_switch=False,
        max_order_quantity=100,
        max_daily_loss=10_000_000.0,
        max_position_quantity=100,
    )
    guard = new_guard()
    g = LiveSafetyGate(
        policy,
        risk_guard=guard,
        sensor_max_delay_seconds=30.0,
        approval_validity_seconds=900.0,
        now=lambda: NOW,
        allow_liquidation_reduction=True,
    )
    approve(g)
    assert g.evaluate(20, health=health(), daily_pnl=Decimal("0"), current_position_quantity=90, order_purpose="LIQUIDATION").allowed is True


def test_missing_required_live_safety_inputs_fail_closed():
    g = gate()
    approve(g)
    assert g.evaluate(1).allowed is False
    assert g.evaluate(1, health=health(), daily_pnl=Decimal("0")).allowed is False


def test_live_broker_uses_integrated_gate_and_never_transports_blocked_order():
    from contracts.types import BrokerOrderCommand, BrokerOrderResponse
    from environments.live.broker.kis_live_broker import LiveBrokerAdapter
    from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
    from environments.live.idempotency import IdempotencyRegistry, OrderIdentity

    class Transport:
        connected = False
        submitted = []
        def authenticate(self):
            self.connected = True
            return True
        def submit(self, command):
            self.submitted.append(command)
            return BrokerOrderResponse(command.client_order_id, True, "ACK")

    class SymbolSource:
        def current_symbol(self): return "101W09"

    transport = Transport()
    policy = LiveSafetyPolicy(LiveApprovalState.APPROVED, False, 10, 10_000_000.0, 100)
    safety = LiveSafetyGate(policy, risk_guard=new_guard(), sensor_max_delay_seconds=30.0,
                            approval_validity_seconds=900.0, now=lambda: NOW,
                            allow_liquidation_reduction=True)
    approve(safety)
    broker = LiveBrokerAdapter(transport, safety, policy, IdempotencyRegistry(),
                               KisFuturesBrokerCommandAdapter(SymbolSource()))
    broker.connect()
    command = BrokerOrderCommand("ORD-T2", "FUT-1", "BUY", 2, "LIMIT", asset_type="FUTURES")
    identity = OrderIdentity("ORD-T2", "TRACK-1", "fp-t2")
    with pytest.raises(RuntimeError, match="CURRENT_POSITION_QUANTITY_REQUIRED"):
        broker.submit(command, identity, 1.0, health=health(), daily_pnl=Decimal("0"))
    assert transport.submitted == []
