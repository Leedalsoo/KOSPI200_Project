from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.validation_only_s4_group_account_risk_reconciler import (
    reconcile_s4_group_account_risk,
)

INSTRUMENT = "SYNTHETIC:MINI:SHARED"


def _lot(*, strategy: str, group: str, side: str, qty: int, execution_id: str):
    return SimpleNamespace(
        run_id="SYNTHETIC:S4:F14:RUN", strategy_id=strategy, group_id=group,
        instrument_id=INSTRUMENT, execution_id=execution_id, side=side,
        remaining_quantity=qty, contract_multiplier=Decimal(50000),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def _runtime_and_bridge(lots, *, vssf_positions, bridge_positions):
    bridge = SimpleNamespace(
        run_id="SYNTHETIC:S4:F14:RUN",
        position_lot_store=SimpleNamespace(open_lots=lambda: tuple(lots)),
        leg_positions=bridge_positions,
    )
    runtime = SimpleNamespace(account=SimpleNamespace(
        validation_run_id="SYNTHETIC:S4:F14:RUN",
        validation_candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
        positions=vssf_positions,
    ))
    return bridge, runtime


def test_reconciles_group_gross_exposure_when_account_and_bridge_net_to_flat():
    lots = (
        _lot(strategy="S4", group="group-a", side="SELL", qty=2, execution_id="exec-a"),
        _lot(strategy="S4", group="group-b", side="SELL", qty=1, execution_id="exec-b"),
        _lot(strategy="S3", group="group-c", side="BUY", qty=3, execution_id="exec-c"),
    )
    bridge, runtime = _runtime_and_bridge(lots, vssf_positions={}, bridge_positions={})

    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
        fixture_group_caps={
            ("SYNTHETIC:S4:F14:RUN", "S4", "group-a", INSTRUMENT): 2,
            ("SYNTHETIC:S4:F14:RUN", "S4", "group-b", INSTRUMENT): 2,
        },
    )

    assert result.status == "VALIDATION_ONLY_S4_GROUP_ACCOUNT_RECONCILED"
    assert result.group_projection.group_positions[("SYNTHETIC:S4:F14:RUN", "S4", "group-a", INSTRUMENT)].net_signed_qty == -2
    assert result.group_projection.group_positions[("SYNTHETIC:S4:F14:RUN", "S4", "group-b", INSTRUMENT)].net_signed_qty == -1
    account = result.group_projection.account_positions[INSTRUMENT]
    assert (account.net_signed_qty, account.gross_long_qty, account.gross_short_qty) == (0, 3, 3)
    assert result.fixture_group_cap_breaches == ()
    assert result.production_risk_gate_connected is False


def test_vssf_position_drift_is_reported_without_mutating_any_projection():
    lots = (_lot(strategy="S4", group="group-a", side="SELL", qty=2, execution_id="exec-a"),)
    vssf = {INSTRUMENT: {"side": "SELL", "qty": 1, "contract_multiplier": Decimal(50000)}}
    bridge_positions = {INSTRUMENT: SimpleNamespace(
        side="SELL", qty=2, contract_multiplier=Decimal(50000),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )}
    bridge, runtime = _runtime_and_bridge(lots, vssf_positions=vssf, bridge_positions=bridge_positions)

    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "S4_F14_VSSF_POSITION_MISMATCH:SYNTHETIC:MINI:SHARED" in result.issues
    assert vssf[INSTRUMENT]["qty"] == 1
    assert bridge_positions[INSTRUMENT].qty == 2


def test_bridge_aggregate_drift_is_reported():
    lots = (_lot(strategy="S4", group="group-a", side="SELL", qty=2, execution_id="exec-a"),)
    bridge_positions = {INSTRUMENT: SimpleNamespace(
        side="SELL", qty=1, contract_multiplier=Decimal(50000),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )}
    bridge, runtime = _runtime_and_bridge(
        lots, vssf_positions={INSTRUMENT: {"side": "SELL", "qty": 2, "contract_multiplier": Decimal(50000)}},
        bridge_positions=bridge_positions,
    )
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "S4_F14_BRIDGE_POSITION_MISMATCH:SYNTHETIC:MINI:SHARED" in result.issues


def test_missing_candidate_scope_uses_synthetic_fallback_status_not_false_pass():
    lots = (_lot(strategy="S4", group="group-a", side="SELL", qty=1, execution_id="exec-a"),)
    bridge, runtime = _runtime_and_bridge(
        lots, vssf_positions={INSTRUMENT: {"side": "SELL", "qty": 1, "contract_multiplier": Decimal(50000)}},
        bridge_positions={INSTRUMENT: SimpleNamespace(
            side="SELL", qty=1, contract_multiplier=Decimal(50000),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        )},
    )
    runtime.account.validation_candidate_id = None
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )
    assert result.status == "INSUFFICIENT_SCOPE_EVIDENCE"
    assert "S4_F14_CANDIDATE_SCOPE_UNVERIFIED" in result.issues


def test_fixture_group_caps_are_scoped_per_group_and_never_become_operating_limits():
    lots = (
        _lot(strategy="S4", group="group-a", side="SELL", qty=3, execution_id="exec-a"),
        _lot(strategy="S4", group="group-b", side="SELL", qty=1, execution_id="exec-b"),
    )
    bridge, runtime = _runtime_and_bridge(
        lots, vssf_positions={INSTRUMENT: {"side": "SELL", "qty": 4, "contract_multiplier": Decimal(50000)}},
        bridge_positions={INSTRUMENT: SimpleNamespace(
            side="SELL", qty=4, contract_multiplier=Decimal(50000),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        )},
    )
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
        fixture_group_caps={
            ("SYNTHETIC:S4:F14:RUN", "S4", "group-a", INSTRUMENT): 2,
            ("SYNTHETIC:S4:F14:RUN", "S4", "group-b", INSTRUMENT): 2,
        },
    )
    assert result.status == "FIXTURE_GROUP_CAP_EXCEEDED"
    assert result.fixture_group_cap_breaches == (
        ("SYNTHETIC:S4:F14:RUN", "S4", "group-a", INSTRUMENT, 3, 2),
    )
    assert result.production_risk_gate_connected is False


def test_foreign_run_position_lot_is_not_silently_folded_into_current_run():
    lots = (_lot(strategy="S4", group="group-a", side="SELL", qty=1, execution_id="exec-a"),)
    lots[0].run_id = "SYNTHETIC:OTHER:RUN"
    bridge, runtime = _runtime_and_bridge(lots, vssf_positions={}, bridge_positions={})
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "S4_F14_POSITION_LOT_RUN_SCOPE_MISMATCH:exec-a" in result.issues

def test_actual_virtual_account_and_bridge_flat_views_preserve_group_gross_lots():
    from environments.virtual.authoritative_vssf.paper_account import (
        PaperTradingAccount,
    )
    from environments.virtual.position.virtual_position_aggregate import (
        VirtualPositionAggregate,
    )

    run_id = "SYNTHETIC:S4:F14:RUN"
    candidate_id = "SYNTHETIC:S4:F14:CANDIDATE"
    account = PaperTradingAccount(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    aggregate = VirtualPositionAggregate(instrument_id=INSTRUMENT)
    lots = []
    fills = (
        ("S4", "group-a", "SELL", 2, "exec-a"),
        ("S4", "group-b", "SELL", 1, "exec-b"),
        ("S3", "group-c", "BUY", 3, "exec-c"),
    )
    for strategy, group, side, qty, execution_id in fills:
        report = SimpleNamespace(
            exec_id=execution_id, client_order_id=f"order-{execution_id}",
            track_id=strategy, strategy_id=strategy, group_id=group, leg_id="mini",
            instrument_id=INSTRUMENT, identity_source="SYNTHETIC:DERIVED_SCENARIO",
            symbol=INSTRUMENT, asset_type="FUTURES", option_type=None, strike=None, expiry=None,
            side=side, executed_qty=qty, executed_price=1000, fee=Decimal(0),
            contract_multiplier=Decimal(50000), timestamp=datetime(2026, 11, 27, 5, 0, tzinfo=UTC),
        )
        account.apply_execution(report)
        aggregate.apply_fill(
            side=side, quantity=qty, price=1000,
            contract_multiplier=Decimal(50000),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        )
        lots.append(_lot(
            strategy=strategy, group=group, side=side, qty=qty, execution_id=execution_id,
        ))
    bridge = SimpleNamespace(
        run_id=run_id,
        position_lot_store=SimpleNamespace(open_lots=lambda: tuple(lots)),
        leg_positions={INSTRUMENT: aggregate},
    )
    runtime = SimpleNamespace(account=account)

    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime, run_id=run_id, candidate_id=candidate_id,
    )

    assert account.positions == {}
    assert aggregate.qty == 0 and aggregate.side is None
    assert result.status == "VALIDATION_ONLY_S4_GROUP_ACCOUNT_RECONCILED"
    account_exposure = result.group_projection.account_positions[INSTRUMENT]
    assert (account_exposure.net_signed_qty, account_exposure.gross_long_qty, account_exposure.gross_short_qty) == (0, 3, 3)


def test_missing_account_contract_multiplier_is_not_treated_as_valid_exposure():
    lots = (_lot(strategy="S4", group="group-a", side="SELL", qty=1, execution_id="exec-a"),)
    bridge_positions = {INSTRUMENT: SimpleNamespace(
        side="SELL", qty=1, contract_multiplier=Decimal(50000),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )}
    bridge, runtime = _runtime_and_bridge(
        lots, vssf_positions={INSTRUMENT: {"side": "SELL", "qty": 1}},
        bridge_positions=bridge_positions,
    )
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert f"S4_F14_VSSF_POSITION_MULTIPLIER_REQUIRED:{INSTRUMENT}" in result.issues


def test_zero_bridge_aggregate_is_a_valid_flat_projection_when_gross_lots_offset():
    lots = (
        _lot(strategy="S4", group="group-a", side="SELL", qty=2, execution_id="exec-a"),
        _lot(strategy="S3", group="group-b", side="BUY", qty=2, execution_id="exec-b"),
    )
    bridge, runtime = _runtime_and_bridge(
        lots, vssf_positions={},
        bridge_positions={INSTRUMENT: SimpleNamespace(
            side=None, qty=0, contract_multiplier=Decimal(50000),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        )},
    )
    result = reconcile_s4_group_account_risk(
        bridge=bridge, vssf_runtime=runtime,
        run_id="SYNTHETIC:S4:F14:RUN", candidate_id="SYNTHETIC:S4:F14:CANDIDATE",
    )
    assert result.status == "VALIDATION_ONLY_S4_GROUP_ACCOUNT_RECONCILED"
    exposure = result.group_projection.account_positions[INSTRUMENT]
    assert exposure.net_signed_qty == 0
    assert exposure.gross_long_qty == exposure.gross_short_qty == 2
