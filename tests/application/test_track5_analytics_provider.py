from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsSnapshot,
    AnalyticsStatus,
)
from application.composition.track5_analytics_provider import build_track5_analytics_snapshot
from application.composition.standard_runtime_input_provider import _track5_common_input
from core.strategy.contracts import CommonStrategyInput


AS_OF = datetime(2026, 10, 22, 2, 16, tzinfo=timezone(timedelta(hours=9)))


def _common_snapshot(option_premium: Decimal) -> AnalyticsSnapshot:
    return AnalyticsSnapshot(
        run_id="S23-TRACK5-ANALYTICS-TEST",
        instrument_identity=None,
        as_of=AS_OF,
        timeframe="tick",
        window=1,
        analytics_version="1",
        metrics={
            "price.last": AnalyticsMetric(
                metric_key="price.last",
                value=option_premium,
                status=AnalyticsStatus.AVAILABLE,
                unit="option-premium",
                as_of=AS_OF,
                calculation_version="common-v1",
                provenance=(AnalyticsProvenance(source="common-option-tick", dependencies=("last_price",), source_as_of=AS_OF),),
            ),
        },
    )


def _track5_data(underlying_price):
    return SimpleNamespace(
        open_price=Decimal("891.04"),
        previous_close=Decimal("858.78"),
        underlying_price=underlying_price,
        active_vol=Decimal("0.2"),
        macro_regime="NORMAL",
    )


def test_track5_price_last_uses_underlying_not_option_premium():
    snapshot = build_track5_analytics_snapshot(
        _track5_data(Decimal("858.78")),
        run_id="S23-TRACK5-ANALYTICS-TEST",
        as_of=AS_OF,
        common_snapshot=_common_snapshot(Decimal("42.30")),
    )

    metric = snapshot.get("price.last")
    assert metric is not None
    assert metric.value == Decimal("858.78")
    assert metric.unit == "index-points"
    assert metric.provenance[0].source == "common-analytics.track5"


def test_track5_does_not_fall_back_to_option_premium_when_underlying_missing():
    snapshot = build_track5_analytics_snapshot(
        _track5_data(None),
        run_id="S23-TRACK5-ANALYTICS-TEST",
        as_of=AS_OF,
        common_snapshot=_common_snapshot(Decimal("42.30")),
    )

    metric = snapshot.get("price.last")
    assert metric is not None
    assert metric.status is AnalyticsStatus.UNAVAILABLE
    assert metric.value is None

def test_track5_common_input_never_falls_back_to_option_premium():
    common = CommonStrategyInput(as_of=AS_OF, current_price=Decimal("42.30"))

    assert _track5_common_input(common, Decimal("858.78")).current_price == Decimal("858.78")
    assert _track5_common_input(common, None).current_price is None