"""FRESH-06/FRESH-11 supplemental tests. Synthetic paths are explicitly ASSUMPTION fixtures."""
import ast
from pathlib import Path

import pytest

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from application.composition.runtime_authoritative_risk_router_adapter import route_from_runtime_authoritative_sources
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide

ROOT = Path(__file__).resolve().parents[3]


def _command(track_id="S1"):
    return CanonicalOrderCommand(
        client_order_id="fresh-impl-client", track_id=track_id,
        asset_type=CanonicalAssetType.OPTION, side=CanonicalOrderSide.BUY,
        qty=1, price=1.0, symbol="A12345", expiry="20261029",
        instrument_id="OPT-1",
    )


class _RiskGateMustNotRun:
    def __init__(self):
        self.calls = 0

    def admit_order(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("risk gate must not run for blocked freshness")


@pytest.mark.parametrize("status", [FreshnessStatus.UNKNOWN, FreshnessStatus.STALE, FreshnessStatus.CAPABILITY_CONFLICT])
def test_fresh11_all_strategy_ids_block_nonfresh_verdict_before_risk_or_router(status):
    # This exercises the real shared single-order admission seam, not KIS timestamp semantics.
    for strategy_id in (f"S{i}" for i in range(1, 10)):
        gate = _RiskGateMustNotRun()
        verdict = FreshnessVerdict(
            status, "ASSUMPTION: synthetic verdict fixture", "test-only",
            instrument_id="OPT-1", symbol="A12345", evidence_sha256="a" * 64,
        )
        result = route_from_runtime_authoritative_sources(
            _command(strategy_id), risk_gate=gate, context=None,
            freshness_verdict=verdict,
        )
        assert not result.routed, strategy_id
        assert gate.calls == 0, strategy_id


def test_fresh11_candidate_call_path_symbols_exist_but_full_s1_s9_lineage_is_not_proven():
    # Static inventory only; existence is not evidence that every runtime edge is connected.
    factory = ast.parse((ROOT / "application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8"))
    loop = ast.parse((ROOT / "application/composition/automated_virtual_trading_loop.py").read_text(encoding="utf-8"))
    adapter = ast.parse((ROOT / "application/composition/runtime_authoritative_risk_router_adapter.py").read_text(encoding="utf-8"))
    defs = {node.name for tree in (factory, loop, adapter) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "attach_standard_automated_loop" in defs
    assert "on_tick" in defs
    assert "route_from_runtime_authoritative_sources" in defs
    # Deliberately does not assert KIS->strategy input lineage or all resolver-to-broker edges.


def test_fresh06_actual_multileg_source_orders_freshness_preflight_before_router_submission():
    # Structural guard for current source ordering. Does not claim a full execute() fixture/E2E.
    path = ROOT / "application/composition/virtual_multi_leg_execution.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    execute = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute")
    calls = []
    for node in ast.walk(execute):
        if isinstance(node, ast.Call):
            fn = node.func
            calls.append((getattr(fn, "attr", getattr(fn, "id", "")), node.lineno))
    freshness_lines = [line for name, line in calls if name == "admits_freshness_verdict_for_identity"]
    route_lines = [line for name, line in calls if name == "route_from_runtime_authoritative_sources"]
    assert freshness_lines and route_lines
    assert max(freshness_lines) < min(route_lines)
    # Structural ordering only: zero-submit behavior at the actual runtime boundary remains unproven.
