from datetime import date
from decimal import Decimal

from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.basis_source import BasisObservation
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot
from contracts.types import MarketState
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.track2_market_metrics_source import KISTrack2MarketMetricsSource
from infrastructure.kis.volume_profile_source import KISVolumeProfileSource
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class OB:
    def get_order_book(self, symbol):
        levels = tuple(OptionOrderBookLevel(Decimal("3"), Decimal("10")) for _ in range(5))
        return OptionOrderBookSnapshot(symbol, "101500", levels, levels, "KIS:H0IOASP0")


def test_track2_reaches_authoritative_bbw_volume_boundary_before_remaining_iv_blocker() -> None:
    market = VirtualMarketSimulatorRuntime()
    metrics = KISTrack2MarketMetricsSource(price_window=20, history_size=40)
    poc = KISVolumeProfileSource()
    for i in range(25):
        observation = KisIndexFuturesMarketObservation(
            shrn_iscd="101S2609", observed_hour=f"1015{i:02d}",
            price=Decimal(f"{500 + (i % 3) * 0.5:.2f}"), volume=Decimal(100 + i * 10),
            ask_price=Decimal("500"), bid_price=Decimal("499.95"), source="KIS:H0IFCNT0",
        )
        metrics.update(observation)
        poc.update(observation)
    basis = KISBasisSource()
    basis.update(BasisObservation("KOSPI200", Decimal("501.0"), Decimal("500.0"), "101524", "KIS:INDEX+FUTURES"))
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-16T10:15:24", underlying_price=500.0,
        strike_price=500.0, option_type="CALL", bid_price=3.0, ask_price=3.2,
        last_price=3.1, volume=100, seq_id=25, expiry="202610", symbol="201S11305",
    )
    market._recent_ticks.append(tick)
    state = MarketState(as_of=__import__("datetime").datetime.fromisoformat(tick.timestamp), ticks={"KOSPI200": tick}, quality={})
    provider = StandardRuntimeInputProvider(
        market, option_orderbook_source=OB(), volume_profile_source=poc,
        basis_source=basis, track2_metrics_source=metrics,
    )
    context = provider.build(tick, state)["track2_asymmetric_trap"]
    assert context.analytics is None
    runtime_data = provider.data.snapshot(tick)
    assert runtime_data.basis == Decimal("1.0")
    assert runtime_data.bbw_window is not None and len(runtime_data.bbw_window) >= 2
    assert runtime_data.volume_window is not None and len(runtime_data.volume_window) >= 2
    assert runtime_data.status["track2_bbw_volume"].available is True


class IV:
    def get_iv(self, *, expiry, option_type, strike):
        return {"CALL": Decimal("0.241"), "PUT": Decimal("0.257")}[option_type]


def test_track2_analytics_snapshot_uses_authoritative_call_put_iv_source() -> None:
    market = VirtualMarketSimulatorRuntime()
    metrics = KISTrack2MarketMetricsSource(price_window=20, history_size=40)
    poc = KISVolumeProfileSource()
    for i in range(25):
        observation = KisIndexFuturesMarketObservation(
            shrn_iscd="101S2609", observed_hour=f"1015{i:02d}",
            price=Decimal(f"{500 + (i % 3) * 0.5:.2f}"), volume=Decimal(100 + i * 10),
            ask_price=Decimal("500"), bid_price=Decimal("499.95"), source="KIS:H0IFCNT0",
        )
        metrics.update(observation)
        poc.update(observation)
    basis = KISBasisSource()
    basis.update(BasisObservation("KOSPI200", Decimal("501.0"), Decimal("500.0"), "101524", "KIS:INDEX+FUTURES"))
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-16T10:15:24", underlying_price=500.0,
        strike_price=500.0, option_type="CALL", bid_price=3.0, ask_price=3.2,
        last_price=3.1, volume=100, seq_id=25, expiry="202610", symbol="201S11305",
    )
    market._recent_ticks.append(tick)
    state = MarketState(as_of=__import__("datetime").datetime.fromisoformat(tick.timestamp), ticks={"KOSPI200": tick}, quality={})
    provider = StandardRuntimeInputProvider(
        market, option_orderbook_source=OB(), volume_profile_source=poc,
        basis_source=basis, track2_metrics_source=metrics, track2_option_iv_source=IV(),
    )
    analytics = provider.build(tick, state)["track2_asymmetric_trap"].analytics
    assert analytics is not None
    assert analytics.get("options.call_iv").value == Decimal("0.241")
    assert analytics.get("options.put_iv").value == Decimal("0.257")
    assert analytics.get("futures.basis").value == Decimal("1.0")
    assert analytics.get("volatility.bbw").value is False
