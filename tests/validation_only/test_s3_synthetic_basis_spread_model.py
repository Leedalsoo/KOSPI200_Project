from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import math

import pytest


@dataclass(frozen=True)
class SyntheticLeg:
    role: str
    instrument_id: str
    side: str
    quantity: int


@dataclass(frozen=True)
class SyntheticSpreadPlan:
    direction: str
    z_score: float
    legs: tuple[SyntheticLeg, SyntheticLeg]
    cash_hedge_notional_residual: Decimal


def build_synthetic_basis_plan(
    *,
    z_score: float,
    futures_identity: str,
    cash_identity: str,
    futures_price: Decimal,
    futures_multiplier: Decimal,
    cash_price: Decimal,
    cash_beta: Decimal,
    cash_unit_multiplier: Decimal = Decimal("1"),
    futures_quantity: int = 1,
    market_regime: str = "NORMAL",
    market_stable: bool = True,
    normalizing: bool = True,
    history_count: int = 60,
    futures_time: datetime | None = None,
    index_time: datetime | None = None,
) -> SyntheticSpreadPlan:
    if not math.isfinite(z_score):
        raise ValueError("S3_Z_SCORE_UNAVAILABLE")
    if history_count < 60:
        raise ValueError("S3_BASIS_WARMUP_REQUIRED")
    if market_regime != "NORMAL" or not market_stable:
        raise ValueError("S3_MARKET_REGIME_BLOCKED")
    if not normalizing:
        raise ValueError("S3_BASIS_NOT_NORMALIZING")
    if abs(z_score) < 2.0:
        raise ValueError("S3_ENTRY_THRESHOLD_NOT_MET")
    if futures_identity == cash_identity:
        raise ValueError("S3_SAME_IDENTITY_NOT_A_SPREAD")
    if not futures_identity.startswith("SYNTHETIC_CONTRACT:"):
        raise ValueError("S3_FUTURES_IDENTITY_NOT_SYNTHETIC")
    if not cash_identity.startswith("SYNTHETIC_CONTRACT:"):
        raise ValueError("S3_CASH_IDENTITY_NOT_SYNTHETIC")
    if futures_time is None or index_time is None:
        raise ValueError("S3_SOURCE_TIME_UNAVAILABLE")
    if abs((futures_time - index_time).total_seconds()) > 2:
        raise ValueError("S3_SOURCE_TIME_MISMATCH")
    if min(futures_price, futures_multiplier, cash_price, cash_beta, cash_unit_multiplier) <= 0:
        raise ValueError("S3_HEDGE_INPUT_INVALID")
    if futures_quantity <= 0:
        raise ValueError("S3_FUTURES_QUANTITY_INVALID")

    cash_target = (
        futures_price * futures_multiplier * futures_quantity
        / (cash_price * cash_beta * cash_unit_multiplier)
    )
    cash_quantity = int(cash_target.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cash_quantity <= 0:
        raise ValueError("S3_CASH_HEDGE_QUANTITY_INVALID")

    if z_score > 0:
        direction, futures_side, cash_side = "SHORT_BASIS", "SELL", "BUY"
    else:
        direction, futures_side, cash_side = "LONG_BASIS", "BUY", "SELL"

    futures_notional = futures_price * futures_multiplier * futures_quantity
    cash_notional = cash_price * cash_beta * cash_unit_multiplier * cash_quantity
    residual = cash_notional - futures_notional
    return SyntheticSpreadPlan(
        direction=direction,
        z_score=z_score,
        legs=(
            SyntheticLeg("FUTURES_SPREAD", futures_identity, futures_side, futures_quantity),
            SyntheticLeg("CASH_BASKET_HEDGE", cash_identity, cash_side, cash_quantity),
        ),
        cash_hedge_notional_residual=residual,
    )


def exit_reason(*, z_score: float, held_minutes: float) -> str | None:
    if not math.isfinite(z_score) or held_minutes < 0:
        raise ValueError("S3_EXIT_INPUT_INVALID")
    if abs(z_score) >= 3.5:
        return "STOP"
    if abs(z_score) <= 0.5:
        return "CONVERGENCE"
    if held_minutes >= 60:
        return "TIMEOUT"
    return None


def group_state(*, futures_filled: int, cash_filled: int,
                futures_requested: int, cash_requested: int) -> str:
    if min(futures_filled, cash_filled) < 0:
        raise ValueError("S3_FILL_QUANTITY_INVALID")
    if futures_filled > futures_requested or cash_filled > cash_requested:
        raise ValueError("S3_OVERFILL")
    if futures_filled == futures_requested and cash_filled == cash_requested:
        return "ACTIVE"
    if futures_filled or cash_filled:
        return "PARTIALLY_EXPOSED"
    return "ENTRY_WORKING"


def spread_net_pnl(
    *,
    direction: str,
    futures_entry: Decimal,
    futures_exit: Decimal,
    futures_multiplier: Decimal,
    futures_quantity: int,
    cash_entry: Decimal,
    cash_exit: Decimal,
    cash_unit_multiplier: Decimal,
    cash_quantity: int,
    total_fees: Decimal,
    total_slippage: Decimal,
) -> Decimal:
    if direction == "SHORT_BASIS":
        gross = (
            (futures_entry - futures_exit) * futures_multiplier * futures_quantity
            + (cash_exit - cash_entry) * cash_unit_multiplier * cash_quantity
        )
    elif direction == "LONG_BASIS":
        gross = (
            (futures_exit - futures_entry) * futures_multiplier * futures_quantity
            + (cash_entry - cash_exit) * cash_unit_multiplier * cash_quantity
        )
    else:
        raise ValueError("S3_DIRECTION_INVALID")
    return gross - total_fees - total_slippage


def _times(delta_seconds: int = 0):
    t0 = datetime(2026, 11, 23, 9, 0, 0)
    return t0, t0 + timedelta(seconds=delta_seconds)


def _plan(z: float = 2.5, **overrides):
    t0, t1 = _times()
    args = dict(
        z_score=z,
        futures_identity="SYNTHETIC_CONTRACT:KOSPI200_FUTURES_NEAR",
        cash_identity="SYNTHETIC_CONTRACT:KOSPI200_CASH_BASKET",
        futures_price=Decimal("1075"),
        futures_multiplier=Decimal("250000"),
        cash_price=Decimal("50000"),
        cash_beta=Decimal("1"),
        cash_unit_multiplier=Decimal("1"),
        futures_quantity=1,
        market_regime="NORMAL",
        market_stable=True,
        normalizing=True,
        history_count=60,
        futures_time=t0,
        index_time=t1,
    )
    args.update(overrides)
    return build_synthetic_basis_plan(**args)


def test_positive_basis_enters_short_futures_long_cash_proxy():
    plan = _plan(2.5)
    assert plan.direction == "SHORT_BASIS"
    assert [(x.role, x.side) for x in plan.legs] == [
        ("FUTURES_SPREAD", "SELL"), ("CASH_BASKET_HEDGE", "BUY")
    ]


def test_negative_basis_enters_long_futures_short_cash_proxy():
    plan = _plan(-2.5)
    assert plan.direction == "LONG_BASIS"
    assert [x.side for x in plan.legs] == ["BUY", "SELL"]


def test_hedge_quantity_is_notional_beta_adjusted():
    plan = _plan(2.5)
    assert plan.legs[1].quantity == 5375
    assert abs(plan.cash_hedge_notional_residual) <= Decimal("25000")


def test_same_identity_is_rejected():
    with pytest.raises(ValueError, match="S3_SAME_IDENTITY_NOT_A_SPREAD"):
        _plan(2.5, cash_identity="SYNTHETIC_CONTRACT:KOSPI200_FUTURES_NEAR")


def test_non_synthetic_identity_is_rejected():
    with pytest.raises(ValueError, match="S3_CASH_IDENTITY_NOT_SYNTHETIC"):
        _plan(2.5, cash_identity="KODEX200_REAL_SYMBOL")


def test_warmup_shortfall_is_unavailable():
    with pytest.raises(ValueError, match="S3_BASIS_WARMUP_REQUIRED"):
        _plan(2.5, history_count=59)


def test_high_volatility_blocks_entry():
    with pytest.raises(ValueError, match="S3_MARKET_REGIME_BLOCKED"):
        _plan(2.5, market_regime="HIGH_VOLATILITY")


def test_unstable_market_blocks_entry():
    with pytest.raises(ValueError, match="S3_MARKET_REGIME_BLOCKED"):
        _plan(2.5, market_stable=False)


def test_non_normalizing_basis_blocks_entry():
    with pytest.raises(ValueError, match="S3_BASIS_NOT_NORMALIZING"):
        _plan(2.5, normalizing=False)


def test_entry_threshold_is_two_sigma():
    with pytest.raises(ValueError, match="S3_ENTRY_THRESHOLD_NOT_MET"):
        _plan(1.999)


def test_source_pairing_over_two_seconds_is_rejected():
    t0, t1 = _times(3)
    with pytest.raises(ValueError, match="S3_SOURCE_TIME_MISMATCH"):
        _plan(2.5, futures_time=t0, index_time=t1)


def test_missing_source_time_is_rejected():
    with pytest.raises(ValueError, match="S3_SOURCE_TIME_UNAVAILABLE"):
        _plan(2.5, index_time=None)


def test_nonpositive_beta_or_multiplier_is_rejected():
    with pytest.raises(ValueError, match="S3_HEDGE_INPUT_INVALID"):
        _plan(2.5, cash_beta=Decimal("0"))


def test_nonfinite_z_score_is_rejected():
    with pytest.raises(ValueError, match="S3_Z_SCORE_UNAVAILABLE"):
        _plan(float("nan"))


def test_convergence_stop_and_timeout_priorities():
    assert exit_reason(z_score=0.4, held_minutes=5) == "CONVERGENCE"
    assert exit_reason(z_score=3.5, held_minutes=5) == "STOP"
    assert exit_reason(z_score=1.0, held_minutes=60) == "TIMEOUT"
    assert exit_reason(z_score=1.0, held_minutes=59.9) is None


def test_stop_has_priority_over_timeout():
    assert exit_reason(z_score=3.8, held_minutes=60) == "STOP"


def test_one_leg_fill_is_partially_exposed_not_active():
    assert group_state(
        futures_filled=1, cash_filled=0,
        futures_requested=1, cash_requested=5375,
    ) == "PARTIALLY_EXPOSED"


def test_both_legs_fully_filled_are_active():
    assert group_state(
        futures_filled=1, cash_filled=5375,
        futures_requested=1, cash_requested=5375,
    ) == "ACTIVE"


def test_no_fills_remains_entry_working():
    assert group_state(
        futures_filled=0, cash_filled=0,
        futures_requested=1, cash_requested=5375,
    ) == "ENTRY_WORKING"


def test_overfill_is_rejected():
    with pytest.raises(ValueError, match="S3_OVERFILL"):
        group_state(
            futures_filled=2, cash_filled=0,
            futures_requested=1, cash_requested=5375,
        )


def test_short_basis_net_pnl_includes_costs():
    pnl = spread_net_pnl(
        direction="SHORT_BASIS",
        futures_entry=Decimal("1075"), futures_exit=Decimal("1074"),
        futures_multiplier=Decimal("250000"), futures_quantity=1,
        cash_entry=Decimal("50000"), cash_exit=Decimal("50010"),
        cash_unit_multiplier=Decimal("1"), cash_quantity=5375,
        total_fees=Decimal("10000"), total_slippage=Decimal("5000"),
    )
    assert pnl == Decimal("288750")


def test_cost_stress_can_turn_gross_profit_into_net_loss():
    pnl = spread_net_pnl(
        direction="SHORT_BASIS",
        futures_entry=Decimal("1075"), futures_exit=Decimal("1074.9"),
        futures_multiplier=Decimal("250000"), futures_quantity=1,
        cash_entry=Decimal("50000"), cash_exit=Decimal("50000.1"),
        cash_unit_multiplier=Decimal("1"), cash_quantity=5375,
        total_fees=Decimal("50000"), total_slippage=Decimal("25000"),
    )
    assert pnl < 0
