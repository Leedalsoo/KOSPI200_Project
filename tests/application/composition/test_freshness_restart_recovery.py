from datetime import datetime, timezone

from contracts.market_data_freshness import (
    FreshnessEvidence, FreshnessPolicy, FreshnessStatus, evaluate_freshness,
    evidence_fingerprint,
)


def _evidence():
    return FreshnessEvidence(
        source="KIS_VTS_REST", endpoint="/quote", tr_id="FHMIF10000000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        raw_source_time="000000", source_instant=None,
        received_at=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
        raw_payload_sha256="e" * 64, source_time_semantics_verified=False,
        capability_verified=True, candidate_policy_version="candidate-v1",
        metadata={"partition": "20261015"},
    )


def test_fresh10_restart_after_gap_stays_unknown_until_source_reconciles():
    policy = FreshnessPolicy("restart-v1")
    before_restart = evaluate_freshness(_evidence(), policy=policy)
    after_restart = evaluate_freshness(_evidence(), policy=policy)
    assert before_restart.status is FreshnessStatus.UNKNOWN
    assert after_restart.status is FreshnessStatus.UNKNOWN
    assert before_restart.reason == after_restart.reason
    assert before_restart.evidence_sha256 == after_restart.evidence_sha256


def test_fresh13_verdict_and_evidence_fingerprint_are_deterministic():
    evidence = _evidence()
    policy = FreshnessPolicy("replay-v1")
    a = evaluate_freshness(evidence, policy=policy)
    b = evaluate_freshness(evidence, policy=policy)
    assert a == b
    assert evidence_fingerprint(evidence) == evidence_fingerprint(evidence)
