from datetime import datetime
from decimal import Decimal

from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from application.composition.track4_market_input_materializer import Track4RuntimeInputMaterializer
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from contracts.types import AccountSnapshot, CanonicalMarketTick, DataQuality, MarketState
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry
from core.strategy.track4_gamma_scalping import Track4MarketInput

AS_OF = datetime(2026, 1, 2, 10, 0)
TRACK4_KEY = ("track4_gamma_scalping", "1.0")


class StubAccountProvider:
    def snapshot(self):
        return AccountSnapshot(as_of=AS_OF, balances={"cash": Decimal("1000000"), "realized_pnl": Decimal("1000"), "unrealized_pnl": Decimal("2000")}, freshness=DataQuality(True, True, True, "test"))


def build_materialized_track4_input() -> Track4MarketInput:
    market = Track4MarketProjectionProvider(
        lambda: MarketConditionSnapshot(as_of=AS_OF, instrument_id="KOSPI200_VIRTUAL", current_price=350.0, price_change=0.2, volatility=0.008, baseline_volatility=0.010, volatility_ratio=0.8, drawdown=0.0, stress_level=0.0, stress_flags=()),
        price_history_supplier=lambda _: (Decimal("349.0"), Decimal("350.0")),
    )
    account = Track4VSSFAccountProjectionProvider(StubAccountProvider())
    provider = Track4CompositeRuntimeInputProvider(market, account)
    greeks = KISIndexOptionGreeksProvider.from_payload({"delta": "0.52", "gama": "0.18", "theta": "-0.07", "hts_ints_vltl": "0.21"}, instrument_id="KOSPI200-OPT-1", observed_at=AS_OF.isoformat())
    return Track4RuntimeInputMaterializer(provider, greeks).materialize(AS_OF)


def build_context(data: Track4MarketInput) -> StrategyContext:
    tick = CanonicalMarketTick(instrument_id="KOSPI200_VIRTUAL", observed_at=data.observed_at, price=data.current_price)
    state = MarketState(as_of=data.observed_at, ticks={tick.instrument_id: tick}, quality={})
    common = CommonStrategyInput(as_of=data.observed_at, current_price=data.current_price, active_vol=data.active_vol, base_vol=data.base_vol, current_pnl=data.current_pnl, time_str=data.time_str)
    analytics = build_track4_analytics_snapshot(data, run_id="track4-integration", as_of=data.observed_at)
    return StrategyContext(market_state=state, strategy_id=TRACK4_KEY[0], input=StrategyInput(common=common, payload=data), analytics=analytics)


def test_materialized_track4_input_reaches_registry_orchestrator_and_evaluate():
    context = build_context(build_materialized_track4_input())
    result = StrategyOrchestrator(build_standard_strategy_registry(), STANDARD_STRATEGY_KEYS).run({TRACK4_KEY[0]: context}, selected=(TRACK4_KEY,))
    assert result.failures == ()
    assert any(signal.direction == "BUILD" for signal in result.signals)
    assert any(signal.direction == "SELL" for signal in result.signals)


def test_track4_identity_and_payload_boundary_are_preserved():
    data = build_materialized_track4_input()
    context = build_context(data)
    assert context.strategy_id == TRACK4_KEY[0]
    assert context.input is not None
    assert context.input.payload is data
    assert isinstance(context.input.payload, Track4MarketInput)
    assert context.analytics is not None
    assert context.analytics.run_id == "track4-integration"
    assert context.market_state.as_of == data.observed_at
