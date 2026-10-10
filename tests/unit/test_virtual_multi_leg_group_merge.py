from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def test_deferred_leg_fill_merges_with_prior_filled_leg_and_replaces_same_leg_status():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.groups = {
        "run-pair": [
            SimpleNamespace(leg_id="put", status="FILLED", execution_id="EXEC-PUT"),
        ]
    }
    group_plan = SimpleNamespace(
        group_id="run-pair",
        legs=(SimpleNamespace(leg_id="call"), SimpleNamespace(leg_id="put")),
    )

    pending_call = SimpleNamespace(leg_id="call", status="NEW", execution_id=None)
    first_merge = bridge._merge_group_reports(group_plan, [pending_call])
    bridge.groups["run-pair"] = list(first_merge)

    filled_call = SimpleNamespace(leg_id="call", status="FILLED", execution_id="EXEC-CALL")
    final_merge = bridge._merge_group_reports(group_plan, [filled_call])

    assert [report.leg_id for report in final_merge] == ["call", "put"]
    assert [(report.leg_id, report.status) for report in final_merge] == [
        ("call", "FILLED"),
        ("put", "FILLED"),
    ]
    assert [report.execution_id for report in final_merge] == ["EXEC-CALL", "EXEC-PUT"]


def test_deferred_leg_keeps_other_leg_report_when_same_group_is_reexecuted():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.groups = {
        "run-pair": [
            SimpleNamespace(leg_id="call", status="FILLED", execution_id="EXEC-CALL"),
            SimpleNamespace(leg_id="put", status="FILLED", execution_id="EXEC-PUT"),
        ]
    }
    group_plan = SimpleNamespace(
        group_id="run-pair",
        legs=(SimpleNamespace(leg_id="call"), SimpleNamespace(leg_id="put")),
    )

    newer_put = SimpleNamespace(leg_id="put", status="FILLED", execution_id="EXEC-PUT-2")
    merged = bridge._merge_group_reports(group_plan, [newer_put])

    assert [report.leg_id for report in merged] == ["call", "put"]
    assert [report.execution_id for report in merged] == ["EXEC-CALL", "EXEC-PUT-2"]


def test_execution_report_history_preserves_distinct_partial_fill_events():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.groups = {"run-pair": []}
    group_plan = SimpleNamespace(group_id="run-pair", legs=(SimpleNamespace(leg_id="call"),))
    first = SimpleNamespace(leg_id="call", client_order_id="ORDER-1", status="PARTIALLY_FILLED",
                            execution_id="EXEC-1", filled_quantity=2, execution_timestamp="2026-10-10T09:00:00")
    second = SimpleNamespace(leg_id="call", client_order_id="ORDER-1", status="FILLED",
                             execution_id="EXEC-2", filled_quantity=3, execution_timestamp="2026-10-10T09:00:01")
    merged = bridge._merge_group_reports(group_plan, [first, second])
    assert [report.execution_id for report in merged] == ["EXEC-1", "EXEC-2"]
    bridge.groups["run-pair"] = list(merged)
    replayed = bridge._merge_group_reports(group_plan, [first])
    assert [report.execution_id for report in replayed] == ["EXEC-1", "EXEC-2"]


def test_client_order_id_is_stable_for_same_intent_and_changes_with_residual_quantity():
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    plan = SimpleNamespace(group_id="group-1", strategy_id="Strategy_5")
    identity = SimpleNamespace(instrument_id="FUT-202610", symbol="FUT-202610")
    leg = SimpleNamespace(leg_id="FUTURES_EXIT", side="BUY", quantity=5, position_role="NONE")
    same_intent = SimpleNamespace(leg_id="FUTURES_EXIT", side="BUY", quantity=5, position_role="NONE")
    residual = SimpleNamespace(leg_id="FUTURES_EXIT", side="BUY", quantity=3, position_role="NONE")
    first = VirtualMultiLegExecutionBridge._client_order_id(plan, leg, identity)
    assert first == VirtualMultiLegExecutionBridge._client_order_id(plan, same_intent, identity)
    assert first != VirtualMultiLegExecutionBridge._client_order_id(plan, residual, identity)


def test_position_flat_check_is_conservative_and_uses_strategy_instrument_lots():
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: (
        SimpleNamespace(strategy_id="Strategy_6", instrument_id="OPT-PUT", remaining_quantity=1),
    ))
    bridge.identity_for_leg = lambda plan, leg: SimpleNamespace(instrument_id=leg.instrument_id)
    plan = SimpleNamespace(strategy_id="Strategy_6", legs=(SimpleNamespace(instrument_id="OPT-PUT"),))
    assert bridge._position_flat_for_plan(plan) is False
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: ())
    assert bridge._position_flat_for_plan(plan) is True


def test_position_flat_check_fails_closed_when_identity_cannot_be_resolved():
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: ())
    bridge.identity_for_leg = lambda plan, leg: (_ for _ in ()).throw(ValueError("identity unavailable"))
    plan = SimpleNamespace(strategy_id="Strategy_6", legs=(SimpleNamespace(),))
    assert bridge._position_flat_for_plan(plan) is False


def test_authoritative_close_plan_uses_original_group_residual_quantity_and_identity():
    from datetime import datetime
    from decimal import Decimal
    from contracts.position_provenance import PositionLotProvenance, PositionRole
    from contracts.types import OptionInstrumentIdentity
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge

    identity = OptionInstrumentIdentity(
        instrument_id="OPT-20261029-P-350", symbol="OPT-20261029-P-350",
        expiry="20261029", option_type="PUT", strike=Decimal("350"),
        contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
    )
    lot = PositionLotProvenance(
        run_id="run-1", instrument_id=identity.instrument_id,
        strategy_id="track6_daily_tail_insurance", group_id="original-group",
        leg_id="put", client_order_id="entry-order", execution_id="entry-fill",
        side="BUY", opened_quantity=3, remaining_quantity=2,
        execution_timestamp=datetime(2026, 10, 10, 9, 0),
        instrument_identity=identity, contract_multiplier=Decimal("250000"),
        identity_source="OPTION_MASTER", position_role=PositionRole.NONE,
    )
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "run-1"
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: (lot,))

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track6_daily_tail_insurance",
        purpose="DAILY_TAIL_INSURANCE_TRAILING_CLOSE",
    )

    assert plan.group_id == "original-group"
    assert plan.strategy_id == "track6_daily_tail_insurance"
    assert plan.purpose == "DAILY_TAIL_INSURANCE_TRAILING_CLOSE"
    assert len(plan.legs) == 1
    assert plan.legs[0].side == "SELL"
    assert plan.legs[0].quantity == 2
    assert plan.legs[0].instrument_identity == identity


def test_authoritative_close_plan_fails_closed_for_multiple_open_groups():
    from datetime import datetime
    from decimal import Decimal
    from contracts.position_provenance import PositionLotProvenance, PositionRole
    from contracts.types import OptionInstrumentIdentity
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge

    identity = OptionInstrumentIdentity(
        instrument_id="OPT-20261029-P-350", symbol="OPT-20261029-P-350",
        expiry="20261029", option_type="PUT", strike=Decimal("350"),
        contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
    )
    def lot(group_id, execution_id):
        return PositionLotProvenance(
            run_id="run-1", instrument_id=identity.instrument_id,
            strategy_id="track6_daily_tail_insurance", group_id=group_id,
            leg_id="put", client_order_id=f"order-{execution_id}", execution_id=execution_id,
            side="BUY", opened_quantity=1, remaining_quantity=1,
            execution_timestamp=datetime(2026, 10, 10, 9, 0),
            instrument_identity=identity, contract_multiplier=Decimal("250000"),
            identity_source="OPTION_MASTER", position_role=PositionRole.NONE,
        )
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "run-1"
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: (lot("group-a", "fill-a"), lot("group-b", "fill-b")))

    import pytest
    with pytest.raises(ValueError, match="AMBIGUOUS_OPEN_POSITION_GROUPS"):
        bridge.build_close_plan_from_open_lots(
            strategy_id="track6_daily_tail_insurance", purpose="CLOSE",
        )


def test_group_preflight_preserves_originating_leg_rejection_reason():
    from types import SimpleNamespace
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge

    failed_leg = SimpleNamespace(rejection_reason="RISK_GUARD_STATUS_UNAVAILABLE")
    allowed_leg = SimpleNamespace(rejection_reason=None)

    assert VirtualMultiLegExecutionBridge._preflight_rejection_reason(
        failed_leg, False, None
    ) == "RISK_GUARD_STATUS_UNAVAILABLE"
    assert VirtualMultiLegExecutionBridge._preflight_rejection_reason(
        allowed_leg, True, None
    ) == "GROUP_RISK_PREFLIGHT_REJECTED"
    assert VirtualMultiLegExecutionBridge._preflight_rejection_reason(
        failed_leg, False, "GROUP_INSUFFICIENT_FREE_MARGIN"
    ) == "GROUP_INSUFFICIENT_FREE_MARGIN"
