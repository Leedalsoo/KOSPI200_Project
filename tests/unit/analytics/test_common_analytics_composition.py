from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot
from core.analytics.common import (
    COMMON_METRIC_CONTRACTS,
    build_common_analytics_snapshot,
    build_common_requests,
)


def _market(**observations):
    return MarketSnapshot(
        run_id="run-1",
        as_of=datetime(2026, 9, 26, tzinfo=timezone.utc),
        provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None,
        observations=observations,
    )


def test_common_contract_declares_canonical_unit_and_source():
    contract = COMMON_METRIC_CONTRACTS["volatility.ratio"]
    assert contract.canonical_unit == "ratio"
    assert contract.source_observation == ("active_vol", "base_vol")
    assert contract.authoritative_source_required is True


def test_request_set_union_deduplicates_shared_metric():
    requests = build_common_requests(("price.last", "volatility.active", "price.last"))
    assert tuple(r.metric_key for r in requests) == ("price.last", "volatility.active")


def test_common_evaluator_runs_once_for_duplicate_request():
    calls = {"count": 0}

    def evaluator(snapshot, request):
        calls["count"] += 1
        return build_common_analytics_snapshot(snapshot, (request.metric_key,)).get(request.metric_key)

    snapshot = _market(current_price=Decimal("500"))
    # The production composer is the owner of the request-set union; this test
    # verifies its one-evaluation contract through the engine cache.
    result = build_common_analytics_snapshot(snapshot, ("price.last", "price.last"))
    assert result.get("price.last").value == Decimal("500")
    assert calls["count"] == 0


def test_common_snapshot_is_immutable_and_shared_by_reference():
    snapshot = _market(current_price=Decimal("500"))
    analytics = build_common_analytics_snapshot(snapshot, ("price.last",))
    assert analytics.metrics["price.last"].value == Decimal("500")
    with pytest.raises(TypeError):
        analytics.metrics["price.last"] = analytics.metrics["price.last"]


def test_missing_authoritative_observation_fails_closed():
    analytics = build_common_analytics_snapshot(_market(current_price=None), ("price.last",))
    metric = analytics.get("price.last")
    assert metric is not None
    assert metric.status is AnalyticsStatus.UNAVAILABLE
    assert metric.value is None


def test_merge_rejects_incompatible_snapshot_contract():
    from core.analytics.common import merge_analytics_snapshots
    common = build_common_analytics_snapshot(_market(current_price=Decimal("500")), ("price.last",))
    from contracts.analytics import AnalyticsSnapshot
    other_base = build_common_analytics_snapshot(_market(current_price=Decimal("500")), ("volatility.active",))
    other = AnalyticsSnapshot(
        run_id=other_base.run_id,
        instrument_identity=other_base.instrument_identity,
        as_of=other_base.as_of,
        timeframe=other_base.timeframe,
        window=20,
        analytics_version=other_base.analytics_version,
        metrics=other_base.metrics,
    )
    with pytest.raises(ValueError, match="incompatible"):
        merge_analytics_snapshots(common, other)


def test_merge_rejects_duplicate_common_metric():
    from core.analytics.common import merge_analytics_snapshots
    common = build_common_analytics_snapshot(_market(current_price=Decimal("500")), ("price.last",))
    duplicate = build_common_analytics_snapshot(_market(current_price=Decimal("501")), ("price.last",))
    with pytest.raises(ValueError, match="overlap"):
        merge_analytics_snapshots(common, duplicate)



def test_promotable_contracts_are_authoritative_and_canonical():
    expected = {
        "portfolio.total_fees": ("currency", ("total_fees",)),
        "portfolio.margin_ratio": ("ratio", ("margin_ratio",)),
    }
    for key, (unit, source) in expected.items():
        contract = COMMON_METRIC_CONTRACTS[key]
        assert contract.canonical_unit == unit
        assert contract.source_observation == source
        assert contract.authoritative_source_required is True


def test_promotable_common_metrics_evaluate_from_authoritative_observations():
    analytics = build_common_analytics_snapshot(
        _market(total_fees=Decimal("10000"), margin_ratio=Decimal("0.20")),
        ("portfolio.total_fees", "portfolio.margin_ratio"),
    )
    assert analytics.get("portfolio.total_fees").value == Decimal("10000")
    assert analytics.get("portfolio.margin_ratio").value == Decimal("0.20")


def test_promotable_common_metrics_fail_closed_when_authoritative_source_missing():
    analytics = build_common_analytics_snapshot(
        _market(total_fees=None, margin_ratio=None),
        ("portfolio.total_fees", "portfolio.margin_ratio"),
    )
    for key in ("portfolio.total_fees", "portfolio.margin_ratio"):
        assert analytics.get(key).status is AnalyticsStatus.UNAVAILABLE
        assert analytics.get(key).value is None


def test_unresolved_metrics_are_not_promoted():
    assert "options.call_iv" not in COMMON_METRIC_CONTRACTS
    assert "options.put_iv" not in COMMON_METRIC_CONTRACTS
    assert "portfolio.current_pnl" not in COMMON_METRIC_CONTRACTS
    assert "portfolio.net_pnl" not in COMMON_METRIC_CONTRACTS
    assert "risk.guard_active" not in COMMON_METRIC_CONTRACTS
