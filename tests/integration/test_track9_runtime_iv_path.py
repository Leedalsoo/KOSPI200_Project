from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from contracts.track9_iv_event_materializer import Track9ATMIVSnapshot, Track9IVEventMaterializer


class FakeATMSource:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)

    def snapshot(self, **kwargs):
        return next(self.snapshots)


class FakeScenario:
    def active_config(self):
        return {"base_volatility": 1.0, "shock_interval_days": 999999}


class FakeMarket:
    recent_ticks = []
    scenario = FakeScenario()


def _snapshot(at, call, put):
    return Track9ATMIVSnapshot(
        symbol="KOSPI200", expiry="2026-10-15", strike=Decimal("500"),
        call_iv=Decimal(str(call)), put_iv=Decimal(str(put)),
        observed_at=at, source="KIS:H0IOCNT0",
    )


def _tick(at):
    return SimpleNamespace(
        timestamp=at.isoformat(), last_price=Decimal("10"), volume=Decimal("1"),
        strike_price=Decimal("500"), option_type="CALL", expiry="2026-10-15",
        symbol="CALL500", underlying_symbol="KOSPI200", underlying_price=Decimal("501"),
        seq_id=1,
    )


def test_materializer_output_is_projected_into_virtual_runtime_data():
    start = datetime(2026, 9, 18, 9, 0)
    now = datetime(2026, 9, 18, 10, 0)
    source = FakeATMSource([_snapshot(start, "0.24", "0.26"), _snapshot(now, "0.28", "0.30")])
    provider = VirtualRuntimeDataProvider(
        FakeMarket(),
        track9_iv_event_materializer=Track9IVEventMaterializer(),
        track9_atm_iv_source=source,
    )

    provider.snapshot(_tick(start))
    result = provider.snapshot(_tick(now))

    assert result.iv_spike == Decimal("4.00")
    assert result.iv_crush == Decimal("0")
    assert result.status["track9_iv_event"].available is True
