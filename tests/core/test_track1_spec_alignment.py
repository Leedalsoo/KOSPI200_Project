from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.types import CanonicalMarketTick, MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input, Track1TailDefense


def make_context(
    price: str,
    *,
    reference_point: str = "100",
    open_short: int = 0,
    pending_short: int = 0,
    reference_verified: bool = True,
    exposure_verified: bool = True,
    dte: float = 10,
    dte_verified: bool = True,
    runtime_config_verified: bool = True,
    risk_limits_available: bool = True,
) -> tuple[Track1TailDefense, StrategyContext]:
    strategy = Track1TailDefense(
        runtime_config_verified=runtime_config_verified,
        risk_limits_available=risk_limits_available,
    )
    now = datetime(2026, 11, 9, 10, 0)
    market_state = MarketState(
        as_of=now,
        ticks={
            "KOSPI200": CanonicalMarketTick(
                instrument_id="KOSPI200",
                observed_at=now,
                price=Decimal(price),
            )
        },
        quality={},
    )
    payload = Track1Input(
        current_time=now,
        days_to_expiry=dte,
        reference_point=Decimal(reference_point),
        reference_point_verified=reference_verified,
        open_short_quantity=open_short,
        pending_short_quantity=pending_short,
        exposure_snapshot_verified=exposure_verified,
        dte_basis_verified=dte_verified,
    )
    return strategy, StrategyContext(
        market_state=market_state,
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=payload),
    )


def test_track1_put_base_fence_is_buy_not_inferred_sell() -> None:
    strategy = Track1TailDefense()
    signal = strategy._build_fence_signal(
        "PUT", 87.5, 0, "TAIL_DEFENSE_BUILD_OUTER", side="BUY"
    )
    assert signal.direction == "BUY"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.side == "BUY"
    assert signal.execution_proposal.asset_type == "OPTION"
    assert signal.execution_proposal.option_type == "PUT"
    assert signal.execution_proposal.strike == Decimal("87.5")


def test_track1_short_put_fence_remains_explicit_sell() -> None:
    strategy = Track1TailDefense()
    signal = strategy._build_fence_signal(
        "PUT", 92.5, 1, "INITIAL_INNER_FENCE", side="SELL"
    )
    assert signal.direction == "SELL"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.side == "SELL"
    assert signal.execution_proposal.asset_type == "OPTION"


def test_track1_rejects_implicit_or_invalid_order_side() -> None:
    strategy = Track1TailDefense()
    with pytest.raises(ValueError, match="TRACK1_OPTION_SIDE_INVALID"):
        strategy._build_fence_signal(
            "PUT", 92.5, 1, "INITIAL_INNER_FENCE", side="HOLD"
        )


def test_track1_new_entries_fail_closed_without_runtime_config_and_risk() -> None:
    strategy, context = make_context(
        "107.5",
        runtime_config_verified=False,
        risk_limits_available=False,
    )
    assert strategy.evaluate(context) == ()
    assert strategy.state.reference_point is None


def test_track1_requires_verified_reference_exposure_and_dte_inputs() -> None:
    cases = (
        make_context("102.5", reference_verified=False),
        make_context("102.5", exposure_verified=False),
        make_context("102.5", dte_verified=False),
    )
    for strategy, context in cases:
        assert strategy.evaluate(context) == ()
        assert strategy.state.reference_point is None


def test_track1_upward_crossings_use_previous_reference_for_put_strikes() -> None:
    strategy, context = make_context("107.5", reference_point="100")
    signals = strategy.evaluate(context)

    assert [s.execution_proposal.option_type for s in signals] == ["PUT", "PUT", "PUT"]
    assert [s.execution_proposal.strike for s in signals] == [
        Decimal("92.5"), Decimal("95.0"), Decimal("97.5")
    ]
    assert all(s.execution_proposal.side == "SELL" for s in signals)
    assert strategy.state.reference_point == Decimal("107.5")


def test_track1_downward_crossings_use_previous_reference_for_call_strikes() -> None:
    strategy, context = make_context("92.5", reference_point="100")
    signals = strategy.evaluate(context)

    assert [s.execution_proposal.option_type for s in signals] == ["CALL", "CALL", "CALL"]
    assert [s.execution_proposal.strike for s in signals] == [
        Decimal("107.5"), Decimal("105.0"), Decimal("102.5")
    ]
    assert all(s.execution_proposal.side == "SELL" for s in signals)
    assert strategy.state.reference_point == Decimal("92.5")


def test_track1_short_cap_counts_open_and_pending_and_stops_extra_orders() -> None:
    strategy, context = make_context("107.5", open_short=9, pending_short=0)
    signals = strategy.evaluate(context)

    assert len(signals) == 1
    assert signals[0].execution_proposal.proposed_quantity == 1
    assert strategy.state.reference_point == Decimal("107.5")


def test_track1_full_short_cap_consumes_crossings_without_new_orders() -> None:
    strategy, context = make_context("102.5", open_short=8, pending_short=2)
    assert strategy.evaluate(context) == ()
    assert strategy.state.reference_point == Decimal("102.5")


def test_track1_dte4_or_inside_blocks_new_short_entries() -> None:
    strategy, context = make_context("102.5", dte=4)
    assert strategy.evaluate(context) == ()
    assert strategy.state.reference_point is None


def test_track1_invalid_exposure_snapshot_fails_closed() -> None:
    strategy, context = make_context("102.5", open_short=-1)
    assert strategy.evaluate(context) == ()
    assert strategy.state.reference_point is None


def test_track1_keeps_existing_reference_across_subsequent_events() -> None:
    strategy, first = make_context("102.5", reference_point="100")
    first_signals = strategy.evaluate(first)
    assert len(first_signals) == 1
    assert strategy.state.reference_point == Decimal("102.5")

    now = datetime(2026, 11, 9, 10, 1)
    second = StrategyContext(
        market_state=MarketState(
            as_of=now,
            ticks={
                "KOSPI200": CanonicalMarketTick(
                    instrument_id="KOSPI200",
                    observed_at=now,
                    price=Decimal("105"),
                )
            },
            quality={},
        ),
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=Track1Input(
            current_time=now,
            days_to_expiry=10,
            reference_point=Decimal("999"),
            reference_point_verified=True,
            open_short_quantity=1,
            pending_short_quantity=0,
            exposure_snapshot_verified=True,
            dte_basis_verified=True,
        )),
    )
    signals = strategy.evaluate(second)
    assert [s.execution_proposal.strike for s in signals] == [Decimal("95.0")]
    assert strategy.state.reference_point == Decimal("105.0")
