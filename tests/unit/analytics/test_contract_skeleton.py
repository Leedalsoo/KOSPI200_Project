from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.analytics import AnalyticsMetric, AnalyticsRequest


def test_analytics_request_requires_stable_metric_key_and_timeframe_window() -> None:
    request = AnalyticsRequest(
        metric_key="price.mid",
        timeframe="1m",
        window=20,
        dependencies=("market.bid", "market.ask"),
        freshness_seconds=5,
        source_requirement="market_data",
        analytics_version="1",
    )
    assert request.metric_key == "price.mid"
    assert request.timeframe == "1m"
    assert request.window == 20


def test_analytics_metric_requires_explicit_unit_and_as_of() -> None:
    metric = AnalyticsMetric(
        metric_key="price.mid",
        value=Decimal("100.25"),
        status="AVAILABLE",
        unit="price",
        as_of=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc),
        calculation_version="1",
        provenance=("market_data",),
    )
    assert metric.unit == "price"
    assert metric.as_of.tzinfo is not None


def test_invalid_timeframe_or_window_is_rejected() -> None:
    with pytest.raises(ValueError):
        AnalyticsRequest(
            metric_key="price.mid",
            timeframe="",
            window=20,
            dependencies=(),
            freshness_seconds=5,
            source_requirement="market_data",
            analytics_version="1",
        )
    with pytest.raises(ValueError):
        AnalyticsRequest(
            metric_key="price.mid",
            timeframe="1m",
            window=0,
            dependencies=(),
            freshness_seconds=5,
            source_requirement="market_data",
            analytics_version="1",
        )
