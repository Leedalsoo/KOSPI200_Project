from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from application.composition.authoritative_option_quote_freshness_provider import (
    AuthoritativeOptionQuoteFreshnessProvider,
)
from contracts.market_data_freshness import FreshnessStatus
from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource


class _OptionMaster:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, symbol):
        return self.identity if symbol == self.identity.shrn_iscd else None


def _identity(*, symbol="OPT123", instrument_id="STD123", expiry="20261105", option_type="PUT", strike="500", multiplier="250000"):
    return SimpleNamespace(
        shrn_iscd=symbol,
        stnd_iscd=instrument_id,
        expiry=expiry,
        option_type=option_type,
        strike=Decimal(strike),
        contract_multiplier=Decimal(multiplier),
    )


def _command(*, symbol="OPT123", instrument_id="STD123", expiry="20261105", option_type="PUT", strike="500", multiplier="250000"):
    return SimpleNamespace(
        asset_type="OPTION",
        broker_symbol=symbol,
        instrument_id=instrument_id,
        expiry=expiry,
        option_type=option_type,
        strike=Decimal(strike),
        contract_multiplier=Decimal(multiplier),
    )


def test_matching_option_master_identity_without_source_evidence_fails_closed():
    master_identity = _identity()
    provider = AuthoritativeOptionQuoteFreshnessProvider(option_master=_OptionMaster(master_identity))

    verdict = provider(None, None, _command(), _command())

    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == "AUTHORITATIVE_QUOTE_FRESHNESS_EVIDENCE_UNAVAILABLE"
    assert verdict.instrument_id == "STD123"
    assert verdict.symbol == "OPT123"


def test_contract_identity_mismatch_returns_identity_conflict():
    master_identity = _identity()
    provider = AuthoritativeOptionQuoteFreshnessProvider(option_master=_OptionMaster(master_identity))
    command = _command(instrument_id="OTHER-STD")

    verdict = provider(None, None, _identity(), command)

    assert verdict.status is FreshnessStatus.IDENTITY_CONFLICT
    assert verdict.reason == "OPTION_MASTER_COMMAND_IDENTITY_MISMATCH"


def test_missing_option_master_contract_returns_identity_conflict():
    provider = AuthoritativeOptionQuoteFreshnessProvider(option_master=_OptionMaster(_identity()))
    command = _command(symbol="MISSING")

    verdict = provider(None, None, _identity(symbol="MISSING"), command)

    assert verdict.status is FreshnessStatus.IDENTITY_CONFLICT
    assert verdict.reason == "OPTION_MASTER_CONTRACT_NOT_FOUND"


def test_injected_synthetic_evidence_can_exercise_freshness_path_without_runtime_activation():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from contracts.market_data_freshness import FreshnessEvidence, FreshnessPolicy

    now = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    evidence = FreshnessEvidence(
        source="SYNTHETIC:validation-only",
        endpoint="synthetic://freshness-test",
        tr_id="SYNTHETIC_TEST_ONLY",
        environment="SYNTHETIC",
        instrument_id="STD123",
        symbol="OPT123",
        raw_source_time="095959",
        source_instant=now - timedelta(seconds=1),
        received_at=now,
        raw_payload_sha256="a" * 64,
        source_time_semantics_verified=True,
        capability_verified=True,
        metadata={"synthetic": "true", "validation_only": "true"},
    )
    policy = FreshnessPolicy(
        version="SYNTHETIC_TEST_ONLY",
        source_age_enabled=True,
        max_age=timedelta(seconds=10),
        max_future_skew=timedelta(seconds=1),
    )
    provider = AuthoritativeOptionQuoteFreshnessProvider(
        option_master=_OptionMaster(_identity()),
        evidence_provider=lambda *_: evidence,
        policy=policy,
        environment="SYNTHETIC",
    )

    verdict = provider(None, None, _identity(), _command())

    assert verdict.status is FreshnessStatus.FRESH
    assert verdict.policy_version == "SYNTHETIC_TEST_ONLY"
    assert verdict.source == "SYNTHETIC:validation-only"
    assert verdict.environment == "SYNTHETIC"
    assert verdict.evidence_sha256 == "a" * 64
    assert verdict.admits_risk_increase is True


def test_injected_synthetic_stale_evidence_is_denied_by_provider():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from contracts.market_data_freshness import FreshnessEvidence, FreshnessPolicy

    now = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    evidence = FreshnessEvidence(
        source="SYNTHETIC:validation-only",
        endpoint="synthetic://freshness-test",
        tr_id="SYNTHETIC_TEST_ONLY",
        environment="SYNTHETIC",
        instrument_id="STD123",
        symbol="OPT123",
        raw_source_time="095900",
        source_instant=now - timedelta(seconds=60),
        received_at=now,
        raw_payload_sha256="b" * 64,
        source_time_semantics_verified=True,
        capability_verified=True,
        metadata={"synthetic": "true", "validation_only": "true"},
    )
    policy = FreshnessPolicy(
        version="SYNTHETIC_TEST_ONLY",
        source_age_enabled=True,
        max_age=timedelta(seconds=10),
        max_future_skew=timedelta(seconds=1),
    )
    provider = AuthoritativeOptionQuoteFreshnessProvider(
        option_master=_OptionMaster(_identity()),
        evidence_provider=lambda *_: evidence,
        policy=policy,
        environment="SYNTHETIC",
    )

    verdict = provider(None, None, _identity(), _command())

    assert verdict.status is FreshnessStatus.STALE
    assert verdict.admits_risk_increase is False


def test_futures_quote_freshness_is_not_inferred_from_option_master():
    provider = AuthoritativeOptionQuoteFreshnessProvider(option_master=_OptionMaster(_identity()))
    command = SimpleNamespace(asset_type="FUTURES", broker_symbol="FUT1", instrument_id="FUT1")

    verdict = provider(None, None, None, command)

    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == "AUTHORITATIVE_FUTURES_QUOTE_FRESHNESS_PROVIDER_UNAVAILABLE"


def test_runtime_historical_source_evidence_is_connected_but_remains_fail_closed():
    as_of = datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    observation = SimpleNamespace(
        source="KIS:H0IOASP0",
        observed_at=as_of,
        collected_at=as_of,
        contract=SimpleNamespace(
            instrument_id="STD123", symbol="OPT123", expiry="20261105",
            option_type="PUT", strike=Decimal("500"),
        ),
        analytics=SimpleNamespace(implied_volatility=None, delta=None),
        quote=None,
        order_book=None,
        provenance=SimpleNamespace(
            endpoints=("kis-option-quote-endpoint",),
            tr_ids=("H0IOASP0",),
            source_timestamps=("095959",),
            metadata=(("environment", "KIS_VTS"),),
        ),
        raw_reference=SimpleNamespace(content_hash="c" * 64),
    )
    source = HistoricalObservationOptionSource([observation])
    source.set_as_of(as_of)
    provider = AuthoritativeOptionQuoteFreshnessProvider(
        option_master=_OptionMaster(_identity()),
        evidence_provider=lambda _plan, _leg, _identity, command: source.get_freshness_evidence(
            command.broker_symbol
        ),
    )

    verdict = provider(None, None, _identity(), _command())

    assert verdict.status is FreshnessStatus.BLOCKED_SOURCE_CAPABILITY
    assert verdict.source == "KIS:H0IOASP0"
    assert verdict.tr_id == "H0IOASP0"
    assert verdict.environment == "KIS_VTS"
    assert verdict.source_instant is None
    assert verdict.admits_risk_increase is False

