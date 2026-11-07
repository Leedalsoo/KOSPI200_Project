"""Pure, fail-closed policy kernel for the independent S9 overnight strangle.

This module contains only approved P0 decisions. It does not submit orders,
resolve broker identities, or authorize a Runtime/Live execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Iterable, Literal

OptionSide = Literal["PUT", "CALL"]


class Track9PolicyBlocked(ValueError):
    """Raised when authoritative inputs cannot determine one safe policy result."""


@dataclass(frozen=True)
class Track9OptionCandidate:
    symbol: str
    expiry: date
    option_type: OptionSide
    strike: Decimal
    instrument_family: str
    contract_multiplier: Decimal | None
    tradable: bool | None


@dataclass(frozen=True)
class Track9AtmPair:
    expiry: date
    strike: Decimal
    put: Track9OptionCandidate
    call: Track9OptionCandidate
    contract_multiplier: Decimal


@dataclass(frozen=True)
class Track9OpeningDecision:
    move: Decimal
    action: Literal["CLOSE_INSURANCE", "STOP_LOSS"]


ENTRY_EVALUATION_TIME = time(15, 0)
OPENING_MOVE_THRESHOLD = Decimal("0.01")


def select_nearest_expiry_atm_pair(
    contracts: Iterable[Track9OptionCandidate],
    *,
    underlying_price: Decimal,
    as_of_date: date,
) -> Track9AtmPair:
    """Select same-expiry, same-strike standard PUT/CALL at the nearest valid expiry.

    Missing tradeability, multiplier, duplicate contracts, or an ATM strike tie
    blocks selection instead of guessing.
    """
    if underlying_price <= 0:
        raise Track9PolicyBlocked("TRACK9_UNDERLYING_PRICE_INVALID")

    candidates = tuple(contracts)
    if any(item.tradable is None for item in candidates):
        raise Track9PolicyBlocked("TRACK9_TRADEABILITY_UNVERIFIED")

    eligible = tuple(
        item for item in candidates
        if item.tradable is True
        and item.instrument_family == "STANDARD"
        and item.expiry >= as_of_date
        and item.symbol
        and item.strike > 0
    )
    if not eligible:
        raise Track9PolicyBlocked("TRACK9_NO_TRADABLE_STANDARD_OPTIONS")

    nearest_expiry = min(item.expiry for item in eligible)
    expiry_contracts = tuple(item for item in eligible if item.expiry == nearest_expiry)

    pairs: dict[Decimal, dict[str, list[Track9OptionCandidate]]] = {}
    for item in expiry_contracts:
        if item.option_type not in ("PUT", "CALL"):
            continue
        pairs.setdefault(item.strike, {"PUT": [], "CALL": []})[item.option_type].append(item)

    complete_strikes = tuple(
        strike for strike, sides in pairs.items()
        if len(sides["PUT"]) == 1 and len(sides["CALL"]) == 1
    )
    if not complete_strikes:
        raise Track9PolicyBlocked("TRACK9_SAME_EXPIRY_PUT_CALL_PAIR_UNAVAILABLE")

    distances = {strike: abs(strike - underlying_price) for strike in complete_strikes}
    minimum_distance = min(distances.values())
    nearest_strikes = tuple(
        strike for strike, distance in distances.items() if distance == minimum_distance
    )
    if len(nearest_strikes) != 1:
        raise Track9PolicyBlocked("TRACK9_ATM_STRIKE_TIE_UNRESOLVED")

    strike = nearest_strikes[0]
    put = pairs[strike]["PUT"][0]
    call = pairs[strike]["CALL"][0]
    if put.contract_multiplier is None or call.contract_multiplier is None:
        raise Track9PolicyBlocked("TRACK9_CONTRACT_MULTIPLIER_UNAVAILABLE")
    if put.contract_multiplier <= 0 or call.contract_multiplier <= 0:
        raise Track9PolicyBlocked("TRACK9_CONTRACT_MULTIPLIER_INVALID")
    if put.contract_multiplier != call.contract_multiplier:
        raise Track9PolicyBlocked("TRACK9_PUT_CALL_MULTIPLIER_MISMATCH")

    return Track9AtmPair(
        expiry=nearest_expiry,
        strike=strike,
        put=put,
        call=call,
        contract_multiplier=put.contract_multiplier,
    )


def is_track9_entry_evaluation_time(value: time) -> bool:
    """S9 evaluates entry once at exactly 15:00 KST; no late catch-up."""
    return value == ENTRY_EVALUATION_TIME


def evaluate_track9_opening_move(
    *,
    previous_official_close: Decimal | None,
    next_session_official_open: Decimal | None,
) -> Track9OpeningDecision:
    """Apply the approved official-close to next-session-official-open rule."""
    if previous_official_close is None or next_session_official_open is None:
        raise Track9PolicyBlocked("TRACK9_OFFICIAL_OPEN_CLOSE_UNAVAILABLE")
    if previous_official_close <= 0 or next_session_official_open <= 0:
        raise Track9PolicyBlocked("TRACK9_OFFICIAL_OPEN_CLOSE_INVALID")

    move = (next_session_official_open - previous_official_close) / previous_official_close
    action = (
        "CLOSE_INSURANCE"
        if abs(move) >= OPENING_MOVE_THRESHOLD
        else "STOP_LOSS"
    )
    return Track9OpeningDecision(move=move, action=action)


__all__ = (
    "ENTRY_EVALUATION_TIME",
    "OPENING_MOVE_THRESHOLD",
    "Track9AtmPair",
    "Track9OpeningDecision",
    "Track9OptionCandidate",
    "Track9PolicyBlocked",
    "evaluate_track9_opening_move",
    "is_track9_entry_evaluation_time",
    "select_nearest_expiry_atm_pair",
)
