from datetime import date, time
from decimal import Decimal

import pytest

from core.strategy.track9_independent_policy import (
    Track9OptionCandidate,
    Track9PolicyBlocked,
    evaluate_track9_opening_move,
    is_track9_entry_evaluation_time,
    select_nearest_expiry_atm_pair,
)


def contract(symbol, expiry, side, strike, *, multiplier=Decimal("250000"), tradable=True, family="STANDARD"):
    return Track9OptionCandidate(
        symbol=symbol,
        expiry=date.fromisoformat(expiry),
        option_type=side,
        strike=Decimal(str(strike)),
        instrument_family=family,
        contract_multiplier=multiplier,
        tradable=tradable,
    )


def test_selects_nearest_tradable_expiry_and_same_strike_standard_pair():
    items = [
        contract("P1", "2026-11-12", "PUT", "500", family="STANDARD"),
        contract("C1", "2026-11-12", "CALL", "500", family="STANDARD"),
        contract("P2", "2026-11-19", "PUT", "500"),
        contract("C2", "2026-11-19", "CALL", "500"),
        contract("PM", "2026-11-10", "PUT", "500", family="MINI"),
        contract("CM", "2026-11-10", "CALL", "500", family="MINI"),
    ]
    pair = select_nearest_expiry_atm_pair(
        items, underlying_price=Decimal("501"), as_of_date=date(2026, 11, 9)
    )
    assert pair.expiry == date(2026, 11, 12)
    assert pair.strike == Decimal("500")
    assert pair.put.symbol == "P1"
    assert pair.call.symbol == "C1"


def test_blocks_atm_distance_tie_instead_of_inventing_tie_break():
    items = [
        contract("P499", "2026-11-12", "PUT", "499"),
        contract("C499", "2026-11-12", "CALL", "499"),
        contract("P501", "2026-11-12", "PUT", "501"),
        contract("C501", "2026-11-12", "CALL", "501"),
    ]
    with pytest.raises(Track9PolicyBlocked, match="ATM_STRIKE_TIE_UNRESOLVED"):
        select_nearest_expiry_atm_pair(
            items, underlying_price=Decimal("500"), as_of_date=date(2026, 11, 9)
        )


def test_blocks_unverified_tradeability_or_multiplier():
    unknown_tradeability = [
        contract("P", "2026-11-12", "PUT", "500", tradable=None),
        contract("C", "2026-11-12", "CALL", "500", tradable=None),
    ]
    with pytest.raises(Track9PolicyBlocked, match="TRADEABILITY_UNVERIFIED"):
        select_nearest_expiry_atm_pair(
            unknown_tradeability, underlying_price=Decimal("500"), as_of_date=date(2026, 11, 9)
        )

    missing_multiplier = [
        contract("P", "2026-11-12", "PUT", "500", multiplier=None),
        contract("C", "2026-11-12", "CALL", "500", multiplier=None),
    ]
    with pytest.raises(Track9PolicyBlocked, match="MULTIPLIER_UNAVAILABLE"):
        select_nearest_expiry_atm_pair(
            missing_multiplier, underlying_price=Decimal("500"), as_of_date=date(2026, 11, 9)
        )


def test_entry_evaluation_is_exactly_1500():
    assert is_track9_entry_evaluation_time(time(15, 0))
    assert not is_track9_entry_evaluation_time(time(15, 0, 1))
    assert not is_track9_entry_evaluation_time(time(15, 10))


@pytest.mark.parametrize(
    ("opening", "expected"),
    [
        ("101", "CLOSE_INSURANCE"),
        ("99", "CLOSE_INSURANCE"),
        ("100.999", "STOP_LOSS"),
        ("99.001", "STOP_LOSS"),
    ],
)
def test_opening_move_uses_official_close_open_and_exact_one_percent_boundary(opening, expected):
    result = evaluate_track9_opening_move(
        previous_official_close=Decimal("100"),
        next_session_official_open=Decimal(opening),
    )
    assert result.action == expected


def test_missing_official_open_or_close_fails_closed():
    with pytest.raises(Track9PolicyBlocked, match="OFFICIAL_OPEN_CLOSE_UNAVAILABLE"):
        evaluate_track9_opening_move(
            previous_official_close=Decimal("100"),
            next_session_official_open=None,
        )
