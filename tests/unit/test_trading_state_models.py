from datetime import datetime, timezone
from decimal import Decimal

from contracts.trading_state import (
    KillSwitchState,
    SensorLevel,
    SensorSnapshot,
    TradingHealthSnapshot,
    PositionPnLExposureSnapshot,
)


def test_sensor_snapshot_is_immutable_and_serializable():
    observed = datetime.now(timezone.utc)
    sensor = SensorSnapshot("MARKET_DATA", SensorLevel.GREEN, observed, "fresh")
    health = TradingHealthSnapshot(observed_at=observed, sensors=(sensor,))
    assert health.sensors[0].level is SensorLevel.GREEN
    assert health.sensors[0].name == "MARKET_DATA"


def test_health_is_not_green_when_blocked_or_unknown():
    observed = datetime.now(timezone.utc)
    blocked = SensorSnapshot("LIVE_CREDENTIAL", SensorLevel.BLOCKED, observed, "missing")
    unknown = SensorSnapshot("POSITION", SensorLevel.UNKNOWN, observed, "unavailable")
    health = TradingHealthSnapshot(observed_at=observed, sensors=(blocked, unknown))
    assert health.overall_level() is SensorLevel.BLOCKED


def test_position_pnl_exposure_snapshot_requires_explicit_values():
    snap = PositionPnLExposureSnapshot(
        as_of=datetime.now(timezone.utc),
        gross_exposure=Decimal("100"),
        net_exposure=Decimal("20"),
        option_exposure=Decimal("80"),
        futures_exposure=Decimal("20"),
        realized_pnl=Decimal("5"),
        unrealized_pnl=Decimal("-2"),
        daily_pnl=Decimal("3"),
        open_positions=2,
    )
    assert snap.daily_pnl == Decimal("3")


def test_kill_switch_state_defaults_to_closed_fail_safe():
    state = KillSwitchState()
    assert state.engaged is True
    assert state.reason == "FAIL_SAFE_DEFAULT"
