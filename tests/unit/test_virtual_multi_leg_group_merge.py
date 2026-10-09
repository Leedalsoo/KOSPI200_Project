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
