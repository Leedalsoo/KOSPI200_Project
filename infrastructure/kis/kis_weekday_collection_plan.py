from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Sequence

from infrastructure.krx.krx_marketplace_master import load_option_master


KST = timezone(timedelta(hours=9))
OPTION_TRADE_TR_ID = "H0IOCNT0"
FUTURES_TRADE_TR_ID = "H0IFCNT0"
FUTURES_QUOTE_TR_ID = "H0IFASP0"
MAX_SUBSCRIPTIONS = 41

# The strategies currently require offsets from ATM through ±15 points.
STRATEGY_MONTHLY_OFFSETS = (
    Decimal("-15.0"),
    Decimal("-12.5"),
    Decimal("-10.0"),
    Decimal("-7.5"),
    Decimal("-5.0"),
    Decimal("-2.5"),
    Decimal("0.0"),
    Decimal("2.5"),
    Decimal("5.0"),
    Decimal("7.5"),
    Decimal("10.0"),
    Decimal("12.5"),
    Decimal("15.0"),
)


@dataclass(frozen=True)
class CollectionWindow:
    start: date
    end: date


@dataclass(frozen=True)
class CollectionPlan:
    subscriptions: tuple[tuple[str, str], ...]
    monthly_expiry: str
    weekly_expiry: str
    monthly_strikes: tuple[Decimal, ...]
    weekly_strikes: tuple[Decimal, ...]
    standard_futures_symbol: str
    mini_futures_symbol: str


def _nearest_strike(price: Decimal) -> Decimal:
    return (price / Decimal("2.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("2.5")


def _next_expiry(identities: Sequence[object], as_of: date, *, strictly_after: bool = False) -> str:
    expiries = sorted(
        {
            identity.expiry
            for identity in identities
            if identity.expiry
            and (
                date.fromisoformat(identity.expiry) > as_of
                if strictly_after
                else date.fromisoformat(identity.expiry) >= as_of
            )
        }
    )
    if not expiries:
        raise ValueError("NO_LISTED_OPTION_EXPIRY_AVAILABLE")
    return expiries[0]


def _find_option(
    identities: Sequence[object],
    *,
    expiry: str,
    option_type: str,
    strike: Decimal,
) -> str:
    matches = [
        identity
        for identity in identities
        if identity.expiry == expiry
        and identity.option_type == option_type
        and identity.strike == strike
        and identity.contract_multiplier == Decimal("250000")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"AUTHORITATIVE_OPTION_IDENTITY_REQUIRED:{expiry}:{option_type}:{strike}:{len(matches)}"
        )
    return matches[0].shrn_iscd


def build_collection_plan(
    *,
    reference_price: Decimal,
    option_master_paths: Sequence[str | Path],
    weekly_master_paths: Sequence[str | Path],
    standard_futures_symbol: str,
    mini_futures_symbol: str,
    as_of: date,
) -> CollectionPlan:
    monthly_master = load_option_master(option_master_paths)
    weekly_master = load_option_master(weekly_master_paths)

    monthly_identities = tuple(monthly_master.identities.values())
    weekly_identities = tuple(weekly_master.identities.values())

    monthly_expiry = _next_expiry(monthly_identities, as_of)
    weekly_expiry = _next_expiry(weekly_identities, as_of)

    atm = _nearest_strike(Decimal(reference_price))
    monthly_strikes = tuple(atm + offset for offset in STRATEGY_MONTHLY_OFFSETS)

    # Track7 is the only strategy whose current contract rule is explicitly
    # weekly; it needs the listed ATM±15 CALL/PUT pair.
    weekly_strikes = (atm - Decimal("15.0"), atm + Decimal("15.0"))

    subscriptions: list[tuple[str, str]] = []
    for strike in monthly_strikes:
        subscriptions.append(
            (OPTION_TRADE_TR_ID, _find_option(
                monthly_identities, expiry=monthly_expiry, option_type="PUT", strike=strike
            ))
        )
        subscriptions.append(
            (OPTION_TRADE_TR_ID, _find_option(
                monthly_identities, expiry=monthly_expiry, option_type="CALL", strike=strike
            ))
        )

    for strike in weekly_strikes:
        subscriptions.append(
            (OPTION_TRADE_TR_ID, _find_option(
                weekly_identities, expiry=weekly_expiry, option_type="PUT", strike=strike
            ))
        )
        subscriptions.append(
            (OPTION_TRADE_TR_ID, _find_option(
                weekly_identities, expiry=weekly_expiry, option_type="CALL", strike=strike
            ))
        )

    subscriptions.extend(
        (
            (FUTURES_TRADE_TR_ID, standard_futures_symbol),
            (FUTURES_QUOTE_TR_ID, standard_futures_symbol),
            (FUTURES_TRADE_TR_ID, mini_futures_symbol),
            (FUTURES_QUOTE_TR_ID, mini_futures_symbol),
        )
    )

    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise ValueError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")

    return CollectionPlan(
        subscriptions=tuple(subscriptions),
        monthly_expiry=monthly_expiry,
        weekly_expiry=weekly_expiry,
        monthly_strikes=monthly_strikes,
        weekly_strikes=weekly_strikes,
        standard_futures_symbol=standard_futures_symbol,
        mini_futures_symbol=mini_futures_symbol,
    )


def is_collection_day(day: date, window: CollectionWindow) -> bool:
    return window.start <= day <= window.end and day.weekday() < 5


def should_stop(now_iso: str, window: CollectionWindow) -> bool:
    now = datetime.fromisoformat(now_iso)
    if now.tzinfo is None:
        raise ValueError("STOP_CLOCK_MUST_BE_TIMEZONE_AWARE")
    return now.astimezone(KST).date() > window.end or (
        now.astimezone(KST).date() == window.end
        and now.astimezone(KST).time().isoformat() >= "23:59:59"
    )
