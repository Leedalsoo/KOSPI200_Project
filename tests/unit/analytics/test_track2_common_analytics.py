from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.strategy.contracts import StrategyContext
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap


def snapshot():
    return MarketSnapshot(
        run_id="S2-RUN",
        as_of=datetime(2026, 9, 20, 10, 0),
        provenance=AnalyticsProvenance(source="TEST"),
        instrument_identity=None,
        observations={
            "bbw_window": (0.30, 0.20, 0.10),
            "volume_window": (100.0, 100.0, 500.0),
            "basis": Decimal("1.0"),
            "put_iv": Decimal("15.0"),
            "call_iv": Decimal("20.0"),
            "poc_price": Decimal("495"),
            "bid_qtys": tuple(Decimal("100") for _ in range(5)),
            "ask_qtys": tuple(Decimal("1") for _ in range(5)),
            "active_vol": Decimal("0.15"),
            "base_vol": Decimal("0.20"),
            "last_price": Decimal("500"),
        },
    )


def request(key, deps):
    return AnalyticsRequest(
        metric_key=key,
        timeframe="tick",
        window=20,
        dependencies=tuple(deps),
        freshness_seconds=1.0,
        source_requirement="authoritative",
        analytics_version="1",
    )


def test_track2_declares_only_common_analytics_features():
    strategy = Track2AsymmetricTrap()
    keys = {item.metric_key for item in strategy.feature_requirements()}
    assert keys == {
        "volatility.bbw",
        "volume.z_score",
        "microstructure.obi",
        "futures.basis",
        "options.put_iv",
        "options.call_iv",
        "volume_profile.poc",
        "volatility.active",
        "volatility.base",
    }


def test_track2_common_analytics_evaluators_produce_trigger_inputs():
    from core.analytics.track2 import build_track2_evaluators

    requests = [
        request("volatility.bbw", ("bbw_window",)),
        request("volume.z_score", ("volume_window",)),
        request("microstructure.obi", ("bid_qtys", "ask_qtys")),
        request("futures.basis", ("basis",)),
        request("options.put_iv", ("put_iv",)),
        request("options.call_iv", ("call_iv",)),
        request("volume_profile.poc", ("poc_price",)),
        request("volatility.active", ("active_vol",)),
        request("volatility.base", ("base_vol",)),
    ]
    result = AnalyticsEngine(build_track2_evaluators()).evaluate(snapshot(), requests)
    assert result.get("volatility.bbw").value is True
    assert result.get("volume.z_score").value > 3.0
    assert result.get("microstructure.obi").value > Decimal("0.5")
    assert result.get("futures.basis").value == Decimal("1.0")


def test_track2_evaluate_consumes_analytics_snapshot_not_typed_market_payload():
    from core.analytics.track2 import build_track2_evaluators
    from core.domain.market_models import MarketState

    requests = [
        request("volatility.bbw", ("bbw_window",)),
        request("volume.z_score", ("volume_window",)),
        request("microstructure.obi", ("bid_qtys", "ask_qtys")),
        request("futures.basis", ("basis",)),
        request("options.put_iv", ("put_iv",)),
        request("options.call_iv", ("call_iv",)),
        request("volume_profile.poc", ("poc_price",)),
        request("volatility.active", ("active_vol",)),
        request("volatility.base", ("base_vol",)),
    ]
    analytics = AnalyticsEngine(build_track2_evaluators()).evaluate(snapshot(), requests)
    context = StrategyContext(
        market_state=MarketState(as_of=snapshot().as_of, ticks={"KOSPI200": type("Tick", (), {"instrument_id": "KOSPI200", "price": Decimal("500")})()}, quality={}),
        strategy_id="track2_asymmetric_trap",
        analytics=analytics,
    )
    signals = Track2AsymmetricTrap().evaluate(context)
    assert signals
    assert signals[0].reason == "ASYMMETRIC_TRAP_ENTRY"
