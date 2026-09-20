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
        "portfolio.active_sell_qty",
        "portfolio.insurance_qty",
        "events.upcoming",
        "options.iv_spike",
        "options.iv_crush",
        "portfolio.current_pnl",
        "portfolio.total_fees",
        "portfolio.net_pnl",
        "portfolio.margin_ratio",
        "risk.guard_active",
        "portfolio.event_budget",
        "portfolio.estimated_event_cost",
        "options.atm_call_strike",
        "options.atm_put_strike",
        "options.contract_multiplier",
    } <= keys


def test_track9_analytics_calculates_net_pnl_once_and_preserves_unavailable_inputs():
    market = snapshot(current_pnl=Decimal("120"), total_fees=Decimal("20"))
    engine = AnalyticsEngine(build_track9_evaluators())
    result = engine.evaluate(
        market,
        (
            request("portfolio.current_pnl", "current_pnl"),
            request("portfolio.total_fees", "total_fees"),
            request("portfolio.net_pnl", "current_pnl", "total_fees"),
            request("events.upcoming", "event_upcoming"),
        ),
    )
    assert result.get("portfolio.net_pnl").value == Decimal("100")
    assert result.get("events.upcoming").status is AnalyticsStatus.UNAVAILABLE
    assert result.get("events.upcoming").value is None


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
