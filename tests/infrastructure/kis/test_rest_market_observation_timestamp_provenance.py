from datetime import datetime, timedelta, timezone

import pytest

from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    FreshnessStatus,
    candidate_source_instant,
    evaluate_freshness,
)
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.kis_rest_market_observation_normalizer import (
    KISRestMarketObservationNormalizer,
)


class _IdentityLookup:
    def get_contract_identity(self, symbol):
        return OptionInstrumentIdentity(instrument_id="OPT-1", symbol=symbol)


def test_fresh04_rest_price_and_orderbook_time_conflict_is_rejected():
    normalizer = KISRestMarketObservationNormalizer(_IdentityLookup())
    price = {
        "rt_cd": "0",
        "output1": {"futs_shrn_iscd": "A12345", "aspr_acpt_hour": "101500"},
        "output3": {"bstp_cls_code": "2001", "hts_kor_isnm": "KOSPI200", "bstp_nmix_prpr": "350"},
    }
    book = {
        "rt_cd": "0",
        "output1": {"futs_shrn_iscd": "A12345"},
        "output2": {"aspr_acpt_hour": "101501"},
    }
    with pytest.raises(ValueError, match="KIS_REST_SOURCE_TIMESTAMP_MISMATCH"):
        normalizer.normalize(
            price_response=price,
            asking_price_response=book,
            collected_at=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
            run_id="test-run",
        )


def test_fresh05_missing_hash_endpoint_tr_or_identity_is_unknown():
    policy = FreshnessPolicy("disabled")
    base = dict(
        source="KIS_VTS_REST", endpoint="/quote", tr_id="FHMIF10000000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        raw_source_time="101500", source_instant=None,
        received_at=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
        raw_payload_sha256="a" * 64, capability_verified=True,
        source_time_semantics_verified=True,
    )
    for changes in (
        {"raw_payload_sha256": None},
        {"endpoint": ""},
        {"tr_id": ""},
        {"instrument_id": ""},
        {"symbol": ""},
    ):
        assert evaluate_freshness(
            FreshnessEvidence(**(base | changes)), policy=policy
        ).status is FreshnessStatus.UNKNOWN


def test_fresh07_receive_time_never_substitutes_for_missing_source_instant():
    received = datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc)
    evidence = FreshnessEvidence(
        source="KIS_VTS_REST", endpoint="/quote", tr_id="FHMIF10000000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        raw_source_time="101500", source_instant=None, received_at=received,
        raw_payload_sha256="b" * 64, capability_verified=True,
        source_time_semantics_verified=True,
    )
    verdict = evaluate_freshness(
        evidence,
        policy=FreshnessPolicy("age-policy", True, __import__("datetime").timedelta(seconds=2), __import__("datetime").timedelta(seconds=1)),
    )
    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.source_instant is None
    assert verdict.received_at == received
    assert verdict.reason == "SOURCE_INSTANT_OR_RECEIVE_TIME_MISSING"


def test_fresh14_unverified_source_capability_is_blocked_not_promoted():
    evidence = FreshnessEvidence(
        source="KIS:H0IOASP0", endpoint="websocket", tr_id="H0IOASP0",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        raw_source_time="101500",
        source_instant=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
        received_at=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
        raw_payload_sha256="c" * 64, source_time_semantics_verified=True,
        capability_verified=False,
    )
    verdict = evaluate_freshness(evidence, policy=FreshnessPolicy("disabled"))
    assert verdict.status is FreshnessStatus.BLOCKED_SOURCE_CAPABILITY
    assert verdict.reason == "SOURCE_CAPABILITY_NOT_VERIFIED"


def _rest_responses(price_source_time="101500", book_source_time="101500"):
    return (
        {
            "rt_cd": "0",
            "output1": {
                "futs_shrn_iscd": "A12345",
                "futs_prpr": "350.0",
                "aspr_acpt_hour": price_source_time,
            },
            "output3": {
                "bstp_cls_code": "2001",
                "hts_kor_isnm": "KOSPI200",
                "bstp_nmix_prpr": "350",
            },
        },
        {
            "rt_cd": "0",
            "output1": {"futs_shrn_iscd": "A12345"},
            "output2": {
                "aspr_acpt_hour": book_source_time,
                "futs_askp1": "351.0",
                "futs_bidp1": "349.0",
                "futs_askp_rsqn1": "2",
                "futs_bidp_rsqn1": "3",
            },
        },
    )


def test_t13_rest_source_time_remains_time_only_and_unresolved():
    normalizer = KISRestMarketObservationNormalizer(_IdentityLookup())
    price, book = _rest_responses()
    received = datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc)

    observation = normalizer.normalize(
        price_response=price,
        asking_price_response=book,
        collected_at=received,
        run_id="t13-rest-time-only",
    )

    metadata = dict(observation.provenance.metadata)
    assert observation.observed_at is None
    assert observation.collected_at == received
    assert observation.provenance.source_timestamps == ("101500",)
    assert metadata["source_timestamp_field"] == "aspr_acpt_hour"
    assert metadata["source_timestamp_format"] == "HHMMSS"
    assert metadata["source_timestamp_timezone"] == "UNVERIFIED"
    assert metadata["source_timestamp_date_resolution"] == "UNRESOLVED_TIME_ONLY"
    assert metadata["source_timestamp_absolute"] == "false"
    assert metadata["source_timestamp_status"] == "TIME_OF_DAY_ONLY"
    assert metadata["receipt_timezone"] == "UTC"
    assert metadata["observed_at_semantics"] == "RECEIPT_TIME_ONLY_SOURCE_INSTANT_UNRESOLVED"


def test_t13_rest_zero_sentinel_is_not_promoted_and_valid_side_is_retained():
    normalizer = KISRestMarketObservationNormalizer(_IdentityLookup())
    price, book = _rest_responses("000000", "101500")
    received = datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc)

    observation = normalizer.normalize(
        price_response=price,
        asking_price_response=book,
        collected_at=received,
        run_id="t13-rest-zero-sentinel",
    )

    metadata = dict(observation.provenance.metadata)
    assert observation.provenance.source_timestamps == ("101500",)
    assert metadata["source_timestamp_raw_price"] == "000000"
    assert metadata["source_timestamp_raw_order_book"] == "101500"
    assert metadata["source_timestamp_zero_or_malformed_not_promoted"] == "true"


def test_t13_rest_zero_sentinel_and_missing_source_time_remain_unknown():
    normalizer = KISRestMarketObservationNormalizer(_IdentityLookup())
    price, book = _rest_responses("000000", None)
    received = datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc)

    observation = normalizer.normalize(
        price_response=price,
        asking_price_response=book,
        collected_at=received,
        run_id="t13-rest-source-time-unknown",
    )

    metadata = dict(observation.provenance.metadata)
    assert observation.observed_at is None
    assert observation.provenance.source_timestamps == ()
    assert metadata["source_timestamp_status"] == "UNKNOWN"
    assert metadata["source_timestamp_zero_or_malformed_not_promoted"] == "true"


def test_t13_rest_receipt_timestamp_must_be_timezone_aware():
    normalizer = KISRestMarketObservationNormalizer(_IdentityLookup())
    price, book = _rest_responses()

    with pytest.raises(ValueError, match="KIS_REST_COLLECTED_AT_MUST_BE_TIMEZONE_AWARE"):
        normalizer.normalize(
            price_response=price,
            asking_price_response=book,
            collected_at=datetime.fromisoformat("2026-10-15T10:15:00"),
            run_id="t13-rest-naive-receipt",
        )


def test_t13_time_only_source_candidate_requires_verified_date_and_session_context():
    missing_date = candidate_source_instant('101500', trading_date=None, trading_date_verified=True, session_context_verified=True)
    unverified_date = candidate_source_instant('101500', trading_date='20261013', trading_date_verified=False, session_context_verified=True)
    unverified_session = candidate_source_instant('101500', trading_date='20261013', trading_date_verified=True, session_context_verified=False)
    assert missing_date.status.value == 'UNKNOWN'
    assert missing_date.reason == 'TRADING_DATE_MISSING_OR_INVALID'
    assert unverified_date.reason == 'TRADING_DATE_NOT_INDEPENDENTLY_VERIFIED'
    assert unverified_session.reason == 'PRODUCT_SESSION_CONTEXT_NOT_VERIFIED'

def test_t13_time_only_source_candidate_does_not_resolve_outside_session_window():
    for raw in ('000000', '083000', '154500'):
        candidate = candidate_source_instant(raw, trading_date='20261013', trading_date_verified=True, session_context_verified=True)
        assert candidate.status.value == 'UNKNOWN'
        assert candidate.candidate_instant is None

def test_t13_time_only_candidate_is_not_a_freshness_pass_until_semantics_verified():
    candidate = candidate_source_instant('101500', trading_date='20261013', trading_date_verified=True, session_context_verified=True)
    assert candidate.status.value == 'CANDIDATE'
    assert candidate.candidate_instant.isoformat() == '2026-10-13T10:15:00+09:00'
    evidence = FreshnessEvidence(source='KIS_VTS_REST', endpoint='/option/orderbook', tr_id='FHMIF10010000', environment='VIRTUAL', instrument_id='OPT-1', symbol='A12345', raw_source_time='101500', source_instant=candidate.candidate_instant, received_at=datetime(2026, 10, 13, 1, 15, 1, tzinfo=timezone.utc), raw_payload_sha256='d' * 64, source_time_semantics_verified=False, capability_verified=True)
    verdict = evaluate_freshness(evidence, policy=FreshnessPolicy('t13-synthetic', True, timedelta(seconds=5), timedelta(seconds=1)))
    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == 'ABSOLUTE_SOURCE_TIME_SEMANTICS_NOT_VERIFIED'

def test_t13_timezone_normalization_and_future_clock_skew_are_explicit():
    candidate = candidate_source_instant('101500', trading_date='20261013', trading_date_verified=True, session_context_verified=True)
    evidence = FreshnessEvidence(source='KIS_VTS_REST', endpoint='/option/orderbook', tr_id='FHMIF10010000', environment='VIRTUAL', instrument_id='OPT-1', symbol='A12345', raw_source_time='101500', source_instant=candidate.candidate_instant + timedelta(seconds=1), received_at=datetime(2026, 10, 13, 1, 15, tzinfo=timezone.utc), raw_payload_sha256='e' * 64, source_time_semantics_verified=True, capability_verified=True)
    verdict = evaluate_freshness(evidence, policy=FreshnessPolicy('t13-clock-skew', True, timedelta(seconds=5), timedelta(milliseconds=500)))
    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == 'SOURCE_TIME_IN_FUTURE'
