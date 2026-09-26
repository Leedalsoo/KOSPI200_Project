from datetime import datetime

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.types import DataQuality, MarketState


def test_standard_runtime_materializes_track5_analytics_snapshot():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    context = StandardRuntimeInputProvider(market).build(tick, state, account)["track5_gap_divergence"]
    assert context.analytics is not None
    assert context.analytics.run_id == "virtual"
    assert context.analytics.get("price.gap") is not None
    assert context.analytics.get("stats.z_score") is not None
    assert context.analytics.get("price.last").provenance[0].source == "common-analytics.canonical"
    assert context.analytics.get("volatility.active").provenance[0].source == "common-analytics.canonical"


def test_standard_runtime_track5_fails_closed_when_volatility_is_missing():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    market._recent_ticks.clear()
    state = MarketState(as_of=datetime.fromisoformat(tick.timestamp), ticks={"KOSPI200": tick}, quality={})
    context = StandardRuntimeInputProvider(market).build(tick, state, account)["track5_gap_divergence"]
    assert context.analytics is not None
    assert context.analytics.get("volatility.expected_move").value is None



def test_standard_runtime_injects_authoritative_fee_and_margin_metrics():
    from decimal import Decimal
    from contracts.track9_margin_read_model import Track9MarginSnapshot

    class FeeLedger:
        def total(self, *, run_id, start=None, end=None):
            assert run_id == "RUN-COMMON"
            return Decimal("1234")

    class MarginReadModel:
        def snapshot(self, *, run_id):
            return Track9MarginSnapshot(
                run_id=run_id,
                account_id="ACC-VSSF-001",
                total_balance=Decimal("1000000"),
                used_margin=Decimal("200000"),
                free_margin=Decimal("800000"),
                observed_at=datetime(2026, 9, 26, 10, 0),
                source="VSSF:AccountSnapshot",
            )

    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    provider = StandardRuntimeInputProvider(
        market, track9_fee_ledger=FeeLedger(), track9_margin_read_model=MarginReadModel(), run_id="RUN-COMMON"
    )
    context = provider.build(tick, state, account)["track5_gap_divergence"]
    assert context.analytics.get("portfolio.total_fees").value == Decimal("1234")
    assert context.analytics.get("portfolio.total_fees").provenance[0].source == "common-analytics.canonical"
    assert context.analytics.get("portfolio.margin_ratio").value == Decimal("0.2")
