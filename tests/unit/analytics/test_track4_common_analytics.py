from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsSnapshot, AnalyticsStatus
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot

AS_OF = datetime(2026, 9, 8, 10, 0)


def _data() -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=AS_OF, current_price=Decimal("350"), active_vol=Decimal("0.21"), base_vol=Decimal("0.20"),
        time_str="10:00:00", current_delta=Decimal("0.41"), current_gamma=Decimal("0.18"), current_pnl=Decimal("1000"),
        current_equity=Decimal("1000000"), price_history=(Decimal("349"), Decimal("350")), current_theta=Decimal("-0.07"),
    )


def test_track4_common_analytics_exposes_gamma_scalping_features() -> None:
    snapshot = build_track4_analytics_snapshot(_data(), run_id="run-track4", as_of=AS_OF)
    assert snapshot.get("volatility.ratio").value == Decimal("1.05")
    assert snapshot.get("options.delta").value == Decimal("0.41")
    assert snapshot.get("options.gamma").value == Decimal("0.18")
    assert snapshot.get("options.theta").value == Decimal("-0.07")
    assert snapshot.get("portfolio.current_pnl").value == Decimal("1000")
    assert snapshot.get("portfolio.equity").value == Decimal("1000000")
    assert snapshot.get("price.tick_deadband").status is AnalyticsStatus.AVAILABLE


def test_track4_strategy_declares_only_features_it_consumes() -> None:
    keys = {requirement.metric_key for requirement in Track4GammaScalping().feature_requirements()}
    assert keys == {"volatility.active", "volatility.base", "volatility.ratio", "options.delta", "portfolio.current_pnl", "portfolio.equity", "price.tick_deadband"}


def test_track4_strategy_reads_analytics_snapshot_instead_of_recomputing_common_values() -> None:
    data = _data()
    snapshot = build_track4_analytics_snapshot(data, run_id="run-track4", as_of=AS_OF)
    context = StrategyContext(strategy_id="track4_gamma_scalping", input=StrategyInput(payload=data), analytics=snapshot)
    signals = Track4GammaScalping().evaluate(context)
    assert any(signal.direction == "SELL" for signal in signals)


def test_track4_analytics_snapshot_is_immutable() -> None:
    metric = AnalyticsMetric("test.metric", Decimal("1"), AnalyticsStatus.AVAILABLE, "unit", AS_OF, "1", (AnalyticsProvenance("test"),))
    snapshot = AnalyticsSnapshot("run-track4", None, AS_OF, "tick", 1, "1", {"test.metric": metric})
    try:
        snapshot.metrics["other.metric"] = metric
    except TypeError:
        pass
    else:
        raise AssertionError("AnalyticsSnapshot metrics must be immutable")
