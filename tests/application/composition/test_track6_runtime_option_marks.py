from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.track6_option_contract_source import Track6OptionContractSource

KST = timezone(timedelta(hours=9))
INSTRUMENT = "SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5"


class Master:
    def get_contract_identity(self, instrument_id):
        if instrument_id != INSTRUMENT:
            return None
        return SimpleNamespace(
            shrn_iscd=INSTRUMENT, option_type="PUT", strike=Decimal("487.5"),
            expiry="20261102", contract_multiplier=Decimal("250000"),
        )


def provider(quote):
    market = SimpleNamespace(option_quotes_by_instrument_id={INSTRUMENT: quote})
    master = Master()
    return StandardRuntimeInputProvider(
        market, track6_option_contract_source=Track6OptionContractSource(master),
        track6_option_mark_max_age_seconds=5,
    )


def quote(timestamp, **overrides):
    value = {
        "instrument_id": INSTRUMENT, "option_type": "PUT", "strike": 487.5,
        "expiry": "20261102", "bid": 0.8, "ask": 0.9, "last": 0.85,
        "timestamp": timestamp.isoformat(), "contract_multiplier": 250000,
        "source": "SYNTHETIC:DERIVED_SCENARIO",
    }
    value.update(overrides)
    return value


def test_provider_materializes_fresh_identity_bound_synthetic_marks():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    marks = provider(quote(now))._track6_option_marks(now)
    assert len(marks) == 1
    assert marks[0].instrument_id == INSTRUMENT
    assert marks[0].bid_price == Decimal("0.8")
    assert marks[0].source == "SYNTHETIC:DERIVED_SCENARIO"
    assert len(marks[0].evidence_sha256) == 64


def test_provider_omits_stale_or_wrong_identity_synthetic_marks():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    stale = quote(now - timedelta(seconds=6))
    wrong_id = quote(now, instrument_id="SYNTHETIC_CONTRACT:OTHER")
    wrong_source = quote(now, source="VMS:REPLAY")
    assert provider(stale)._track6_option_marks(now) == ()
    assert provider(wrong_id)._track6_option_marks(now) == ()
    assert provider(wrong_source)._track6_option_marks(now) == ()
