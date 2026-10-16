from datetime import datetime, timezone

import pytest

from contracts.market_data_freshness import (
    FreshnessEvidence, FreshnessPolicy, FreshnessStatus, FreshnessVerdict,
    evaluate_freshness, permits_group_risk_increase,
)
from application.composition.runtime_authoritative_risk_router_adapter import (
    route_from_runtime_authoritative_sources,
)
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide,
)


def _command():
    return CanonicalOrderCommand(
        client_order_id="client-1", track_id="S1",
        asset_type=CanonicalAssetType.OPTION, side=CanonicalOrderSide.BUY,
        qty=1, price=1.0, symbol="A12345", expiry="20261029",
        instrument_id="OPT-1",
    )


class _ForbiddenRiskGate:
    def __init__(self):
        self.calls = 0

    def admit_order(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("RiskGate must not be called before freshness identity is admitted")


@pytest.mark.parametrize("strategy_id", [f"S{i}" for i in range(1, 10)])
def test_fresh11_each_strategy_requires_explicit_fresh_verdict(strategy_id):
    command = _command()
    command = CanonicalOrderCommand(
        client_order_id=command.client_order_id, track_id=strategy_id,
        asset_type=command.asset_type, side=command.side, qty=command.qty,
        price=command.price, symbol=command.symbol, expiry=command.expiry,
        instrument_id=command.instrument_id,
    )
    gate = _ForbiddenRiskGate()
    result = route_from_runtime_authoritative_sources(
        command, risk_gate=gate, context=None, freshness_verdict=None,
    )
    assert not result.routed
    assert result.rejection_reason == "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED"
    assert gate.calls == 0


def test_single_order_path_rejects_fresh_verdict_for_wrong_contract():
    gate = _ForbiddenRiskGate()
    wrong = FreshnessVerdict(
        FreshnessStatus.FRESH, "test", "v1",
        instrument_id="OPT-OTHER", symbol="OTHER",
    )
    result = route_from_runtime_authoritative_sources(
        _command(), risk_gate=gate, context=None, freshness_verdict=wrong,
    )
    assert not result.routed
    assert result.rejection_reason == "MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH"
    assert gate.calls == 0


def test_fresh06_any_bad_leg_blocks_whole_group_before_submission():
    fresh = FreshnessVerdict(FreshnessStatus.FRESH, "ok", "v1", instrument_id="1", symbol="A")
    stale = FreshnessVerdict(FreshnessStatus.STALE, "old", "v1", instrument_id="2", symbol="B")
    assert not permits_group_risk_increase((fresh, stale))
    assert not permits_group_risk_increase((fresh, None))


def test_fresh08_missing_exact_contract_quote_evidence_is_not_auto_executable():
    evidence = FreshnessEvidence(
        source="KIS_VTS_REST", endpoint="/quote", tr_id="FHMIF10010000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        raw_source_time="101500", source_instant=None,
        received_at=datetime(2026, 10, 15, 1, 15, tzinfo=timezone.utc),
        raw_payload_sha256="d" * 64, source_time_semantics_verified=False,
        capability_verified=True,
    )
    verdict = evaluate_freshness(evidence, policy=FreshnessPolicy("disabled"))
    assert verdict.status is FreshnessStatus.UNKNOWN
