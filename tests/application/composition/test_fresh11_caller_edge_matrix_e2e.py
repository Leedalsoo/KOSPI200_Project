"""Shared freshness-gate regression for all registered strategy identifiers."""
import ast
from pathlib import Path

import pytest

from application.composition.runtime_authoritative_risk_router_adapter import route_from_runtime_authoritative_sources
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide

ROOT = Path(__file__).resolve().parents[3]
REGISTERED_STRATEGY_IDS = tuple(f"S{i}" for i in range(1, 10))
BLOCKING = (FreshnessStatus.UNKNOWN, FreshnessStatus.STALE, FreshnessStatus.CAPABILITY_CONFLICT)


class RiskGateSpy:
    def __init__(self):
        self.calls = 0

    def admit_order(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("freshness rejection must precede risk admission")


class RouterSpy:
    def __init__(self):
        self.calls = 0

    def register_and_route(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("freshness rejection must precede routing")


@pytest.mark.parametrize("strategy_id", REGISTERED_STRATEGY_IDS)
@pytest.mark.parametrize("status", BLOCKING)
def test_registered_strategy_ids_share_gate_before_risk_and_router(strategy_id, status):
    gate, router = RiskGateSpy(), RouterSpy()
    command = CanonicalOrderCommand(client_order_id=f"{strategy_id}-matrix", track_id=strategy_id,
        asset_type=CanonicalAssetType.OPTION, side=CanonicalOrderSide.BUY, qty=1, price=1.0,
        symbol="A12345", expiry="20261029", instrument_id="OPT-1")
    verdict = FreshnessVerdict(status, "ASSUMPTION: synthetic blocked verdict", "test-only",
        instrument_id="OPT-1", symbol="A12345", evidence_sha256="b" * 64)
    result = route_from_runtime_authoritative_sources(command, risk_gate=gate,
        context={"order_router": router}, freshness_verdict=verdict)
    assert not result.routed
    assert gate.calls == 0
    assert router.calls == 0


def test_factory_retains_expected_resolver_ids_without_claiming_active_scope():
    source = (ROOT / "application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    registrations = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "register"
        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    resolver_ids = {node.args[0].value for node in registrations}
    # S3/S4 registrations remain for compatibility; Current Baseline v2 excludes them from active Q25 scope.
    expected = {"TRACK1_TAIL_DEFENSE", "track2_asymmetric_trap", "track4_gamma_scalping",
        "track5_gap_divergence", "Strategy_3_StatArb", "track6_daily_tail_insurance",
        "track7_volatility_skew_weekly_insurance", "track8_macro_regime_monthly_strangle",
        "track9_event_overnight_insurance"}
    assert expected <= resolver_ids
    # Registration evidence is not proof of KIS-source lineage or every runtime caller edge.
