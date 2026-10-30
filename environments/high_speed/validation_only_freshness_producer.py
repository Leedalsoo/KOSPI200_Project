"""Validation-only synthetic freshness scenario producer.

This module emits deterministic scenario fixtures, not production FreshnessEvidence.
It has no runtime, broker, collector, order-router, or freshness-policy dependency.
Only a test may adapt these fixtures to the freshness contract; synthetic evidence
must never be treated as authoritative market data.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

GENERATOR_VERSION = "psb-validation-only-freshness-v1"
SYNTHETIC_SOURCE = "SYNTHETIC:psb-validation-only"
SYNTHETIC_ENVIRONMENT = "SYNTHETIC"
FIXTURE_TIMEZONE = "Asia/Seoul"
DEFAULT_ANCHOR = datetime(2026, 10, 28, 10, 0, 0, tzinfo=ZoneInfo(FIXTURE_TIMEZONE))
EXPECTED_INSTRUMENT_ID = "SYNTHETIC:OPT-001"
EXPECTED_SYMBOL = "SYNTHETIC-OPT-001"


@dataclass(frozen=True, slots=True)
class ValidationOnlyFreshnessCase:
    """Immutable synthetic fixture; deliberately not a production contract DTO."""

    scenario_id: str
    synthetic: bool
    generator_version: str
    seed: int
    config_hash: str
    source: str
    endpoint: str
    tr_id: str
    environment: str
    instrument_id: str
    symbol: str
    raw_source_time: str
    source_instant: datetime | None
    received_at: datetime
    raw_payload_sha256: str
    fixture_time_semantics_verified: bool
    fixture_capability_verified: bool
    expected_status: str

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-friendly record carrying explicit synthetic provenance."""
        record = asdict(self)
        record["source_instant"] = self.source_instant.isoformat() if self.source_instant else None
        record["received_at"] = self.received_at.isoformat()
        return record


class ValidationOnlyFreshnessProducer:
    """Build repeatable freshness edge cases without reading clocks or live sources."""

    def __init__(
        self,
        *,
        seed: int,
        generator_version: str = GENERATOR_VERSION,
        max_age_seconds: int = 600,
        max_future_skew_seconds: int = 1,
        anchor: datetime = DEFAULT_ANCHOR,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("SEED_MUST_BE_INTEGER")
        if not generator_version.strip():
            raise ValueError("GENERATOR_VERSION_REQUIRED")
        if max_age_seconds < 0 or max_future_skew_seconds < 0:
            raise ValueError("SYNTHETIC_THRESHOLDS_MUST_BE_NON_NEGATIVE")
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            raise ValueError("ANCHOR_MUST_BE_TIMEZONE_AWARE")

        self._seed = seed
        self._generator_version = generator_version
        self._max_age_seconds = max_age_seconds
        self._max_future_skew_seconds = max_future_skew_seconds
        self._anchor = anchor
        self._rng = random.Random(seed)
        config = {
            "schema_version": 1,
            "generator_version": generator_version,
            "anchor": anchor.isoformat(),
            "timezone": FIXTURE_TIMEZONE,
            "max_age_seconds": max_age_seconds,
            "max_future_skew_seconds": max_future_skew_seconds,
            "scenario_ids": [
                "fresh_candidate",
                "stale_candidate",
                "future_timestamp",
                "missing_timestamp",
                "identity_conflict",
                "capability_unverified",
                "time_semantics_unverified",
            ],
        }
        self._config_hash = sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def produce(self) -> tuple[ValidationOnlyFreshnessCase, ...]:
        """Return a stable set of explicitly synthetic edge-case records."""
        received_at = self._anchor
        fresh_age = self._rng.randint(0, self._max_age_seconds)
        stale_age = self._max_age_seconds + 1 + self._rng.randint(0, 30)
        future_skew = self._max_future_skew_seconds + 1 + self._rng.randint(0, 5)

        definitions = (
            ("fresh_candidate", received_at - timedelta(seconds=fresh_age), True, True, "FRESH"),
            ("stale_candidate", received_at - timedelta(seconds=stale_age), True, True, "STALE"),
            ("future_timestamp", received_at + timedelta(seconds=future_skew), True, True, "UNKNOWN"),
            ("missing_timestamp", None, True, True, "UNKNOWN"),
            ("identity_conflict", received_at - timedelta(seconds=fresh_age), True, True, "IDENTITY_CONFLICT"),
            ("capability_unverified", received_at - timedelta(seconds=fresh_age), True, False, "BLOCKED_SOURCE_CAPABILITY"),
            ("time_semantics_unverified", received_at - timedelta(seconds=fresh_age), False, True, "UNKNOWN"),
        )

        cases: list[ValidationOnlyFreshnessCase] = []
        for scenario_id, source_instant, time_verified, capability_verified, expected_status in definitions:
            instrument_id = (
                "SYNTHETIC:OTHER-OPT"
                if scenario_id == "identity_conflict"
                else EXPECTED_INSTRUMENT_ID
            )
            raw_source_time = source_instant.strftime("%H%M%S") if source_instant else ""
            payload = {
                "scenario_id": scenario_id,
                "source_instant": source_instant.isoformat() if source_instant else None,
                "received_at": received_at.isoformat(),
                "instrument_id": instrument_id,
                "symbol": EXPECTED_SYMBOL,
                "seed": self._seed,
                "config_hash": self._config_hash,
                "generator_version": self._generator_version,
            }
            payload_hash = sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            cases.append(
                ValidationOnlyFreshnessCase(
                    scenario_id=scenario_id,
                    synthetic=True,
                    generator_version=self._generator_version,
                    seed=self._seed,
                    config_hash=self._config_hash,
                    source=SYNTHETIC_SOURCE,
                    endpoint="synthetic://freshness-validation",
                    tr_id="PSB_SYNTHETIC_FIXTURE",
                    environment=SYNTHETIC_ENVIRONMENT,
                    instrument_id=instrument_id,
                    symbol=EXPECTED_SYMBOL,
                    raw_source_time=raw_source_time,
                    source_instant=source_instant,
                    received_at=received_at,
                    raw_payload_sha256=payload_hash,
                    fixture_time_semantics_verified=time_verified,
                    fixture_capability_verified=capability_verified,
                    expected_status=expected_status,
                )
            )
        return tuple(cases)
