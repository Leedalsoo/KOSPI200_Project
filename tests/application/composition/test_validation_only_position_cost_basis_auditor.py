from datetime import datetime, timezone
from decimal import Decimal

from application.composition.validation_only_position_cost_basis_auditor import (
    ValidationOnlyPositionCostBasisAuditor,
)

NOW = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)


def opening_lot():
    return {"instrument_id": "OPT_A", "execution_id": "OPEN-1", "side": "BUY",
            "quantity": 2, "unit_price": "10", "contract_multiplier": "100000",
            "remaining_opening_fee": "20", "executed_at": NOW.isoformat()}


def execution(execution_id, side, qty, price, when):
    return {"execution_id": execution_id, "instrument_id": "OPT_A", "side": side,
            "quantity": qty, "price": str(price), "contract_multiplier": "100000",
            "executed_at": when.isoformat(), "client_order_id": f"CO-{execution_id}",
            "strategy_id": "SYNTHETIC:S1", "group_id": "G1", "leg_id": "L1",
            "source": "SYNTHETIC:DERIVED_SCENARIO"}


def fee(exec_row, amount):
    return {"execution_id": exec_row["execution_id"], "instrument_id": exec_row["instrument_id"],
            "quantity": exec_row["quantity"], "price": exec_row["price"], "fee_amount": str(amount),
            "executed_at": exec_row["executed_at"], "client_order_id": exec_row["client_order_id"],
            "strategy_id": exec_row["strategy_id"], "group_id": exec_row["group_id"],
            "leg_id": exec_row["leg_id"], "source": "SYNTHETIC:FEE_FIXTURE"}


def audit(opening, executions, fees, target):
    return ValidationOnlyPositionCostBasisAuditor(validation_only=True).audit(
        opening_lots=opening, executions=executions, fee_records=fees,
        target_positions=target, source_namespace="SYNTHETIC:POSITION_COST_BASIS",
        deterministic_rule_id="FIFO-FEE-ALLOCATION-v1", source_manifest_sha256="a" * 64,
        source_anchor_refs=("anchor-1",), source_anchor_as_of=NOW,
        scenario_timestamp=NOW, evidence_refs=("fixture-1",), opening_snapshot_as_of=NOW, as_of=NOW,
    )


def test_fifo_cost_basis_realized_gross_net_fees_and_remaining_average_cost():
    close = execution("CLOSE-1", "SELL", 1, 12, NOW)
    result = audit(
        [opening_lot()], [close], [fee(close, "5")],
        [{"instrument_id": "OPT_A", "side": "BUY", "quantity": 1, "average_price": "10"}],
    )
    assert result.is_reconciled
    assert result.realized_gross_pnl == Decimal("200000")
    assert result.realized_net_pnl == Decimal("199985")
    assert result.total_fees == Decimal("15")
    assert result.closing_fees == Decimal("5")
    assert result.opening_fees_realized == Decimal("10")
    assert result.opening_fees_remaining == Decimal("10")
    assert result.manifest_sha256 and len(result.manifest_sha256) == 64
    assert result.migration_applied is False


def test_fifo_cost_basis_allocates_opening_and_closing_fees_on_full_close():
    close = execution("CLOSE-1", "SELL", 2, 12, NOW)
    result = audit([opening_lot()], [close], [fee(close, "8")], [])
    assert result.is_reconciled
    assert result.realized_gross_pnl == Decimal("400000")
    assert result.realized_net_pnl == Decimal("399972")
    assert result.total_fees == Decimal("28")
    assert result.opening_fees_realized == Decimal("20")
    assert result.opening_fees_remaining == Decimal("0")


def test_fifo_cost_basis_rejects_fee_execution_crosswalk_mismatch():
    close = execution("CLOSE-1", "SELL", 1, 12, NOW)
    bad_fee = fee(close, "5")
    bad_fee["client_order_id"] = "OTHER-ORDER"
    result = audit([opening_lot()], [close], [bad_fee],
                   [{"instrument_id": "OPT_A", "side": "BUY", "quantity": 1, "average_price": "10"}])
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "COST_BASIS_FEE_EXECUTION_CLIENT_ORDER_MISMATCH:CLOSE-1" in result.issues


def test_fifo_cost_basis_rejects_target_average_price_mismatch_without_blocking_data_discovery():
    close = execution("CLOSE-1", "SELL", 1, 12, NOW)
    result = audit([opening_lot()], [close], [fee(close, "5")],
                   [{"instrument_id": "OPT_A", "side": "BUY", "quantity": 1, "average_price": "11"}])
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "COST_BASIS_TARGET_AVERAGE_PRICE_MISMATCH:OPT_A" in result.issues


def test_fifo_cost_basis_rejects_future_source_anchor_and_missing_fee_record():
    close = execution("CLOSE-1", "SELL", 1, 12, NOW)
    auditor = ValidationOnlyPositionCostBasisAuditor(validation_only=True)
    result = auditor.audit(
        opening_lots=[opening_lot()], executions=[close], fee_records=[],
        target_positions=[{"instrument_id": "OPT_A", "side": "BUY", "quantity": 1, "average_price": "10"}],
        source_namespace="SYNTHETIC:POSITION_COST_BASIS", deterministic_rule_id="FIFO-v1",
        source_manifest_sha256="a" * 64, source_anchor_refs=("anchor-1",),
        source_anchor_as_of=datetime(2026, 11, 19, tzinfo=timezone.utc),
        scenario_timestamp=NOW, evidence_refs=("fixture-1",), opening_snapshot_as_of=NOW, as_of=NOW,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "COST_BASIS_FUTURE_SOURCE_ANCHOR_REJECTED" in result.issues
    assert "COST_BASIS_EXECUTION_FEE_LEDGER_COVERAGE_MISMATCH" in result.issues


def test_cost_basis_auditor_requires_validation_only_opt_in():
    try:
        ValidationOnlyPositionCostBasisAuditor()
    except ValueError as exc:
        assert str(exc) == "COST_BASIS_VALIDATION_ONLY_OPT_IN_REQUIRED"
    else:
        raise AssertionError("validation-only opt-in was not enforced")



def test_cost_basis_rejects_execution_before_opening_snapshot():
    earlier = datetime(2026, 11, 18, 0, 59, tzinfo=timezone.utc)
    close = execution("CLOSE-1", "SELL", 1, 12, earlier)
    result = ValidationOnlyPositionCostBasisAuditor(validation_only=True).audit(
        opening_lots=[opening_lot()], executions=[close], fee_records=[fee(close, "5")],
        target_positions=[{"instrument_id": "OPT_A", "side": "BUY", "quantity": 1, "average_price": "10"}],
        source_namespace="SYNTHETIC:POSITION_COST_BASIS", deterministic_rule_id="FIFO-v1",
        source_manifest_sha256="a" * 64, source_anchor_refs=("anchor-1",),
        source_anchor_as_of=NOW, scenario_timestamp=NOW, evidence_refs=("fixture-1",),
        opening_snapshot_as_of=NOW, as_of=NOW,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "COST_BASIS_EXECUTION_BEFORE_OPENING_SNAPSHOT" in result.issues
