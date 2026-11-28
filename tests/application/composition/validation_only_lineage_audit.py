"""Pure test-side read-only correlation checks for synthetic Runtime projections."""
from __future__ import annotations


def lineage_mismatches(
    *,
    expected_run_id: str,
    expected_strategy_id: str,
    group_records: tuple[tuple[str, str], ...],
    pending_records: tuple[tuple[str, str, str, str, str], ...],
    position_records: tuple[tuple[str, str, str, str, str, str, str, str], ...],
    fee_records: tuple[tuple[str, str, str, str, str, str, str], ...],
    execution_records: tuple[tuple[str, str, str, str, str, str, str], ...],
    reservation_records: tuple[tuple[str], ...],
    risk_audit_records: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Compare immutable scalar projections; never accepts a mutable runtime store."""
    mismatches: set[str] = set()
    groups = {group_id: strategy_id for group_id, strategy_id in group_records}
    if len(groups) != len(group_records):
        mismatches.add("group_projection_duplicate")

    pending_keys: set[tuple[str, str, str]] = set()
    for plan_group, plan_leg, command_group, command_leg, client_order_id in pending_records:
        if plan_group != command_group:
            mismatches.add("pending_group_mismatch")
        if plan_leg != command_leg:
            mismatches.add("pending_leg_mismatch")
        if plan_group not in groups or command_group not in groups:
            mismatches.add("pending_group_unknown")
        key = (plan_group, plan_leg, client_order_id)
        if key in pending_keys:
            mismatches.add("pending_projection_duplicate")
        pending_keys.add(key)

    positions_by_execution: dict[str, list[tuple[str, ...]]] = {}
    for record in position_records:
        run_id, strategy_id, group_id, _leg_id, _client_order_id, execution_id, _instrument_id, _expiry = record
        positions_by_execution.setdefault(execution_id, []).append(record)
        if run_id != expected_run_id:
            mismatches.add(f"position_run_mismatch:{execution_id}")
        if strategy_id != expected_strategy_id or groups.get(group_id) != expected_strategy_id:
            mismatches.add(f"position_strategy_or_group_mismatch:{execution_id}")
    for execution_id, rows in positions_by_execution.items():
        if len(rows) > 1:
            mismatches.add(f"position_execution_duplicate:{execution_id}")

    fees_by_execution: dict[str, list[tuple[str, ...]]] = {}
    for record in fee_records:
        run_id, strategy_id, group_id, _leg_id, _client_order_id, execution_id, _instrument_id = record
        fees_by_execution.setdefault(execution_id, []).append(record)
        if run_id != expected_run_id:
            mismatches.add(f"fee_run_mismatch:{execution_id}")
        if strategy_id != expected_strategy_id or groups.get(group_id) != expected_strategy_id:
            mismatches.add(f"fee_strategy_or_group_mismatch:{execution_id}")
    for execution_id, rows in fees_by_execution.items():
        if len(rows) > 1:
            mismatches.add(f"fee_execution_duplicate:{execution_id}")

    executions_by_id: dict[str, list[tuple[str, ...]]] = {}
    for record in execution_records:
        strategy_id, group_id, _leg_id, _client_order_id, execution_id, _instrument_id, _expiry = record
        executions_by_id.setdefault(execution_id, []).append(record)
        if strategy_id != expected_strategy_id or groups.get(group_id) != expected_strategy_id:
            mismatches.add(f"execution_strategy_or_group_mismatch:{execution_id}")
    for execution_id, rows in executions_by_id.items():
        if len(rows) > 1:
            mismatches.add(f"execution_duplicate:{execution_id}")
        if len(fees_by_execution.get(execution_id, ())) == 0:
            mismatches.add(f"fee_projection_missing:{execution_id}")
        elif len(fees_by_execution[execution_id]) == 1:
            fee = fees_by_execution[execution_id][0]
            execution = rows[0]
            if (fee[1], fee[2], fee[3], fee[4], fee[5], fee[6]) != (
                expected_strategy_id, execution[1], execution[2], execution[3], execution[4], execution[5]
            ):
                mismatches.add(f"fee_execution_lineage_mismatch:{execution_id}")

    for execution_id, rows in fees_by_execution.items():
        if execution_id not in executions_by_id:
            mismatches.add(f"fee_execution_orphan:{execution_id}")
    for execution_id, rows in positions_by_execution.items():
        execution_rows = executions_by_id.get(execution_id, ())
        fee_rows = fees_by_execution.get(execution_id, ())
        if not execution_rows:
            mismatches.add(f"position_execution_missing:{execution_id}")
        elif len(execution_rows) == 1:
            position, execution = rows[0], execution_rows[0]
            if (position[0], position[1], position[2], position[3], position[4], position[5], position[6], position[7]) != (
                expected_run_id, execution[0], execution[1], execution[2], execution[3], execution[4], execution[5], execution[6]
            ):
                mismatches.add(f"position_execution_lineage_mismatch:{execution_id}")
        if len(fee_rows) == 1 and len(rows) == 1:
            position, fee = rows[0], fee_rows[0]
            if (position[0], position[1], position[2], position[3], position[4], position[5], position[6]) != fee:
                mismatches.add(f"position_fee_lineage_mismatch:{execution_id}")

    audit_groups = set()
    for run_id, group_id in risk_audit_records:
        if run_id != expected_run_id or group_id not in groups:
            mismatches.add("risk_audit_run_or_group_mismatch")
        audit_groups.add(group_id)
    for (group_id,) in reservation_records:
        if group_id not in groups or group_id not in audit_groups:
            mismatches.add(f"reservation_without_matching_group_audit:{group_id}")
    return tuple(sorted(mismatches))
