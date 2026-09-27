from pathlib import Path
from application.composition.futures_identity_source import KisFuturesIdentitySource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from contracts.futures_contract_spec import FuturesProductType
from application.composition.track3_hedge_identity_source import Track3HedgeIdentitySource
from application.composition.track3_multi_leg_execution_plan_adapter import Track3MultiLegExecutionPlanAdapter


def _source():
    raw = (Path("fo_idx_code_mts.mst").read_bytes().decode("cp949", errors="replace"))
    source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(raw))
    return KisFuturesIdentitySource(source, FuturesTargetConfiguration(underlying_short_code="2001", product_type=FuturesProductType.STANDARD))


def test_track3_builds_two_leg_plan_from_authoritative_hedge_identity():
    identity_source = _source()
    identity = identity_source.current_identity()
    plan = Track3MultiLegExecutionPlanAdapter().build_plan(
        strategy_id="Strategy_3_StatArb", group_id="T3-G1", side="SELL", quantity=2,
        identity=identity, hedge_identity_source=Track3HedgeIdentitySource(identity_source),
    )
    assert [(leg.leg_id, leg.side, leg.quantity) for leg in plan.legs] == [("FUTURES", "SELL", 2), ("HEDGE", "BUY", 2)]
    assert plan.strategy_id == "Strategy_3_StatArb"
    assert plan.purpose == "TRACK3_STAT_ARB_FUTURES_HEDGE"


def test_track3_rejects_non_authoritative_or_mismatched_hedge_identity():
    identity_source = _source()
    identity = identity_source.current_identity()
    class Mismatch:
        def current_identity(self):
            from dataclasses import replace
            return replace(identity, instrument_id="OTHER")
    import pytest
    with pytest.raises(ValueError, match="TRACK3_HEDGE_IDENTITY_MISMATCH"):
        Track3MultiLegExecutionPlanAdapter().build_plan(
            strategy_id="Strategy_3_StatArb", group_id="T3-G2", side="BUY", quantity=1,
            identity=identity, hedge_identity_source=Mismatch(),
        )


def test_track3_rejects_missing_hedge_source():
    import pytest
    identity = _source().current_identity()
    with pytest.raises(ValueError, match="FUTURES_IDENTITY_SOURCE_REQUIRED"):
        Track3MultiLegExecutionPlanAdapter().build_plan(
            strategy_id="Strategy_3_StatArb", group_id="T3-G3", side="SELL", quantity=1,
            identity=identity, hedge_identity_source=None,
        )


def test_track3_multi_leg_virtual_bridge_fills_both_legs_and_preserves_provenance():
    from application.bootstrap import create_virtual_runtime_bootstrap
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from tests.risk_guard_test_support import allow_risk_guard

    identity_source = _source()
    identity = identity_source.current_identity()
    plan = Track3MultiLegExecutionPlanAdapter().build_plan(
        strategy_id="Strategy_3_StatArb",
        group_id="T3-BRIDGE-G1",
        side="SELL",
        quantity=1,
        identity=identity,
        hedge_identity_source=Track3HedgeIdentitySource(identity_source),
    )
    bootstrap = create_virtual_runtime_bootstrap(
        initial_capital=250_000_000.0,
        risk_guard_status_source=allow_risk_guard(),
    )
    bridge = VirtualMultiLegExecutionBridge(
        bundle=bootstrap.bundle,
        run_id="T3-BRIDGE-RUN",
        option_master=bootstrap.bundle.option_master,
        futures_identity_source=identity_source,
        risk_guard_status_source=allow_risk_guard(),
    )
    result = bridge.execute(plan)
    assert result.group_complete
    assert result.routed_legs == 2
    assert result.filled_legs == 2
    assert [report.leg_id for report in result.reports] == ["FUTURES", "HEDGE"]
    assert all(report.status == "FILLED" for report in result.reports)
    assert all(
        bridge.provenance[report.execution_id]["client_order_id"]
        == f"T3-BRIDGE-G1-{report.leg_id}"
        for report in result.reports
    )
