from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsSnapshot,
    AnalyticsStatus,
)
from core.strategy.contracts import (
    StrategyFeatureRequirement,
    StrategyPlugin,
    validate_strategy_features,
)


AS_OF = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def _snapshot(status: AnalyticsStatus = AnalyticsStatus.AVAILABLE) -> AnalyticsSnapshot:
    metric = AnalyticsMetric(
        "vol.realized", Decimal("0.2"), status, "ratio", AS_OF, "1",
        (AnalyticsProvenance("test"),),
    )
    return AnalyticsSnapshot("run-1", None, AS_OF, "1m", 20, "1", {"vol.realized": metric})


def test_plugin_declares_feature_and_source_status_requirement() -> None:
    requirement = StrategyFeatureRequirement(
        metric_key="vol.realized",
        timeframe="1m",
        freshness_seconds=5,
        allowed_statuses=frozenset({AnalyticsStatus.AVAILABLE}),
    )

    assert requirement.metric_key == "vol.realized"
    assert requirement.allowed_statuses == frozenset({AnalyticsStatus.AVAILABLE})


def test_plugin_features_are_rejected_when_snapshot_is_unavailable() -> None:
    requirement = StrategyFeatureRequirement(
        metric_key="vol.realized",
        timeframe="1m",
        freshness_seconds=5,
        allowed_statuses=frozenset({AnalyticsStatus.AVAILABLE}),
    )

    result = validate_strategy_features((requirement,), _snapshot(AnalyticsStatus.UNAVAILABLE))
    assert result[0].status is AnalyticsStatus.UNAVAILABLE
    assert result[0].value is None


def test_plugin_contract_requires_metadata_and_lifecycle() -> None:
    class ExamplePlugin:
        strategy_id = "example"
        version = "1.0"

        def feature_requirements(self):
            return ()

        def initialize(self, context):
            pass

        def on_market_state(self, context):
            pass

        def evaluate(self, context):
            return ()

        def reset(self):
            pass

    assert isinstance(ExamplePlugin(), StrategyPlugin)


def test_feature_requirement_rejects_negative_freshness() -> None:
    with pytest.raises(ValueError):
        StrategyFeatureRequirement(
            metric_key="vol.realized",
            timeframe="1m",
            freshness_seconds=-1,
            allowed_statuses=frozenset({AnalyticsStatus.AVAILABLE}),
        )
