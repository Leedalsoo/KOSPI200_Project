from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input, Track1TailDefense
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.track3_statistical_arbitrage import Track3MarketInput, Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9State
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def _track4_input(now: datetime) -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=now,
        current_price=Decimal("350"),
        active_vol=Decimal("1"),
        base_vol=Decimal("1"),
        time_str="10:00:00",
        current_delta=Decimal("0.4"),
        current_gamma=Decimal("0"),
        current_pnl=Decimal("0"),
        current_equity=Decimal("1000000"),
        price_history=(Decimal("350"), Decimal("351")),
    )


def _track4_analytics(strategy: Track4GammaScalping, now: datetime, *, stale_key: str | None = None) -> AnalyticsSnapshot:
    values = {
        "volatility.active": Decimal("1"),
        "volatility.base": Decimal("1"),
        "volatility.ratio": Decimal("1"),
        "options.delta": Decimal("0.4"),
        "portfolio.current_pnl": Decimal("0"),
        "portfolio.equity": Decimal("1000000"),
        "price.tick_deadband": Decimal("0.2"),
    }
    metrics = {
        requirement.metric_key: AnalyticsMetric(
            metric_key=requirement.metric_key,
            value=values[requirement.metric_key],
            status=AnalyticsStatus.STALE if requirement.metric_key == stale_key else AnalyticsStatus.AVAILABLE,
            unit="test",
            as_of=now,
            calculation_version="contract-test-v1",
            provenance=("test-authoritative-source",),
        )
        for requirement in strategy.feature_requirements()
    }
    return AnalyticsSnapshot(
        run_id="strategy-contract-test",
        instrument_identity=None,
        as_of=now,
        timeframe="tick",
        window=1,
        analytics_version="contract-test-v1",
        metrics=metrics,
    )


def test_track1_missing_market_state_fails_closed() -> None:
    strategy = Track1TailDefense()
    context = StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=Track1Input()))
    assert strategy.evaluate(context) == ()


def test_track1_empty_market_state_fails_closed() -> None:
    now = datetime.now(timezone.utc)
    strategy = Track1TailDefense()
    context = StrategyContext(
        market_state=MarketState(now, {}, {}),
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=Track1Input()),
    )
    assert strategy.evaluate(context) == ()


def test_track1_unchanged_price_has_no_signal_after_initial_fence() -> None:
    from tests.strategy.test_strategy1 import ctx

    strategy = Track1TailDefense()
    initial = ctx()
    assert len(strategy.evaluate(initial)) == 3
    assert not strategy.evaluate(ctx())


def test_track2_plan_preserves_group_strategy_and_leg_identity() -> None:
    strategy = Track2AsymmetricTrap()
    plan = strategy.build_execution_plan("T2-PROVENANCE", Decimal("350"), 0.8, 1.0)
    assert plan.group_id == "T2-PROVENANCE"
    assert plan.strategy_id == strategy.strategy_id
    assert len({leg.leg_id for leg in plan.legs}) == len(plan.legs) == 4
    assert all(leg.quantity > 0 for leg in plan.legs)


def test_track3_missing_authoritative_input_fails_closed() -> None:
    strategy = Track3StatisticalArbitrage()
    assert strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id)) == ()
    assert strategy.evaluate(
        StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=Track3MarketInput()))
    ) == ()


def test_track4_missing_analytics_fails_closed() -> None:
    now = datetime.now(timezone.utc)
    strategy = Track4GammaScalping()
    context = StrategyContext(
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=_track4_input(now)),
        analytics=None,
    )
    assert strategy.evaluate(context) == ()


def test_track4_stale_authoritative_metric_fails_closed() -> None:
    now = datetime.now(timezone.utc)
    strategy = Track4GammaScalping()
    context = StrategyContext(
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=_track4_input(now)),
        analytics=_track4_analytics(strategy, now, stale_key="options.delta"),
    )
    assert strategy.evaluate(context) == ()


def test_track9_missing_analytics_fails_closed() -> None:
    strategy = Track9EventOvernightInsurance()
    assert strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id)) == ()


def test_track9_pair_plan_preserves_group_strategy_and_leg_identity() -> None:
    strategy = Track9EventOvernightInsurance(pair_quantity=2)
    strategy.state = Track9State(
        entry_date="2026-10-08",
        entry_qty=2,
        put_strike=Decimal("1090"),
        call_strike=Decimal("1110"),
        entered_today=True,
        state="OVERNIGHT_INSURANCE_AWAITING_FILLS",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        side="BUY",
        track_id=strategy.strategy_id,
        tag_id="OVERNIGHT_INSURANCE_PUT",
        option_type="PUT",
        strike=Decimal("1090"),
    )
    plan = strategy.build_execution_plan("T9-PROVENANCE", proposal=proposal)
    assert plan.group_id == "T9-PROVENANCE"
    assert plan.strategy_id == strategy.strategy_id
    assert [(leg.leg_id, leg.option_type, leg.quantity) for leg in plan.legs] == [
        ("put", "PUT", 2), ("call", "CALL", 2)
    ]
