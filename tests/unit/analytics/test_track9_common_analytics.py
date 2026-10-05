from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track9 import build_track9_evaluators
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance


AS_OF = datetime(2026, 9, 18, 10, 0)


def snapshot(**observations):
    return MarketSnapshot(
        run_id="RUN-T9",
        as_of=AS_OF,
        provenance=AnalyticsProvenance(source="track9-test"),
        instrument_identity=None,
        observations=observations,
    )


def request(key, *dependencies):
    return AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")


def test_track9_plugin_declares_canonical_features():
    strategy = Track9EventOvernightInsurance()
    keys = {item.metric_key for item in strategy.feature_requirements()}
    assert {
        "price.last",
        "options.atm_call_strike",
        "options.atm_put_strike",
        "options.contract_multiplier",
        "options.track9_put_mark_price",
        "options.track9_call_mark_price",
    } == keys


def test_track9_analytics_does_not_recreate_common_metrics():
    evaluators = build_track9_evaluators()
    assert "portfolio.current_pnl" not in evaluators
    assert "portfolio.total_fees" not in evaluators
    assert "portfolio.net_pnl" not in evaluators
    assert "portfolio.margin_ratio" not in evaluators
    assert "risk.guard_active" not in evaluators

    result = AnalyticsEngine(evaluators).evaluate(
        snapshot(current_pnl=Decimal("120"), total_fees=Decimal("20")),
        (request("portfolio.net_pnl", "current_pnl", "total_fees"),),
    )
    assert result.get("portfolio.net_pnl").status is AnalyticsStatus.UNAVAILABLE


def test_track9_analytics_exposes_authoritative_contract_values_without_synthesis():
    market = snapshot(
        atm_call_strike=Decimal("365"),
        atm_put_strike=Decimal("335"),
        contract_multiplier=Decimal("250000"),
    )
    result = AnalyticsEngine(build_track9_evaluators()).evaluate(
        market,
        (
            request("options.atm_call_strike", "atm_call_strike"),
            request("options.atm_put_strike", "atm_put_strike"),
            request("options.contract_multiplier", "contract_multiplier"),
        ),
    )
    assert result.get("options.atm_call_strike").value == Decimal("365")
    assert result.get("options.atm_put_strike").value == Decimal("335")
    assert result.get("options.contract_multiplier").value == Decimal("250000")

    price_result = AnalyticsEngine(build_track9_evaluators()).evaluate(
        snapshot(
            track9_put_entry_price=Decimal("10.5"),
            track9_call_entry_price=Decimal("12.0"),
            track9_put_mark_price=Decimal("24.0"),
            track9_call_mark_price=Decimal("8.0"),
        ),
        (
            request("options.track9_put_entry_price", "track9_put_entry_price"),
            request("options.track9_call_entry_price", "track9_call_entry_price"),
            request("options.track9_put_mark_price", "track9_put_mark_price"),
            request("options.track9_call_mark_price", "track9_call_mark_price"),
        ),
    )
    assert price_result.get("options.track9_put_entry_price").value == Decimal("10.5")
    assert price_result.get("options.track9_call_entry_price").value == Decimal("12.0")
    assert price_result.get("options.track9_put_mark_price").value == Decimal("24.0")
    assert price_result.get("options.track9_call_mark_price").value == Decimal("8.0")
