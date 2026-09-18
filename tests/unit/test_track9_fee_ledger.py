from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.track9_fee_ledger import Track9FeeRecord
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger


def _fee(amount: str = "12.5") -> Track9FeeRecord:
    return Track9FeeRecord(
        run_id="RUN-1",
        strategy_id="TRACK9",
        group_id="G1",
        leg_id="L1",
        client_order_id="G1-L1",
        execution_id="EXEC-1",
        instrument_id="OPT-1",
        fee_amount=Decimal(amount),
        executed_quantity=2,
        executed_price=Decimal("3.25"),
        executed_at=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
        source="VSSF:CanonicalExecutionReport.fee",
    )


def test_fee_ledger_is_idempotent_and_sums_authoritative_execution_fees():
    ledger = VirtualTrack9FeeLedger()
    ledger.record(_fee("12.5"))
    ledger.record(_fee("12.5"))
    second = _fee("2.5")
    second = Track9FeeRecord(
        **{**second.__dict__, "execution_id": "EXEC-2", "client_order_id": "G1-L2", "leg_id": "L2"}
    )
    ledger.record(second)
    assert ledger.total(run_id="RUN-1") == Decimal("15.0")
    assert len(ledger.query(run_id="RUN-1")) == 2


def test_fee_ledger_rejects_same_execution_with_different_fee():
    ledger = VirtualTrack9FeeLedger()
    ledger.record(_fee("12.5"))
    with pytest.raises(ValueError, match="TRACK9_FEE_DUPLICATE_CONFLICT"):
        ledger.record(_fee("13.0"))


def test_fee_ledger_enforces_time_range_and_provenance():
    ledger = VirtualTrack9FeeLedger()
    ledger.record(_fee())
    assert ledger.query(
        run_id="RUN-1",
        start=datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="TRACK9_FEE_PROVENANCE_REQUIRED"):
        Track9FeeRecord(
            run_id="",
            strategy_id="TRACK9",
            group_id="G1",
            leg_id="L1",
            client_order_id="G1-L1",
            execution_id="EXEC-X",
            instrument_id="OPT-1",
            fee_amount=Decimal("1"),
            executed_quantity=1,
            executed_price=Decimal("1"),
            executed_at=datetime.now(timezone.utc),
            source="VSSF",
        )
