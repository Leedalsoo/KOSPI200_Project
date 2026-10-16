from datetime import datetime, timezone

import pytest

from contracts.market_data_freshness import (
    FreshnessEvidence, FreshnessPolicy, FreshnessStatus, evaluate_freshness,
)
from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.kis_rest_market_observation_normalizer import KISRestMarketObservationNormalizer


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
