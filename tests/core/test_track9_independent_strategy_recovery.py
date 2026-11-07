from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance
from core.strategy.track9_independent_policy import (
    Track9OpenLot, Track9OptionCandidate, Track9RuntimeInput, Track9SyntheticQuote,
)

KST = timezone(timedelta(hours=9))

def runtime_input(opening: str) -> Track9RuntimeInput:
    expiry = date(2026, 11, 12)
    put_id = "SYNTHETIC_CONTRACT:S9-20261112-PUT-500"
    call_id = "SYNTHETIC_CONTRACT:S9-20261112-CALL-500"
    observed = datetime(2026, 11, 9, 9, 0, tzinfo=KST)
    opened = datetime(2026, 11, 6, 15, 0, tzinfo=KST)
    return Track9RuntimeInput(
        contract_candidates=(
            Track9OptionCandidate(put_id, expiry, "PUT", Decimal("500"), "STANDARD", Decimal("100000"), True),
            Track9OptionCandidate(call_id, expiry, "CALL", Decimal("500"), "STANDARD", Decimal("100000"), True),
        ),
        underlying_price=Decimal("506"), as_of=observed,
        previous_official_close=Decimal("500"), next_session_official_open=Decimal(opening),
        option_quotes=(
            Track9SyntheticQuote(put_id, "PUT", Decimal("500"), expiry, Decimal("10"), Decimal("10.2"), Decimal("10.1"), observed, "SYNTHETIC:DERIVED_SCENARIO"),
            Track9SyntheticQuote(call_id, "CALL", Decimal("500"), expiry, Decimal("11"), Decimal("11.2"), Decimal("11.1"), observed, "SYNTHETIC:DERIVED_SCENARIO"),
        ),
        open_lots=(
            Track9OpenLot("track9_event_overnight_insurance", put_id, expiry, "PUT", Decimal("500"), 1, "BUY", None, Decimal("100000"), opened),
            Track9OpenLot("track9_event_overnight_insurance", call_id, expiry, "CALL", Decimal("500"), 1, "BUY", None, Decimal("100000"), opened),
        ),
        provenance="SYNTHETIC", source_provenance=tuple((key, "SYNTHETIC") for key in (
            "contract_identity", "contract_multiplier", "tradability", "option_quotes",
            "previous_official_close", "next_session_official_open", "trading_calendar",
            "account", "position", "risk_limits",)),
        scenario_id="S9_RECOVERY_TEST", manifest_sha256="a"*64, dataset_sha256="b"*64,
        contract_profile_sha256="c"*64, risk_profile_sha256="d"*64,
        max_quote_age_seconds=Decimal("5"),
    )

def test_fresh_strategy_restores_open_virtual_lots_and_closes_on_next_session_open() -> None:
    payload=runtime_input("506")
    strategy=Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    assert strategy.state.state == "OVERNIGHT_INSURANCE_ACTIVE"
    assert strategy.state.entry_date == date(2026, 11, 6)
    signals=strategy._opening_exit_signal(payload)
    assert len(signals)==1
    assert "OPENING_MOVE_AT_OR_ABOVE_1PCT_CLOSE_INSURANCE" in signals[0].reason


def test_fresh_strategy_restores_open_lots_and_uses_stop_loss_below_one_percent() -> None:
    payload=runtime_input("502.5")
    strategy=Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    signals=strategy._opening_exit_signal(payload)
    assert len(signals)==1
    assert "OPENING_MOVE_BELOW_1PCT_STOP_LOSS" in signals[0].reason
