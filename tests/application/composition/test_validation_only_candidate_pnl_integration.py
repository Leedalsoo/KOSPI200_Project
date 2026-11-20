from datetime import datetime, timedelta, timezone
from decimal import Decimal

from application.composition.validation_only_runtime_ledger_comparator import (
    ValidationOnlyRuntimeLedgerComparator,
)
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.firm_runtime import (
    VirtualSecuritiesFirmRuntime,
)
from environments.virtual.authoritative_vssf.track9_fee_ledger import (
    VirtualTrack9FeeLedger,
)
from environments.virtual.position.virtual_position_lot_store import (
    VirtualPositionLotStore,
)
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalExecutionReport,
    CanonicalOptionType,
    CanonicalOrderSide,
)

RUN_ID = "SYNTHETIC:RUN:PNL-INTEGRATION"
CANDIDATE_ID = "S2-CANDIDATE-A"
GROUP_ID = f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{CANDIDATE_ID}"
INSTRUMENT_ID = "SYNTHETIC_CONTRACT:PNL-INTEGRATION-PUT"
STAMP = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
IDENTITY = OptionInstrumentIdentity(
    INSTRUMENT_ID,
    INSTRUMENT_ID,
    "20261210",
    "PUT",
    Decimal("500"),
    Decimal("10"),
    "SYNTHETIC:DERIVED_SCENARIO",
)
EVENTS = (
    ("EXEC-BUY-1", "BUY", 1, "10", "0.1"),
    ("EXEC-BUY-2", "BUY", 1, "12", "0.2"),
    ("EXEC-SELL-1", "SELL", 1, "14", "0.3"),
)


def _integrated_candidate():
    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=25_000_000,
        validation_run_id=RUN_ID,
        validation_candidate_id=CANDIDATE_ID,
    )
    lots = VirtualPositionLotStore()
    fees = VirtualTrack9FeeLedger()
    executions = []
    expected_fees = []

    for index, (execution_id, side, quantity, price, fee) in enumerate(EVENTS):
        executed_at = STAMP + timedelta(minutes=index + 1)
        side_enum = CanonicalOrderSide(side)
        report = CanonicalExecutionReport(
            exec_id=execution_id,
            client_order_id=f"CLIENT-{execution_id}",
            track_id="S2",
            asset_type=CanonicalAssetType.OPTION,
            side=side_enum,
            executed_qty=quantity,
            executed_price=float(price),
            fee=float(fee),
            slippage=0.0,
            timestamp=executed_at.isoformat(),
            symbol=INSTRUMENT_ID,
            option_type=CanonicalOptionType.PUT,
            strike=500.0,
            expiry="20261210",
            strategy_id="track2_asymmetric_trap",
            group_id=GROUP_ID,
            leg_id="put",
            instrument_id=INSTRUMENT_ID,
            contract_multiplier=10.0,
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        )
        runtime.account.apply_execution(report)
        lot = PositionLotProvenance(
            run_id=RUN_ID,
            instrument_id=INSTRUMENT_ID,
            strategy_id="track2_asymmetric_trap",
            group_id=GROUP_ID,
            leg_id="put",
            client_order_id=report.client_order_id,
            execution_id=execution_id,
            side=side,
            opened_quantity=quantity,
            remaining_quantity=quantity,
            execution_timestamp=executed_at,
            instrument_identity=IDENTITY,
            contract_multiplier=Decimal("10"),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
            position_role=PositionRole.NONE,
        )
        lots.apply_execution(lot)
        fee_record = Track9FeeRecord(
            run_id=RUN_ID,
            strategy_id="track2_asymmetric_trap",
            group_id=GROUP_ID,
            leg_id="put",
            client_order_id=report.client_order_id,
            execution_id=execution_id,
            instrument_id=INSTRUMENT_ID,
            fee_amount=Decimal(fee),
            executed_quantity=quantity,
            executed_price=Decimal(price),
            executed_at=executed_at,
            source="SYNTHETIC:FEE_FIXTURE",
        )
        fees.record(fee_record)
        row = {
            "execution_id": execution_id,
            "instrument_id": INSTRUMENT_ID,
            "side": side,
            "quantity": quantity,
            "price": Decimal(price),
            "contract_multiplier": Decimal("10"),
            "executed_at": executed_at,
            "fee": Decimal(fee),
        }
        executions.append(row)
        expected_fees.append({
            "execution_id": execution_id,
            "fee_amount": Decimal(fee),
            "quantity": quantity,
            "price": Decimal(price),
        })

    runtime.account.update_tick_price(13.0, INSTRUMENT_ID)
    result = ValidationOnlyRuntimeLedgerComparator().compare(
        opening_lots=(),
        executions=executions,
        expected_fee_records=expected_fees,
        actual_position_lot_history=lots.history(),
        actual_open_position_lots=lots.open_lots(),
        actual_close_events=lots.close_events(),
        actual_fee_records=fees.snapshot(run_id=RUN_ID),
        vssf_positions=runtime.account.positions,
        vssf_realized_pnl_delta=runtime.account.realized_pnl,
        vssf_unrealized_pnl=runtime.account.unrealized_pnl,
        mark_prices={INSTRUMENT_ID: Decimal("13")},
        source_namespace="SYNTHETIC:PNL_INTEGRATION",
        deterministic_rule_id="CANDIDATE-PNL-REPLAY-v1",
        source_manifest_sha256="a" * 64,
        source_anchor_refs=("No.1534", "No.1655"),
        source_anchor_as_of=STAMP,
        scenario_timestamp=STAMP + timedelta(minutes=4),
        evidence_refs=("TEST:CANDIDATE-PNL-INTEGRATION",),
    )
    return runtime, lots, fees, result


def test_candidate_account_position_lots_fee_ledger_and_pnl_reconcile_end_to_end():
    runtime, lots, fees, result = _integrated_candidate()
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert result.issues == ()
    assert runtime.account.realized_pnl == Decimal("30.0")
    assert runtime.account.unrealized_pnl == Decimal("20.0")
    assert runtime.account.balance == Decimal("24999999.4")
    assert [(row.source_lot_execution_id, row.quantity) for row in lots.close_events()] == [
        ("EXEC-BUY-1", 1),
    ]
    assert len(lots.history()) == 2
    assert len(lots.open_lots()) == 1
    assert fees.total(run_id=RUN_ID) == Decimal("0.6")
    assert result.manifest["expected_vssf_average_cost_realized_pnl"] == "30"
    assert result.manifest["fifo_realized_pnl"] == "40"


def test_candidate_pnl_and_ledger_replay_manifest_are_deterministic_after_recreation():
    _runtime_a, _lots_a, _fees_a, first = _integrated_candidate()
    _runtime_b, _lots_b, _fees_b, replay = _integrated_candidate()
    assert first.status == replay.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert first.manifest == replay.manifest
    assert first.manifest_sha256 == replay.manifest_sha256


def test_other_candidate_account_and_ledgers_remain_independent():
    _runtime_a, _lots_a, _fees_a, _result_a = _integrated_candidate()
    other = VirtualSecuritiesFirmRuntime(
        initial_capital=25_000_000,
        validation_run_id=RUN_ID,
        validation_candidate_id="S2-CANDIDATE-B",
    )
    other_lots = VirtualPositionLotStore()
    other_fees = VirtualTrack9FeeLedger()
    assert other.account.realized_pnl == Decimal("0")
    assert other.account.unrealized_pnl == Decimal("0")
    assert other.account.positions == {}
    assert other_lots.history() == ()
    assert other_fees.snapshot(run_id=RUN_ID) == ()
