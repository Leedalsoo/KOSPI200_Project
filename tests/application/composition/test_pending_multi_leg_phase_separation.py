import ast
from pathlib import Path


def _calls(node):
    return {
        item.func.attr if isinstance(item.func, ast.Attribute)
        else item.func.id if isinstance(item.func, ast.Name)
        else ""
        for item in ast.walk(node) if isinstance(item, ast.Call)
    }


def _nested_callbacks():
    source = Path("application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    factory = next(
        item for item in module.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == "attach_standard_automated_loop"
    )
    return {
        item.name: item
        for item in factory.body
        if isinstance(item, ast.FunctionDef)
    }


def test_pending_observer_is_reconciliation_only():
    callbacks = _nested_callbacks()
    calls = _calls(callbacks["observe_pending_multi_leg"])

    assert "process_pending_quotes" in calls
    assert "refresh_track2_position_marks" in calls
    assert not calls.intersection({
        "cancel_pending_order", "cancel_repair_and_reconcile",
        "process_s9_entry_retries", "process_track2_entry_progress",
        "execute", "submit_repair", "submit_flatten",
    })


def test_pending_planner_only_builds_deferred_lifecycle_intents():
    callbacks = _nested_callbacks()
    calls = _calls(callbacks["plan_pending_multi_leg"])

    assert "lifecycle_clock_action" in calls
    assert not calls.intersection({
        "cancel_pending_order", "cancel_repair_and_reconcile",
        "process_s9_entry_retries", "process_track2_entry_progress",
        "execute", "submit_repair", "submit_flatten",
    })


def test_pending_processor_owns_cancel_repair_retry_and_entry_side_effects():
    callbacks = _nested_callbacks()
    calls = _calls(callbacks["process_pending_multi_leg"])

    assert {
        "cancel_pending_order", "cancel_repair_and_reconcile",
        "process_s9_entry_retries", "process_track2_entry_progress",
    }.issubset(calls)
    assert "process" in calls
