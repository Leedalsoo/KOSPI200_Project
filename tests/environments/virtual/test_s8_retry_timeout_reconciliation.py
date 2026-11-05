from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.clock import VirtualClock
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter


class _CommandContext:
    def build_command(self, order):
        return order


def _command(client_order_id, qty=1):
    return SimpleNamespace(
        client_order_id=client_order_id,
        track_id="track8_macro_regime_monthly_strangle",
        asset_type="OPTION",
        side="BUY",
        qty=qty,
        price=Decimal("10"),
        requested_price=Decimal("10"),
        symbol="SYNTHETIC-CALL",
        option_type="CALL",
        strike=Decimal("500"),
        expiry="20261119",
        strategy_id="track8_macro_regime_monthly_strangle",
        group_id="S8-GROUP",
        leg_id="call",
        instrument_id="SYNTHETIC-CALL",
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC_VALIDATION_ONLY",
    )


def _runtime():
    clock = VirtualClock(datetime(2026, 11, 3, 9, 0))
    runtime = VirtualSecuritiesFirmRuntime(initial_capital=50_000_000, clock=clock)
    timeout = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("600"), "VALIDATION_ONLY_10M")
    )
    runtime.attach_timeout_source(timeout)
    return clock, runtime


def test_vssf_timeout_cancel_carries_reason_and_submission_timestamp():
    clock, runtime = _runtime()
    command = _command("timeout-order")
    runtime.process_order(command)
    clock.sleep_policy(600)
    runtime.process_timeouts()

    confirmed = runtime.query_order(command.client_order_id)
    assert confirmed.status == "CANCELLED"
    assert confirmed.lifecycle_reason == "TIMEOUT_10M"
    assert confirmed.submitted_at == "2026-11-03T09:00:00"
    assert confirmed.remaining_qty == 1


def test_manual_cancel_is_distinct_from_timeout_cancel():
    _clock, runtime = _runtime()
    command = _command("manual-order")
    runtime.process_order(command)
    cancelled = runtime.cancel_order(command.client_order_id)
    assert cancelled.status == "CANCELLED"
    assert cancelled.lifecycle_reason == "MANUAL"


def test_execution_adapter_preserves_timeout_metadata():
    clock, runtime = _runtime()
    adapter = VSSFExecutionAdapter(_CommandContext(), runtime)
    command = _command("adapter-timeout")
    submitted = adapter.execute(command)
    assert submitted.status == "NEW"
    assert submitted.submitted_at == datetime(2026, 11, 3, 9, 0)

    clock.sleep_policy(600)
    runtime.process_timeouts()
    confirmed = adapter.query(command.client_order_id)
    assert confirmed.status == "CANCELLED"
    assert confirmed.lifecycle_reason == "TIMEOUT_10M"
    assert confirmed.submitted_at == datetime(2026, 11, 3, 9, 0)


def test_partial_fill_is_reported_with_remaining_quantity_before_cancel():
    _clock, runtime = _runtime()
    command = _command("partial-order", qty=2)
    runtime.process_order(command)
    runtime.execution_engine.reports.append(SimpleNamespace(
        client_order_id=command.client_order_id,
        executed_qty=1,
        exec_id="PARTIAL-EXEC-1",
        executed_price=10.0,
        fee=0.0,
        timestamp="2026-11-03T09:05:00",
    ))

    partial = runtime.query_order(command.client_order_id)
    assert partial.status == "PARTIALLY_FILLED"
    assert partial.executed_qty == 1
    assert partial.remaining_qty == 1

    cancelled = runtime.cancel_order(command.client_order_id, lifecycle_reason="TIMEOUT_10M")
    assert cancelled.status == "CANCELLED"
    assert cancelled.executed_qty == 1
    assert cancelled.remaining_qty == 1
    assert cancelled.exec_id == "PARTIAL-EXEC-1"


def _append_fill(runtime, client_order_id, execution_id, quantity, price, fee, timestamp):
    runtime.execution_engine.reports.append(SimpleNamespace(
        client_order_id=client_order_id,
        executed_qty=quantity,
        exec_id=execution_id,
        executed_price=price,
        fee=fee,
        timestamp=timestamp,
    ))


def test_multiple_partial_fills_are_preserved_as_distinct_execution_events():
    _clock, runtime = _runtime()
    adapter = VSSFExecutionAdapter(_CommandContext(), runtime)
    command = _command("multi-partial-order", qty=5)
    adapter.execute(command)
    _append_fill(runtime, command.client_order_id, "FILL-001", 1, 10.0, 0.1, "2026-11-03T09:02:00")
    _append_fill(runtime, command.client_order_id, "FILL-002", 2, 11.0, 0.2, "2026-11-03T09:04:00")

    report = adapter.query(command.client_order_id)
    assert report.status == "PARTIALLY_FILLED"
    assert report.filled_quantity == 3
    assert report.remaining_quantity == 2
    assert report.execution_id is None
    assert report.execution_price == Decimal("32") / Decimal("3")
    assert report.fee == Decimal("0.3")
    assert [fill.execution_id for fill in report.execution_fills] == ["FILL-001", "FILL-002"]
    assert [fill.filled_quantity for fill in report.execution_fills] == [1, 2]
    assert [fill.execution_price for fill in report.execution_fills] == [Decimal("10.0"), Decimal("11.0")]

    cancelled = adapter.cancel(command.client_order_id)
    assert cancelled.status == "CANCELLED"
    assert cancelled.filled_quantity == 3
    assert cancelled.remaining_quantity == 2
    assert [fill.execution_id for fill in cancelled.execution_fills] == ["FILL-001", "FILL-002"]


def test_duplicate_identical_execution_id_is_deduplicated():
    _clock, runtime = _runtime()
    command = _command("duplicate-fill-order", qty=3)
    runtime.process_order(command)
    fill = dict(
        client_order_id=command.client_order_id,
        executed_qty=1,
        exec_id="DUPLICATE-FILL",
        executed_price=10.0,
        fee=0.1,
        timestamp="2026-11-03T09:02:00",
    )
    runtime.execution_engine.reports.extend((SimpleNamespace(**fill), SimpleNamespace(**fill)))

    report = runtime.query_order(command.client_order_id)
    assert report.status == "PARTIALLY_FILLED"
    assert report.executed_qty == 1
    assert report.remaining_qty == 2
    assert len(report.execution_fills) == 1


def test_cancel_race_after_all_quantity_filled_returns_filled_not_cancelled():
    _clock, runtime = _runtime()
    adapter = VSSFExecutionAdapter(_CommandContext(), runtime)
    command = _command("filled-before-cancel-order", qty=2)
    adapter.execute(command)
    _append_fill(runtime, command.client_order_id, "RACE-FILL-001", 1, 10.0, 0.1, "2026-11-03T09:02:00")
    _append_fill(runtime, command.client_order_id, "RACE-FILL-002", 1, 10.1, 0.1, "2026-11-03T09:03:00")

    # Pending order plus full reported quantity is contradictory until cancellation
    # removes the pending record; it must never be classified as a normal partial.
    assert adapter.query(command.client_order_id).status == "RECONCILIATION_REQUIRED"
    confirmed = adapter.cancel(command.client_order_id)
    assert confirmed.status == "FILLED"
    assert confirmed.filled_quantity == 2
    assert confirmed.remaining_quantity == 0
    assert confirmed.lifecycle_reason is None
    assert [fill.execution_id for fill in confirmed.execution_fills] == [
        "RACE-FILL-001", "RACE-FILL-002",
    ]


def test_conflicting_duplicate_or_overfill_fails_closed():
    _clock, runtime = _runtime()
    command = _command("conflicting-fill-order", qty=2)
    runtime.process_order(command)
    _append_fill(runtime, command.client_order_id, "CONFLICT-ID", 1, 10.0, 0.1, "2026-11-03T09:02:00")
    _append_fill(runtime, command.client_order_id, "CONFLICT-ID", 1, 10.5, 0.1, "2026-11-03T09:03:00")
    assert runtime.query_order(command.client_order_id).status == "RECONCILIATION_REQUIRED"

    _clock2, runtime2 = _runtime()
    command2 = _command("overfill-order", qty=2)
    runtime2.process_order(command2)
    _append_fill(runtime2, command2.client_order_id, "OVER-001", 2, 10.0, 0.1, "2026-11-03T09:02:00")
    _append_fill(runtime2, command2.client_order_id, "OVER-002", 1, 10.0, 0.1, "2026-11-03T09:03:00")
    assert runtime2.query_order(command2.client_order_id).status == "RECONCILIATION_REQUIRED"
