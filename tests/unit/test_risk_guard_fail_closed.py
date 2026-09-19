from decimal import Decimal

from core.risk.risk_guard import RiskGuard
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot


def test_guard_blocks_when_health_is_blocked():
    health = TradingHealthSnapshot.from_sensors([
        SensorSnapshot("MARKET_DATA", SensorLevel.GREEN, reason="fresh"),
        SensorSnapshot("OPTION_MASTER", SensorLevel.BLOCKED, reason="missing"),
    ])
    decision = RiskGuard().evaluate(health=health, kill_switch_engaged=False)
    assert decision.allowed is False
    assert decision.reason == "TRADING_HEALTH_BLOCKED"


def test_guard_blocks_unknown_health_and_engaged_kill_switch():
    health = TradingHealthSnapshot.from_sensors([
        SensorSnapshot("POSITION", SensorLevel.UNKNOWN, reason="unavailable"),
    ])
    decision = RiskGuard().evaluate(health=health, kill_switch_engaged=True)
    assert decision.allowed is False
    assert decision.reason == "KILL_SWITCH_ENGAGED"


def test_guard_allows_only_explicit_green_health_with_switch_open():
    health = TradingHealthSnapshot.from_sensors([
        SensorSnapshot("MARKET_DATA", SensorLevel.GREEN, reason="fresh"),
        SensorSnapshot("POSITION", SensorLevel.GREEN, reason="fresh"),
    ])
    decision = RiskGuard().evaluate(health=health, kill_switch_engaged=False)
    assert decision.allowed is True
    assert decision.reason == "READY"
