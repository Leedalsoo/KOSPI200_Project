"""Pure policy kernel and typed runtime inputs for independent S9 overnight insurance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Iterable, Literal

OptionSide = Literal["PUT", "CALL"]


class Track9PolicyBlocked(ValueError):
    """Raised when inputs cannot determine one safe policy result."""


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


@dataclass(frozen=True)
class Track9SyntheticQuote:
    instrument_id: str
    option_type: str
    strike: Decimal
    expiry: date
    bid: Decimal
    ask: Decimal
    last: Decimal
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class Track9OpenLot:
    strategy_id: str
    instrument_id: str
    expiry: date
    option_type: str
    strike: Decimal
    remaining_quantity: int
    side: str
    entry_price: Decimal
    contract_multiplier: Decimal
    executed_at: datetime


@dataclass(frozen=True)
class Track9RuntimeInput:
    """Manifest-bound runtime inputs; every field retains its source classification."""
    contract_candidates: tuple[Track9OptionCandidate, ...]
    underlying_price: Decimal
    as_of: datetime
    previous_official_close: Decimal | None
    next_session_official_open: Decimal | None
    option_quotes: tuple[Track9SyntheticQuote, ...]
    open_lots: tuple[Track9OpenLot, ...]
    provenance: str
    source_provenance: tuple[tuple[str, str], ...]
    scenario_id: str
    manifest_sha256: str
    dataset_sha256: str
    contract_profile_sha256: str
    risk_profile_sha256: str
    max_quote_age_seconds: Decimal


ENTRY_EVALUATION_TIME = time(15, 0)
OPENING_MOVE_THRESHOLD = Decimal("0.01")


def select_nearest_expiry_atm_pair(
    contracts: Iterable[Track9OptionCandidate], *, underlying_price: Decimal, as_of_date: date,
) -> Track9AtmPair:
    """Select same-expiry, same-strike standard PUT/CALL at nearest valid expiry."""
    underlying_price = Decimal(str(underlying_price))
    if not underlying_price.is_finite() or underlying_price <= 0:
        raise Track9PolicyBlocked("TRACK9_UNDERLYING_PRICE_INVALID")
    candidates = tuple(contracts)
    if any(item.tradable is None for item in candidates):
        raise Track9PolicyBlocked("TRACK9_TRADEABILITY_UNVERIFIED")
    eligible = tuple(item for item in candidates if item.tradable is True
                     and item.instrument_family == "STANDARD" and item.expiry >= as_of_date
                     and item.symbol and item.strike > 0)
    if not eligible:
        raise Track9PolicyBlocked("TRACK9_NO_TRADABLE_STANDARD_OPTIONS")
    nearest_expiry = min(item.expiry for item in eligible)
    expiry_contracts = tuple(item for item in eligible if item.expiry == nearest_expiry)
    pairs: dict[Decimal, dict[str, list[Track9OptionCandidate]]] = {}
    for item in expiry_contracts:
        if item.option_type in ("PUT", "CALL"):
            pairs.setdefault(item.strike, {"PUT": [], "CALL": []})[item.option_type].append(item)
    complete = tuple(strike for strike, sides in pairs.items()
                     if len(sides["PUT"]) == 1 and len(sides["CALL"]) == 1)
    if not complete:
        raise Track9PolicyBlocked("TRACK9_SAME_EXPIRY_PUT_CALL_PAIR_UNAVAILABLE")
    distances = {strike: abs(strike - underlying_price) for strike in complete}
    nearest_distance = min(distances.values())
    nearest = tuple(strike for strike, distance in distances.items() if distance == nearest_distance)
    if len(nearest) != 1:
        raise Track9PolicyBlocked("TRACK9_ATM_STRIKE_TIE_UNRESOLVED")
    strike = nearest[0]
    put, call = pairs[strike]["PUT"][0], pairs[strike]["CALL"][0]
    if put.contract_multiplier is None or call.contract_multiplier is None:
        raise Track9PolicyBlocked("TRACK9_CONTRACT_MULTIPLIER_UNAVAILABLE")
    if put.contract_multiplier <= 0 or call.contract_multiplier <= 0:
        raise Track9PolicyBlocked("TRACK9_CONTRACT_MULTIPLIER_INVALID")
    if put.contract_multiplier != call.contract_multiplier:
        raise Track9PolicyBlocked("TRACK9_PUT_CALL_MULTIPLIER_MISMATCH")
    return Track9AtmPair(nearest_expiry, strike, put, call, put.contract_multiplier)


def is_track9_entry_evaluation_time(value: time) -> bool:
    return value == ENTRY_EVALUATION_TIME


def evaluate_track9_opening_move(*, previous_official_close: Decimal | None,
                                 next_session_official_open: Decimal | None) -> Track9OpeningDecision:
    if previous_official_close is None or next_session_official_open is None:
        raise Track9PolicyBlocked("TRACK9_OFFICIAL_OPEN_CLOSE_UNAVAILABLE")
    previous = Decimal(str(previous_official_close))
    opening = Decimal(str(next_session_official_open))
    if not previous.is_finite() or not opening.is_finite() or previous <= 0 or opening <= 0:
        raise Track9PolicyBlocked("TRACK9_OFFICIAL_OPEN_CLOSE_INVALID")
    move = (opening - previous) / previous
    return Track9OpeningDecision(move, "CLOSE_INSURANCE" if abs(move) >= OPENING_MOVE_THRESHOLD else "STOP_LOSS")


__all__ = (
    "ENTRY_EVALUATION_TIME", "OPENING_MOVE_THRESHOLD", "Track9AtmPair", "Track9OpenLot",
    "Track9OpeningDecision", "Track9OptionCandidate", "Track9PolicyBlocked", "Track9RuntimeInput",
    "Track9SyntheticQuote", "evaluate_track9_opening_move", "is_track9_entry_evaluation_time",
    "select_nearest_expiry_atm_pair",
)
