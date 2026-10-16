"""Typed market-data freshness evidence and fail-closed admission contract.

Time-only KIS fields are candidate timestamps until their absolute-time semantics
are independently established. This module deliberately does not treat receipt
time as source time and does not activate age thresholds by default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from hashlib import sha256
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    CAPABILITY_CONFLICT = "CAPABILITY_CONFLICT"
    BLOCKED_SOURCE_CAPABILITY = "BLOCKED_SOURCE_CAPABILITY"


class TimestampStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceTimestampCandidate:
    status: TimestampStatus
    raw_value: str
    candidate_instant: datetime | None
    trading_date: str | None
    timezone_name: str
    policy_version: str
    reason: str


@dataclass(frozen=True)
class FreshnessPolicy:
    """Runtime age policy; disabled until absolute source-time semantics are approved."""

    version: str
    source_age_enabled: bool = False
    max_age: timedelta | None = None
    max_future_skew: timedelta | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("FRESHNESS_POLICY_VERSION_REQUIRED")
        if self.source_age_enabled and (self.max_age is None or self.max_future_skew is None):
            raise ValueError("FRESHNESS_THRESHOLDS_REQUIRED")
        if self.max_age is not None and self.max_age < timedelta(0):
            raise ValueError("FRESHNESS_MAX_AGE_MUST_BE_NON_NEGATIVE")
        if self.max_future_skew is not None and self.max_future_skew < timedelta(0):
            raise ValueError("FRESHNESS_MAX_FUTURE_SKEW_MUST_BE_NON_NEGATIVE")


@dataclass(frozen=True)
class FreshnessEvidence:
    source: str
    endpoint: str
    tr_id: str
    environment: str
    instrument_id: str
    symbol: str
    raw_source_time: str
    source_instant: datetime | None
    received_at: datetime | None
    raw_payload_sha256: str | None
    source_time_semantics_verified: bool = False
    capability_verified: bool = False
    capability_conflict: bool = False
    candidate_policy_version: str | None = None
    metadata: Mapping[str, str] | None = None


@dataclass(frozen=True)
class FreshnessVerdict:
    status: FreshnessStatus
    reason: str
    policy_version: str
    source: str | None = None
    tr_id: str | None = None
    environment: str | None = None
    instrument_id: str | None = None
    symbol: str | None = None
    source_instant: datetime | None = None
    received_at: datetime | None = None
    evidence_sha256: str | None = None

    @property
    def admits_risk_increase(self) -> bool:
        return self.status is FreshnessStatus.FRESH


def candidate_source_instant(
    raw_value: str | None,
    *,
    trading_date: str | date | None,
    trading_date_verified: bool,
    session_context_verified: bool,
    timezone_name: str = "Asia/Seoul",
    policy_version: str = "kis-time-only-date-join-v1",
    candidate_open: time = time(8, 45),
    candidate_cutoff: time = time(15, 20),
) -> SourceTimestampCandidate:
    """Create a candidate instant for validation only; never a freshness PASS.

    The default interval reflects only the currently reviewed general-session
    candidate. Product-specific/expiry-session semantics must be verified by
    the caller. Pre-session, post-cutoff, zero, and ambiguous values stay UNKNOWN.
    """
    raw = "" if raw_value is None else str(raw_value).strip()
    day_text = trading_date.strftime("%Y%m%d") if isinstance(trading_date, date) else str(trading_date or "").strip()
    def unknown(reason: str) -> SourceTimestampCandidate:
        return SourceTimestampCandidate(
            TimestampStatus.UNKNOWN, raw, None, day_text or None,
            timezone_name, policy_version, reason,
        )

    if not re.fullmatch(r"\d{8}", day_text):
        return unknown("TRADING_DATE_MISSING_OR_INVALID")
    if not trading_date_verified:
        return unknown("TRADING_DATE_NOT_INDEPENDENTLY_VERIFIED")
    if not session_context_verified:
        return unknown("PRODUCT_SESSION_CONTEXT_NOT_VERIFIED")
    if not re.fullmatch(r"\d{6}", raw):
        return unknown("SOURCE_TIME_MISSING_OR_MALFORMED")
    if raw == "000000":
        return unknown("SOURCE_TIME_ZERO_IS_UNKNOWN")
    try:
        parsed_date = datetime.strptime(day_text, "%Y%m%d").date()
        parsed_time = datetime.strptime(raw, "%H%M%S").time()
        tz = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return unknown("SOURCE_DATE_TIME_OR_TIMEZONE_INVALID")
    if not (candidate_open <= parsed_time < candidate_cutoff):
        return unknown("SESSION_BOUNDARY_OR_OUTSIDE_CANDIDATE_WINDOW")
    instant = datetime.combine(parsed_date, parsed_time, tzinfo=tz)
    return SourceTimestampCandidate(
        TimestampStatus.CANDIDATE, raw, instant, day_text, timezone_name,
        policy_version, "CANDIDATE_ONLY_ABSOLUTE_SOURCE_SEMANTICS_UNPROVEN",
    )


def evaluate_freshness(
    evidence: FreshnessEvidence | None,
    *,
    policy: FreshnessPolicy,
    expected_instrument_id: str | None = None,
    expected_symbol: str | None = None,
    expected_environment: str | None = None,
) -> FreshnessVerdict:
    """Evaluate evidence without substituting receive time or guessing capability."""
    def verdict(status: FreshnessStatus, reason: str) -> FreshnessVerdict:
        return FreshnessVerdict(
            status=status, reason=reason, policy_version=policy.version,
            source=evidence.source if evidence else None,
            tr_id=evidence.tr_id if evidence else None,
            environment=evidence.environment if evidence else None,
            instrument_id=evidence.instrument_id if evidence else None,
            symbol=evidence.symbol if evidence else None,
            source_instant=evidence.source_instant if evidence else None,
            received_at=evidence.received_at if evidence else None,
            evidence_sha256=evidence.raw_payload_sha256 if evidence else None,
        )

    if evidence is None:
        return verdict(FreshnessStatus.UNKNOWN, "FRESHNESS_EVIDENCE_MISSING")
    if expected_instrument_id and evidence.instrument_id != expected_instrument_id:
        return verdict(FreshnessStatus.IDENTITY_CONFLICT, "INSTRUMENT_ID_MISMATCH")
    if expected_symbol and evidence.symbol != expected_symbol:
        return verdict(FreshnessStatus.IDENTITY_CONFLICT, "SYMBOL_MISMATCH")
    if expected_environment and evidence.environment.upper() != expected_environment.upper():
        return verdict(FreshnessStatus.IDENTITY_CONFLICT, "ENVIRONMENT_MISMATCH")
    if not evidence.instrument_id.strip() or not evidence.symbol.strip():
        return verdict(FreshnessStatus.UNKNOWN, "EXACT_CONTRACT_IDENTITY_REQUIRED")
    if not evidence.source.strip() or not evidence.endpoint.strip() or not evidence.tr_id.strip():
        return verdict(FreshnessStatus.UNKNOWN, "SOURCE_ENDPOINT_AND_TR_REQUIRED")
    if evidence.raw_payload_sha256 is None or not re.fullmatch(r"[0-9a-fA-F]{64}", evidence.raw_payload_sha256):
        return verdict(FreshnessStatus.UNKNOWN, "RAW_PAYLOAD_SHA256_REQUIRED")
    if evidence.capability_conflict:
        return verdict(FreshnessStatus.CAPABILITY_CONFLICT, "SOURCE_CAPABILITY_EVIDENCE_CONFLICT")
    if not evidence.capability_verified:
        return verdict(FreshnessStatus.BLOCKED_SOURCE_CAPABILITY, "SOURCE_CAPABILITY_NOT_VERIFIED")
    if not evidence.source_time_semantics_verified:
        return verdict(FreshnessStatus.UNKNOWN, "ABSOLUTE_SOURCE_TIME_SEMANTICS_NOT_VERIFIED")
    if evidence.source_instant is None or evidence.received_at is None:
        return verdict(FreshnessStatus.UNKNOWN, "SOURCE_INSTANT_OR_RECEIVE_TIME_MISSING")
    if evidence.source_instant.tzinfo is None or evidence.received_at.tzinfo is None:
        return verdict(FreshnessStatus.UNKNOWN, "TIMEZONE_AWARE_INSTANT_REQUIRED")
    if not policy.source_age_enabled:
        return verdict(FreshnessStatus.UNKNOWN, "SOURCE_AGE_POLICY_NOT_ACTIVATED")
    if policy.max_age is None or policy.max_future_skew is None:
        return verdict(FreshnessStatus.UNKNOWN, "APPROVED_FRESHNESS_THRESHOLDS_REQUIRED")
    skew = evidence.source_instant - evidence.received_at
    if skew > policy.max_future_skew:
        return verdict(FreshnessStatus.UNKNOWN, "SOURCE_TIME_IN_FUTURE")
    age = evidence.received_at - evidence.source_instant
    if age > policy.max_age:
        return verdict(FreshnessStatus.STALE, "SOURCE_AGE_EXCEEDS_APPROVED_THRESHOLD")
    return verdict(FreshnessStatus.FRESH, "SOURCE_TIME_WITHIN_APPROVED_POLICY")


def evidence_fingerprint(evidence: FreshnessEvidence) -> str:
    """Stable hash of the contract's provenance fields (not a substitute for raw hash)."""
    fields = (
        evidence.source, evidence.endpoint, evidence.tr_id, evidence.environment,
        evidence.instrument_id, evidence.symbol, evidence.raw_source_time,
        evidence.source_instant.isoformat() if evidence.source_instant else "",
        evidence.received_at.isoformat() if evidence.received_at else "",
        evidence.raw_payload_sha256 or "", evidence.candidate_policy_version or "",
    )
    return sha256("\x1f".join(fields).encode("utf-8")).hexdigest()


def permits_risk_increasing_order(verdict: FreshnessVerdict | None) -> bool:
    """Fail closed: only an explicit FRESH verdict permits a risk-increasing order."""
    return verdict is not None and verdict.admits_risk_increase


def permits_group_risk_increase(verdicts: tuple[FreshnessVerdict | None, ...] | list[FreshnessVerdict | None]) -> bool:
    """A multi-leg group is eligible only when every required leg is explicitly FRESH."""
    return bool(verdicts) and all(permits_risk_increasing_order(item) for item in verdicts)


def admits_freshness_verdict_for_identity(
    verdict: FreshnessVerdict | None, *, expected_instrument_id: str, expected_symbol: str
) -> bool:
    """Require a complete, identity-matched FRESH verdict at the order boundary."""
    return bool(
        permits_risk_increasing_order(verdict)
        and expected_instrument_id.strip()
        and expected_symbol.strip()
        and verdict.instrument_id == expected_instrument_id
        and verdict.symbol == expected_symbol
        and verdict.source
        and verdict.tr_id
        and verdict.environment
        and verdict.policy_version.strip()
        and verdict.source_instant is not None
        and verdict.source_instant.tzinfo is not None
        and verdict.received_at is not None
        and verdict.received_at.tzinfo is not None
        and verdict.evidence_sha256
        and re.fullmatch(r"[0-9a-fA-F]{64}", verdict.evidence_sha256)
    )
