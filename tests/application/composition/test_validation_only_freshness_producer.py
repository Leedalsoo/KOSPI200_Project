"""PSB tests for the validation-only freshness producer and its isolation boundary."""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    FreshnessStatus,
    evaluate_freshness,
)
from environments.high_speed.validation_only_freshness_producer import (
    EXPECTED_INSTRUMENT_ID,
    EXPECTED_SYMBOL,
    SYNTHETIC_ENVIRONMENT,
    SYNTHETIC_SOURCE,
    ValidationOnlyFreshnessProducer,
)

ROOT = Path(__file__).resolve().parents[3]
PRODUCER_PATH = ROOT / "environments" / "high_speed" / "validation_only_freshness_producer.py"
TEST_ONLY_POLICY = FreshnessPolicy(
    version="PSB_SYNTHETIC_TEST_ONLY",
    source_age_enabled=True,
    max_age=timedelta(seconds=600),
    max_future_skew=timedelta(seconds=1),
)


def _contract_evidence(case):
    """Test-only adapter; never used by application/runtime code."""
    return FreshnessEvidence(
        source=case.source,
        endpoint=case.endpoint,
        tr_id=case.tr_id,
        environment=case.environment,
        instrument_id=case.instrument_id,
        symbol=case.symbol,
        raw_source_time=case.raw_source_time,
        source_instant=case.source_instant,
        received_at=case.received_at,
        raw_payload_sha256=case.raw_payload_sha256,
        source_time_semantics_verified=case.fixture_time_semantics_verified,
        capability_verified=case.fixture_capability_verified,
        metadata={
            "synthetic": "true",
            "generator_version": case.generator_version,
            "seed": str(case.seed),
            "config_hash": case.config_hash,
            "scenario_id": case.scenario_id,
            "validation_only": "true",
        },
    )


def test_producer_is_deterministic_and_provenance_is_complete():
    first = ValidationOnlyFreshnessProducer(seed=20261028).produce()
    second = ValidationOnlyFreshnessProducer(seed=20261028).produce()
    different_seed = ValidationOnlyFreshnessProducer(seed=20261029).produce()

    assert first == second
    assert first != different_seed
    assert len({case.config_hash for case in first}) == 1
    assert all(len(case.config_hash) == 64 for case in first)
    assert all(len(case.raw_payload_sha256) == 64 for case in first)
    assert all(case.synthetic is True for case in first)
    assert all(case.environment == SYNTHETIC_ENVIRONMENT for case in first)
    assert all(case.source == SYNTHETIC_SOURCE for case in first)
    assert all(case.generator_version and case.seed == 20261028 for case in first)
    assert {case.scenario_id for case in first} == {
        "fresh_candidate",
        "stale_candidate",
        "future_timestamp",
        "missing_timestamp",
        "identity_conflict",
        "capability_unverified",
        "time_semantics_unverified",
    }
    assert all(record["synthetic"] is True for record in (case.as_record() for case in first))


def test_synthetic_scenarios_exercise_contract_edge_cases_only():
    cases = ValidationOnlyFreshnessProducer(seed=20261028).produce()
    expected_identity = EXPECTED_INSTRUMENT_ID
    verdicts = {}

    for case in cases:
        verdict = evaluate_freshness(
            _contract_evidence(case),
            policy=TEST_ONLY_POLICY,
            expected_instrument_id=expected_identity,
            expected_symbol=EXPECTED_SYMBOL,
            expected_environment=SYNTHETIC_ENVIRONMENT,
        )
        verdicts[case.scenario_id] = verdict
        assert verdict.status.value == case.expected_status, case.scenario_id
        assert verdict.policy_version == TEST_ONLY_POLICY.version
        assert verdict.evidence_sha256 == case.raw_payload_sha256

    assert verdicts["fresh_candidate"].status is FreshnessStatus.FRESH
    assert verdicts["stale_candidate"].status is FreshnessStatus.STALE
    assert verdicts["future_timestamp"].reason == "SOURCE_TIME_IN_FUTURE"
    assert verdicts["missing_timestamp"].status is FreshnessStatus.UNKNOWN
    assert verdicts["identity_conflict"].status is FreshnessStatus.IDENTITY_CONFLICT
    assert verdicts["capability_unverified"].status is FreshnessStatus.BLOCKED_SOURCE_CAPABILITY
    assert verdicts["time_semantics_unverified"].status is FreshnessStatus.UNKNOWN


def test_producer_module_has_no_production_contract_or_runtime_dependency():
    tree = ast.parse(PRODUCER_PATH.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(
        name == "contracts.market_data_freshness"
        or name.startswith(("application", "core", "infrastructure", "interfaces"))
        for name in imported_modules
    )
    assert "contracts.market_data_freshness" not in imported_modules


def test_no_production_source_imports_the_validation_only_producer():
    production_roots = (
        ROOT / "application",
        ROOT / "contracts",
        ROOT / "core",
        ROOT / "environments",
        ROOT / "infrastructure",
        ROOT / "interfaces",
    )
    target_module = "environments.high_speed.validation_only_freshness_producer"
    offenders = []

    for source_root in production_roots:
        for path in source_root.rglob("*.py"):
            if path == PRODUCER_PATH or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == target_module for alias in node.names):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == target_module:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == [], f"validation-only producer connected to production: {offenders}"
