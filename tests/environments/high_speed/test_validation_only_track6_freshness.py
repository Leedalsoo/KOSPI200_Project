from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from contracts.types import OptionInstrumentIdentity
from environments.high_speed.validation_only_track6_execution import Track6SyntheticFreshnessProvider

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


def test_freshness_provider_uses_exact_contract_quote_not_strike_collision():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    quote = {
        "instrument_id": INSTRUMENT, "option_type": "PUT", "strike": 487.5,
        "expiry": "20261102", "bid": 0.8, "ask": 0.9, "last": 0.85,
        "timestamp": now.isoformat(), "contract_multiplier": 250000,
        "source": "SYNTHETIC:DERIVED_SCENARIO",
    }
    market = SimpleNamespace(
        option_quotes_by_instrument_id={INSTRUMENT: quote},
        option_quotes={("PUT", 487.5, "20261102"): {"bid": 0.01, "ask": 0.02, "last": 0.015}},
    )
    sources = SimpleNamespace(_tick=SimpleNamespace(timestamp=now.isoformat()))
    provider = Track6SyntheticFreshnessProvider(
        option_master=Master(), market=market, max_age_seconds=5, synthetic_sources=sources,
    )
    identity = OptionInstrumentIdentity(
        INSTRUMENT, INSTRUMENT, "20261102", "PUT", Decimal("487.5"),
        Decimal("250000"), "OPTION_MASTER",
    )
    verdict = provider(
        SimpleNamespace(strategy_id="track6_daily_tail_insurance"),
        SimpleNamespace(), identity,
        SimpleNamespace(instrument_id=INSTRUMENT, broker_symbol=INSTRUMENT),
    )
    assert verdict.status.name == "FRESH"
    assert verdict.reason == "SYNTHETIC_MANIFEST_BOUND_QUOTE_VALID"


def test_freshness_provider_fails_closed_without_identity_keyed_quote():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    market = SimpleNamespace(
        option_quotes_by_instrument_id={},
        option_quotes={("PUT", 487.5, "20261102"): {"bid": 0.8, "ask": 0.9, "last": 0.85}},
    )
    sources = SimpleNamespace(_tick=SimpleNamespace(timestamp=now.isoformat()))
    provider = Track6SyntheticFreshnessProvider(
        option_master=Master(), market=market, max_age_seconds=5, synthetic_sources=sources,
    )
    identity = OptionInstrumentIdentity(
        INSTRUMENT, INSTRUMENT, "20261102", "PUT", Decimal("487.5"),
        Decimal("250000"), "OPTION_MASTER",
    )
    verdict = provider(
        SimpleNamespace(strategy_id="track6_daily_tail_insurance"),
        SimpleNamespace(), identity,
        SimpleNamespace(instrument_id=INSTRUMENT, broker_symbol=INSTRUMENT),
    )
    assert verdict.status.name == "UNKNOWN"
    assert verdict.reason == "SYNTHETIC_IDENTITY_BOUND_QUOTE_MISSING"
