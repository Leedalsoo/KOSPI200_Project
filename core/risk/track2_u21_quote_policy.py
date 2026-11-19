from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
import re

class QuoteDecision(str, Enum):
    POLICY_INPUT_BLOCKED = "POLICY_INPUT_BLOCKED"
    PRIMARY_QUOTE_ACCEPTED = "PRIMARY_QUOTE_ACCEPTED"
    FALLBACK_QUOTE_ACCEPTED = "FALLBACK_QUOTE_ACCEPTED"
    FALLBACK_UNAVAILABLE_BLOCKED = "FALLBACK_UNAVAILABLE_BLOCKED"

class QuoteSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass(frozen=True)
class U21Quote:
    instrument_id: str
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    observed_at: datetime | None
    source_time_semantics_verified: bool
    capability_verified: bool
    source: str | None
    raw_payload_sha256: str | None

def _finite_decimal(value) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


@dataclass(frozen=True)
class U21QuotePolicy:
    max_age_seconds: Decimal | None = None
    max_spread: Decimal | None = None
    spread_measure: str | None = None
    fallback_formula: str | None = None
    fallback_priority: str | None = None
    tick_size: Decimal | None = None
    tick_rounding: str | None = None
    approved: bool = False

    def resolved(self) -> bool:
        return bool(
            self.approved
            and _finite_decimal(self.max_age_seconds) and self.max_age_seconds > 0
            and _finite_decimal(self.max_spread) and self.max_spread >= 0
            and self.spread_measure in {"ABSOLUTE", "RELATIVE_MID"}
            and self.fallback_formula == "CONSERVATIVE_EXECUTABLE_SIDE"
            and self.fallback_priority == "ALTERNATE_SOURCE_ONLY"
            and _finite_decimal(self.tick_size) and self.tick_size > 0
            and self.tick_rounding == "BUY_CEILING_SELL_FLOOR"
        )

@dataclass(frozen=True)
class U21QuoteResult:
    decision: QuoteDecision
    reason: str
    price: Decimal | None = None
    source: str | None = None
    spread_value: Decimal | None = None
    fallback_used: bool = False
    order_submission_enabled: bool = False

def _quote_problem(quote, *, now, policy, expected_instrument_id, expected_symbol):
    if quote is None:
        return "QUOTE_MISSING", None
    if quote.instrument_id != expected_instrument_id or quote.symbol != expected_symbol:
        return "QUOTE_IDENTITY_MISMATCH", None
    if (
        not isinstance(quote.bid, Decimal) or not isinstance(quote.ask, Decimal)
        or not quote.bid.is_finite() or not quote.ask.is_finite()
        or quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid
    ):
        return "BID_ASK_MISSING_OR_INVALID", None
    if (
        not isinstance(quote.observed_at, datetime) or quote.observed_at.tzinfo is None
        or quote.observed_at.utcoffset() is None
        or now.tzinfo is None or now.utcoffset() is None
    ):
        return "QUOTE_TIMESTAMP_UNVERIFIED", None
    if not quote.source_time_semantics_verified or not quote.capability_verified:
        return "SOURCE_TIME_OR_CAPABILITY_UNVERIFIED", None
    if (
        not isinstance(quote.source, str) or not quote.source.strip()
        or not isinstance(quote.raw_payload_sha256, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", quote.raw_payload_sha256)
    ):
        return "QUOTE_PROVENANCE_INCOMPLETE", None
    age = (now - quote.observed_at).total_seconds()
    if age < 0:
        return "QUOTE_TIMESTAMP_IN_FUTURE", None
    if Decimal(str(age)) > policy.max_age_seconds:
        return "QUOTE_STALE", None
    spread = quote.ask - quote.bid
    if policy.spread_measure == "RELATIVE_MID":
        mid = (quote.ask + quote.bid) / Decimal("2")
        if mid <= 0:
            return "QUOTE_MID_INVALID", None
        spread = spread / mid
    if spread > policy.max_spread:
        return "SPREAD_EXCEEDS_LIMIT", spread
    return None, spread

def _conservative_price(quote, side, policy):
    raw = quote.ask if side is QuoteSide.BUY else quote.bid
    units = raw / policy.tick_size
    rounding = ROUND_CEILING if side is QuoteSide.BUY else ROUND_FLOOR
    return units.to_integral_value(rounding=rounding) * policy.tick_size

def evaluate_u21_quote(*, primary, fallback, side, now, policy, expected_instrument_id, expected_symbol):
    if (
        not isinstance(side, QuoteSide)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not isinstance(policy, U21QuotePolicy)
        or not isinstance(expected_instrument_id, str) or not expected_instrument_id.strip()
        or not isinstance(expected_symbol, str) or not expected_symbol.strip()
    ):
        return U21QuoteResult(QuoteDecision.POLICY_INPUT_BLOCKED, "U21_EVALUATION_CONTEXT_UNVERIFIED")
    if not policy.resolved():
        return U21QuoteResult(QuoteDecision.POLICY_INPUT_BLOCKED, "U21_POLICY_UNRESOLVED_NULL_DEFAULT")
    problem, spread = _quote_problem(
        primary, now=now, policy=policy,
        expected_instrument_id=expected_instrument_id, expected_symbol=expected_symbol,
    )
    if problem is None:
        return U21QuoteResult(
            QuoteDecision.PRIMARY_QUOTE_ACCEPTED,
            "PRIMARY_QUOTE_WITHIN_EXPLICIT_VALIDATION_POLICY",
            _conservative_price(primary, side, policy), primary.source, spread, False, False,
        )
    fallback_problem, fallback_spread = _quote_problem(
        fallback, now=now, policy=policy,
        expected_instrument_id=expected_instrument_id, expected_symbol=expected_symbol,
    )
    if (
        fallback_problem is None
        and primary is not None
        and (
            not isinstance(primary.source, str)
            or not primary.source.strip()
            or fallback.source == primary.source
        )
    ):
        fallback_problem = "FALLBACK_SOURCE_NOT_INDEPENDENT"
    if fallback_problem is not None:
        return U21QuoteResult(
            QuoteDecision.FALLBACK_UNAVAILABLE_BLOCKED,
            f"PRIMARY_{problem};FALLBACK_{fallback_problem}",
            spread_value=fallback_spread, order_submission_enabled=False,
        )
    return U21QuoteResult(
        QuoteDecision.FALLBACK_QUOTE_ACCEPTED,
        f"PRIMARY_{problem};ALTERNATE_SOURCE_VALID",
        _conservative_price(fallback, side, policy), fallback.source, fallback_spread, True, False,
    )
