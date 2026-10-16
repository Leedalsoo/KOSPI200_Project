from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from contracts.market_data_freshness import (
    FreshnessEvidence, FreshnessPolicy, FreshnessStatus, TimestampStatus,
    candidate_source_instant, evaluate_freshness, evidence_fingerprint,
    permits_risk_increasing_order,
)


def _evidence(**changes):
    base = dict(
        source="KIS_VTS_REST", endpoint="/quote", tr_id="FHMIF10000000",
        environment="VIRTUAL", instrument_id="OPT-123", symbol="A12345",
        raw_source_time="101500",
        source_instant=datetime(2026, 10, 15, 10, 15, tzinfo=ZoneInfo("Asia/Seoul")),
        received_at=datetime(2026, 10, 15, 10, 15, 1, tzinfo=ZoneInfo("Asia/Seoul")),
        raw_payload_sha256="a" * 64, source_time_semantics_verified=True,
        capability_verified=True,
    )
    base.update(changes)
    return FreshnessEvidence(**base)


def test_fresh01_missing_zero_malformed_or_ambiguous_source_time_is_unknown():
    for raw in (None, "", "000000", "12345", "246199"):
        candidate = candidate_source_instant(
            raw, trading_date="20261015", trading_date_verified=True,
            session_context_verified=True,
        )
        assert candidate.status is TimestampStatus.UNKNOWN
        assert candidate.candidate_instant is None
    pre_session = candidate_source_instant(
        "084400", trading_date="20261015", trading_date_verified=True,
        session_context_verified=True,
    )
    assert pre_session.status is TimestampStatus.UNKNOWN
    no_date = candidate_source_instant(
        "101500", trading_date=None, trading_date_verified=False,
        session_context_verified=True,
    )
    assert no_date.status is TimestampStatus.UNKNOWN


def test_candidate_time_join_is_candidate_only_and_timezone_aware():
    candidate = candidate_source_instant(
        "101500", trading_date=date(2026, 10, 15), trading_date_verified=True,
        session_context_verified=True,
    )
    assert candidate.status is TimestampStatus.CANDIDATE
    assert candidate.candidate_instant == datetime(2026, 10, 15, 10, 15, tzinfo=ZoneInfo("Asia/Seoul"))
    verdict = evaluate_freshness(
        _evidence(source_instant=candidate.candidate_instant, source_time_semantics_verified=False),
        policy=FreshnessPolicy("source-time-disabled"),
    )
    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == "ABSOLUTE_SOURCE_TIME_SEMANTICS_NOT_VERIFIED"


def test_candidate_date_invalid_timezone_invalid_and_session_boundary_are_unknown():
    cases = (
        dict(raw_value="101500", trading_date="20260230", trading_date_verified=True, session_context_verified=True),
        dict(raw_value="101500", trading_date="20261015", trading_date_verified=True, session_context_verified=True, timezone_name="Mars/Olympus"),
        dict(raw_value="152000", trading_date="20261015", trading_date_verified=True, session_context_verified=True),
        dict(raw_value="081500", trading_date="20261015", trading_date_verified=True, session_context_verified=True),
    )
    for kwargs in cases:
        assert candidate_source_instant(**kwargs).status is TimestampStatus.UNKNOWN


def test_fresh02_approved_age_policy_marks_old_source_stale():
    now = datetime(2026, 10, 15, 10, 15, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    verdict = evaluate_freshness(
        _evidence(source_instant=now - timedelta(seconds=10), received_at=now),
        policy=FreshnessPolicy("approved-v1", True, timedelta(seconds=2), timedelta(seconds=1)),
    )
    assert verdict.status is FreshnessStatus.STALE
    assert not permits_risk_increasing_order(verdict)


def test_fresh03_future_source_skew_is_unknown_not_clamped():
    now = datetime(2026, 10, 15, 10, 15, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    verdict = evaluate_freshness(
        _evidence(source_instant=now + timedelta(seconds=3), received_at=now),
        policy=FreshnessPolicy("approved-v1", True, timedelta(seconds=2), timedelta(seconds=1)),
    )
    assert verdict.status is FreshnessStatus.UNKNOWN
    assert verdict.reason == "SOURCE_TIME_IN_FUTURE"


def test_missing_evidence_identity_or_raw_hash_fails_closed():
    policy = FreshnessPolicy("disabled")
    assert evaluate_freshness(None, policy=policy).status is FreshnessStatus.UNKNOWN
    assert evaluate_freshness(_evidence(instrument_id=""), policy=policy).status is FreshnessStatus.UNKNOWN
    assert evaluate_freshness(_evidence(raw_payload_sha256=None), policy=policy).status is FreshnessStatus.UNKNOWN
    assert evaluate_freshness(_evidence(raw_payload_sha256="not-a-hash"), policy=policy).status is FreshnessStatus.UNKNOWN


def test_identity_or_environment_mismatch_is_explicit_conflict():
    policy = FreshnessPolicy("disabled")
    assert evaluate_freshness(_evidence(), policy=policy, expected_instrument_id="OTHER").status is FreshnessStatus.IDENTITY_CONFLICT
    assert evaluate_freshness(_evidence(), policy=policy, expected_symbol="OTHER").status is FreshnessStatus.IDENTITY_CONFLICT
    assert evaluate_freshness(_evidence(), policy=policy, expected_environment="LIVE").status is FreshnessStatus.IDENTITY_CONFLICT


def test_capability_conflict_and_disabled_age_policy_never_admit():
    policy = FreshnessPolicy("disabled")
    blocked = evaluate_freshness(_evidence(capability_verified=False), policy=policy)
    unknown = evaluate_freshness(_evidence(), policy=policy)
    assert blocked.status is FreshnessStatus.BLOCKED_SOURCE_CAPABILITY
    assert unknown.status is FreshnessStatus.UNKNOWN
    assert not permits_risk_increasing_order(blocked)
    assert not permits_risk_increasing_order(unknown)


def test_fingerprint_is_deterministic_and_changes_with_source_evidence():
    original = _evidence()
    assert evidence_fingerprint(original) == evidence_fingerprint(original)
    assert evidence_fingerprint(original) != evidence_fingerprint(_evidence(raw_source_time="101501"))


def test_fresh06_and_fresh11_group_requires_every_leg_fresh():
    from contracts.market_data_freshness import FreshnessVerdict, permits_group_risk_increase

    fresh = FreshnessVerdict(FreshnessStatus.FRESH, "ok", "v1", instrument_id="A", symbol="A")
    unknown = FreshnessVerdict(FreshnessStatus.UNKNOWN, "missing", "v1", instrument_id="B", symbol="B")
    stale = FreshnessVerdict(FreshnessStatus.STALE, "old", "v1", instrument_id="C", symbol="C")
    assert permits_group_risk_increase((fresh, fresh))
    assert not permits_group_risk_increase((fresh, unknown))
    assert not permits_group_risk_increase((fresh, stale))
    assert not permits_group_risk_increase(())

def test_fresh14_capability_conflict_is_distinct_from_unverified_capability():
    conflict = evaluate_freshness(
        _evidence(capability_conflict=True),
        policy=FreshnessPolicy("capability-v1"),
    )
    blocked = evaluate_freshness(
        _evidence(capability_verified=False),
        policy=FreshnessPolicy("capability-v1"),
    )
    assert conflict.status is FreshnessStatus.CAPABILITY_CONFLICT
    assert conflict.reason == "SOURCE_CAPABILITY_EVIDENCE_CONFLICT"
    assert blocked.status is FreshnessStatus.BLOCKED_SOURCE_CAPABILITY
    assert not permits_risk_increasing_order(conflict)
