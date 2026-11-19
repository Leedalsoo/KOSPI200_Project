from decimal import Decimal
from types import SimpleNamespace

from environments.virtual.authoritative_vssf.canonical import VSSFOrderResult
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter


STAMP = "2026-10-22T02:16:00+09:00"


class _Context:
    def build_command(self, order):
        return order


class _Runtime:
    def __init__(self):
        self.result = VSSFOrderResult(
            client_order_id="client-1",
            status="FILLED",
            submitted_at=STAMP,
            observed_at=STAMP,
            remaining_qty=0,
            exec_id="exec-1",
            executed_qty=1,
            executed_price=Decimal("42.25"),
            fee=Decimal("0"),
            executed_at=STAMP,
        )

    def process_order(self, command):
        return self.result

    def query_order(self, client_order_id):
        assert client_order_id == "client-1"
        return self.result

    def cancel_order(self, client_order_id, *, lifecycle_reason="MANUAL"):
        assert client_order_id == "client-1"
        return self.result


def _adapter_and_order():
    adapter = VSSFExecutionAdapter(_Context(), _Runtime())
    order = SimpleNamespace(client_order_id="client-1", group_id="group-1", leg_id="leg-1")
    return adapter, order


def test_execute_propagates_group_and_leg_metadata_to_canonical_report():
    adapter, order = _adapter_and_order()

    report = adapter.execute(order)

    assert report.status == "FILLED"
    assert report.group_id == "group-1"
    assert report.leg_id == "leg-1"


def test_query_and_cancel_keep_original_group_and_leg_metadata():
    adapter, order = _adapter_and_order()
    adapter.execute(order)

    queried = adapter.query("client-1")
    cancelled = adapter.cancel("client-1", lifecycle_reason="VALIDATION_ONLY_TEST")

    assert queried is not None
    assert (queried.group_id, queried.leg_id) == ("group-1", "leg-1")
    assert (cancelled.group_id, cancelled.leg_id) == ("group-1", "leg-1")
def test_vssf_group_leg_metadata_survives_adapter_recreation_and_cancel_query():
    from dataclasses import replace

    runtime = _Runtime()
    runtime.result = replace(
        runtime.result,
        group_id="group-1",
        leg_id="leg-1",
    )
    first_adapter = VSSFExecutionAdapter(_Context(), runtime)
    order = SimpleNamespace(
        client_order_id="client-1",
        group_id="group-1",
        leg_id="leg-1",
    )
    first_adapter.execute(order)

    restarted_adapter = VSSFExecutionAdapter(_Context(), runtime)
    queried = restarted_adapter.query("client-1")
    cancelled = restarted_adapter.cancel(
        "client-1",
        lifecycle_reason="VALIDATION_ONLY_RESTART_TEST",
    )

    assert queried is not None
    assert (queried.group_id, queried.leg_id) == ("group-1", "leg-1")
    assert (cancelled.group_id, cancelled.leg_id) == ("group-1", "leg-1")

def test_canonical_execution_report_mapping_preserves_group_and_leg_metadata():
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalExecutionReport,
        CanonicalOptionType,
        CanonicalOrderSide,
    )

    canonical = CanonicalExecutionReport(
        exec_id="canonical-exec-1",
        client_order_id="client-1",
        track_id="track-1",
        asset_type=CanonicalAssetType.OPTION,
        side=CanonicalOrderSide.BUY,
        executed_qty=1,
        executed_price=42.25,
        fee=0.0,
        slippage=0.0,
        timestamp=STAMP,
        symbol="SYNTHETIC-CALL",
        option_type=CanonicalOptionType.CALL,
        strike=500.0,
        expiry="20261105",
        strategy_id="strategy-1",
        group_id="group-canonical",
        leg_id="leg-canonical",
        instrument_id="SYNTHETIC-CALL",
        contract_multiplier=250000.0,
        identity_source="SYNTHETIC_VALIDATION_ONLY",
    )

    report = VSSFExecutionAdapter(_Context(), _Runtime())._map(canonical)

    assert (report.group_id, report.leg_id) == (
        "group-canonical",
        "leg-canonical",
    )
