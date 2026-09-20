from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsRequest,
    AnalyticsSnapshot,
    AnalyticsStatus,
    MarketSnapshot,
)
from core.analytics.engine import AnalyticsEngine


AS_OF = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def _market(**observations: object) -> MarketSnapshot:
    return MarketSnapshot(
        run_id="run-1",
        as_of=AS_OF,
        provenance=AnalyticsProvenance("test-source"),
        instrument_identity=None,
        observations=observations,
    )


def _request(key: str, *, timeframe: str = "1m", window: int = 20) -> AnalyticsRequest:
    return AnalyticsRequest(
        metric_key=key,
        timeframe=timeframe,
        window=window,
        dependencies=("price.last",),
        freshness_seconds=5,
        source_requirement="test-source",
        analytics_version="1",
    )


def test_same_metric_requested_by_two_consumers_is_computed_once() -> None:
    calls = 0

    def evaluator(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
        nonlocal calls
        calls += 1
        return AnalyticsMetric(
            request.metric_key, Decimal("100"), AnalyticsStatus.AVAILABLE,
            "price", snapshot.as_of, request.analytics_version,
            (snapshot.provenance,),
        )

    engine = AnalyticsEngine({"price.mid": evaluator})
    snapshot = engine.evaluate(_market(**{"price.last": Decimal("100")}), (_request("price.mid"), _request("price.mid")))

    assert calls == 1
    assert snapshot.get("price.mid") is not None


def test_missing_dependency_fails_closed_without_evaluator_call() -> None:
    calls = 0

    def evaluator(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
        nonlocal calls
        calls += 1
        raise AssertionError("evaluator must not run")

    engine = AnalyticsEngine({"price.mid": evaluator})
    snapshot = engine.evaluate(_market(), (_request("price.mid"),))

    assert calls == 0
    assert snapshot.get("price.mid").status is AnalyticsStatus.UNAVAILABLE
    assert snapshot.get("price.mid").value is None


def test_timeframe_window_and_version_are_distinct_cache_keys() -> None:
    calls = 0

    def evaluator(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
        nonlocal calls
        calls += 1
        return AnalyticsMetric(
            request.metric_key, Decimal(calls), AnalyticsStatus.AVAILABLE,
            "price", snapshot.as_of, request.analytics_version,
            (snapshot.provenance,),
        )

    engine = AnalyticsEngine({"price.mid": evaluator})
    market = _market(**{"price.last": Decimal("100")})
    engine.evaluate(market, (_request("price.mid", timeframe="1m", window=20),))
    engine.evaluate(market, (_request("price.mid", timeframe="5m", window=20),))
    engine.evaluate(
        market,
        (AnalyticsRequest("price.mid", "1m", 20, ("price.last",), 5, "test-source", "2"),),
    )

    assert calls == 3
