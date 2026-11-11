from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest
from core.risk.track2_u21_quote_policy import QuoteDecision, QuoteSide, U21Quote, U21QuotePolicy, evaluate_u21_quote

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))

def quote(*, bid="1.00", ask="1.10", age=1, source="SYNTHETIC:primary", symbol="OPT1", instrument_id="STD1", semantics=True, capability=True, digest="a"):
    return U21Quote(instrument_id, symbol, Decimal(bid) if bid is not None else None,
                    Decimal(ask) if ask is not None else None,
                    NOW - timedelta(seconds=age) if age is not None else None,
                    semantics, capability, source, digest * 64 if digest else None)

def policy(**overrides):
    values = dict(max_age_seconds=Decimal("5"), max_spread=Decimal("0.20"),
        spread_measure="ABSOLUTE", fallback_formula="CONSERVATIVE_EXECUTABLE_SIDE",
        fallback_priority="ALTERNATE_SOURCE_ONLY", tick_size=Decimal("0.05"),
        tick_rounding="BUY_CEILING_SELL_FLOOR", approved=True)
    values.update(overrides)
    return U21QuotePolicy(**values)

def run(primary, fallback=None, side=QuoteSide.BUY, p=None):
    return evaluate_u21_quote(primary=primary, fallback=fallback, side=side, now=NOW,
        policy=p or policy(), expected_instrument_id="STD1", expected_symbol="OPT1")

def test_null_policy_defaults_block():
    result = run(quote(), p=U21QuotePolicy())
    assert result.decision is QuoteDecision.POLICY_INPUT_BLOCKED
    assert not result.order_submission_enabled

@pytest.mark.parametrize("field", [
    {"max_age_seconds": None}, {"max_spread": None}, {"spread_measure": None},
    {"fallback_formula": None}, {"fallback_priority": None}, {"tick_size": None},
    {"tick_rounding": None}, {"approved": False},
])
def test_each_missing_u21_policy_input_blocks(field):
    assert run(quote(), p=policy(**field)).decision is QuoteDecision.POLICY_INPUT_BLOCKED

def test_fresh_primary_quote_uses_conservative_ask_and_buy_tick_ceiling():
    result = run(quote(bid="1.00", ask="1.11"))
    assert result.decision is QuoteDecision.PRIMARY_QUOTE_ACCEPTED
    assert result.price == Decimal("1.15")
    assert not result.fallback_used and not result.order_submission_enabled

def test_sell_uses_conservative_bid_and_tick_floor():
    result = run(quote(bid="1.04", ask="1.10"), side=QuoteSide.SELL)
    assert result.price == Decimal("1.00")

@pytest.mark.parametrize("primary", [
    None, quote(bid=None), quote(age=6), quote(semantics=False), quote(capability=False),
    quote(symbol="OTHER"), quote(digest=None), quote(bid="1.00", ask="1.50"),
])
def test_missing_stale_unverified_identity_or_wide_quote_uses_valid_alternate(primary):
    result = run(primary, fallback=quote(source="SYNTHETIC:alternate"))
    assert result.decision is QuoteDecision.FALLBACK_QUOTE_ACCEPTED
    assert result.fallback_used and result.source == "SYNTHETIC:alternate"
    assert not result.order_submission_enabled

@pytest.mark.parametrize("fallback", [
    None, quote(age=6, source="SYNTHETIC:alternate"),
    quote(symbol="OTHER", source="SYNTHETIC:alternate"),
    quote(bid=None, source="SYNTHETIC:alternate"),
    quote(bid="1.00", ask="1.50", source="SYNTHETIC:alternate"),
])
def test_no_valid_alternate_source_fails_closed(fallback):
    result = run(quote(bid="1.00", ask="1.50"), fallback=fallback)
    assert result.decision is QuoteDecision.FALLBACK_UNAVAILABLE_BLOCKED
    assert result.price is None and not result.order_submission_enabled

def test_relative_mid_spread_measure_is_explicit():
    result = run(quote(bid="1.00", ask="1.10"),
        p=policy(spread_measure="RELATIVE_MID", max_spread=Decimal("0.10")))
    assert result.decision is QuoteDecision.PRIMARY_QUOTE_ACCEPTED

def test_future_timestamp_is_not_fresh():
    future = U21Quote("STD1", "OPT1", Decimal("1"), Decimal("1.1"),
        NOW + timedelta(seconds=1), True, True, "SYNTHETIC:future", "b" * 64)
    assert run(future).decision is QuoteDecision.FALLBACK_UNAVAILABLE_BLOCKED

def test_validation_policy_never_enables_submission():
    for side in (QuoteSide.BUY, QuoteSide.SELL):
        assert run(quote(), side=side).order_submission_enabled is False
