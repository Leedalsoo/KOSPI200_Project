from datetime import datetime, timezone
from decimal import Decimal

from application.composition.validation_only_runtime_ledger_comparator import ValidationOnlyRuntimeLedgerComparator
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger

STAMP = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
IDENTITY = OptionInstrumentIdentity("SYNTH-OPT", "SYNTH-OPT", "20261119", "CALL",
                                    Decimal("500"), Decimal("10"), "SYNTHETIC_VALIDATION_ONLY")


def _lot(execution_id, side, qty, price, when=STAMP):
    return PositionLotProvenance(
        run_id="FRESH30", instrument_id="SYNTH-OPT", strategy_id="SYNTH-STRATEGY",
        group_id="SYNTH-GROUP", leg_id="call", client_order_id=f"CO-{execution_id}",
        execution_id=execution_id, side=side, opened_quantity=qty, remaining_quantity=qty,
        execution_timestamp=when, instrument_identity=IDENTITY, contract_multiplier=Decimal("10"),
        identity_source="SYNTHETIC_VALIDATION_ONLY", position_role=PositionRole.NONE,
    )


def _fee(execution_id, qty, price, amount):
    return Track9FeeRecord(
        run_id="FRESH30", strategy_id="SYNTH-STRATEGY", group_id="SYNTH-GROUP",
        leg_id="call", client_order_id=f"CO-{execution_id}", execution_id=execution_id,
        instrument_id="SYNTH-OPT", fee_amount=Decimal(str(amount)), executed_quantity=qty,
        executed_price=Decimal(str(price)), executed_at=STAMP, source="SYNTHETIC:FEE_FIXTURE",
    )


def _run(opening, executions, *, mark=Decimal("12"), realized=None, unrealized=None):
    store = VirtualPositionLotStore()
    for row in opening:
        store.apply_execution(row)
    ledger = VirtualTrack9FeeLedger()
    fee_rows = []
    for row in executions:
        ledger_row = _fee(row["execution_id"], row["quantity"], row["price"], row["fee"])
        ledger.record(ledger_row)
        fee_rows.append({"execution_id": row["execution_id"], "fee_amount": row["fee"],
                         "quantity": row["quantity"], "price": row["price"],
                         "run_id": "FRESH30", "client_order_id": "CO-" + row["execution_id"],
                         "instrument_id": "SYNTH-OPT", "strategy_id": "SYNTH-STRATEGY",
                         "group_id": "SYNTH-GROUP", "leg_id": "call",
                         "executed_at": STAMP, "source": "SYNTHETIC:FEE_FIXTURE"})
        store.apply_execution(_lot(row["execution_id"], row["side"], row["quantity"],
                                   row["price"], row["executed_at"]))

    # Exercise the existing VSSF weighted-average position/PnL implementation.
    from environments.virtual.authoritative_vssf.position_manager import PositionManager
    from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
    manager = PositionManager()
    pnl_engine = PnLEngine()
    for row in opening:
        price = Decimal("11") if row.execution_id == "OPEN-2" else Decimal("10")
        manager.update_position(row.instrument_id, row.side, row.opened_quantity, float(price),
                                contract_multiplier=Decimal("10"))
    for row in executions:
        realized_piece = manager.update_position(
            row["instrument_id"], row["side"], row["quantity"], float(row["price"]),
            contract_multiplier=Decimal(row["contract_multiplier"]),
        )
        pnl_engine.add_realized(realized_piece)
    manager.update_market_price("SYNTH-OPT", float(mark))
    unrealized_calc = pnl_engine.calculate_unrealized(manager.positions, mark)
    positions = manager.positions
    realized_calc = pnl_engine.realized_pnl

    result = ValidationOnlyRuntimeLedgerComparator().compare(
        opening_lots=[{"instrument_id": x.instrument_id, "execution_id": x.execution_id,
                       "side": x.side, "quantity": x.opened_quantity, "unit_price": ("11" if x.execution_id == "OPEN-2" else "10"),
                       "contract_multiplier": "10", "executed_at": x.execution_timestamp}
                      for x in opening],
        executions=executions, expected_fee_records=fee_rows,
        actual_position_lot_history=store.history(), actual_open_position_lots=store.open_lots(),
        actual_close_events=store.close_events(), actual_fee_records=ledger.snapshot(run_id="FRESH30"),
        vssf_positions=positions, vssf_realized_pnl_delta=realized_calc if realized is None else realized,
        vssf_unrealized_pnl=unrealized_calc if unrealized is None else unrealized,
        mark_prices={"SYNTH-OPT": mark}, source_namespace="SYNTHETIC:FRESH30",
        deterministic_rule_id="FIFO-VSSF-CROSSCHECK-v1", source_manifest_sha256="a" * 64,
        source_anchor_refs=("SYNTHETIC:ANCHOR",), source_anchor_as_of=STAMP,
        scenario_timestamp=STAMP, evidence_refs=("TEST:FRESH30",),
    )
    return result, store, ledger


def test_partial_close_matches_position_lot_fifo_close_and_fee_ledger():
    opening = [_lot("OPEN-1", "BUY", 3, 10)]
    executions = [{"execution_id": "CLOSE-1", "instrument_id": "SYNTH-OPT", "side": "SELL",
                   "quantity": 1, "price": "12", "contract_multiplier": "10",
                   "executed_at": STAMP, "fee": "0.5"}]
    result, store, ledger = _run(opening, executions)
    print(result.issues, result.manifest)
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert store.close_events()[0].quantity == 1
    assert ledger.total(run_id="FRESH30") == Decimal("0.5")


def test_multi_lot_close_matches_fifo_while_vssf_average_cost_is_separately_reconciled():
    opening = [_lot("OPEN-1", "BUY", 1, 10), _lot("OPEN-2", "BUY", 2, 11)]
    executions = [{"execution_id": "CLOSE-1", "instrument_id": "SYNTH-OPT", "side": "SELL",
                   "quantity": 2, "price": "12", "contract_multiplier": "10",
                   "executed_at": STAMP, "fee": "0.4"}]
    result, store, _ = _run(opening, executions)
    print(result.issues, result.manifest)
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert [(x.source_lot_execution_id, x.quantity) for x in store.close_events()] == [
        ("OPEN-1", 1), ("OPEN-2", 1)
    ]
    assert Decimal(result.manifest["fifo_vs_vssf_realized_method_delta"]) != 0


def test_position_flip_reconciles_close_then_new_opposite_lot():
    opening = [_lot("OPEN-1", "BUY", 1, 10)]
    executions = [{"execution_id": "FLIP-1", "instrument_id": "SYNTH-OPT", "side": "SELL",
                   "quantity": 2, "price": "12", "contract_multiplier": "10",
                   "executed_at": STAMP, "fee": "0.2"}]
    result, store, _ = _run(opening, executions, mark=Decimal("11"))
    print(result.issues, result.manifest)
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert len(store.history()) == 2
    assert store.open_lots()[0].side == "SELL"
    assert store.open_lots()[0].remaining_quantity == 1


def test_cancel_without_fill_then_late_fill_is_reconciled_without_duplicate_replay():
    opening = [_lot("OPEN-1", "BUY", 1, 10)]
    executions = [{"execution_id": "LATE-FILL-1", "instrument_id": "SYNTH-OPT", "side": "SELL",
                   "quantity": 1, "price": "12", "contract_multiplier": "10",
                   "executed_at": STAMP, "fee": "0.3"}]
    result, store, ledger = _run(opening, executions)
    store.apply_execution(_lot("LATE-FILL-1", "SELL", 1, 12))
    ledger.record(_fee("LATE-FILL-1", 1, 12, "0.3"))
    print(result.issues, result.manifest)
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert len(store.close_events()) == 1
    assert len(ledger.snapshot(run_id="FRESH30")) == 1


def test_conflicting_fee_execution_replay_is_not_silently_accepted():
    ledger = VirtualTrack9FeeLedger()
    ledger.record(_fee("DUP-1", 1, 10, "0.1"))
    try:
        ledger.record(_fee("DUP-1", 1, 10, "0.2"))
    except ValueError as exc:
        assert "DUPLICATE_CONFLICT" in str(exc)
    else:
        raise AssertionError("conflicting fee replay must be rejected")


def test_vssf_pnl_difference_requires_reconciliation_not_false_pass():
    opening = [_lot("OPEN-1", "BUY", 2, 10)]
    executions = [{"execution_id": "CLOSE-1", "instrument_id": "SYNTH-OPT", "side": "SELL",
                   "quantity": 1, "price": "12", "contract_multiplier": "10",
                   "executed_at": STAMP, "fee": "0.5"}]
    result, _, _ = _run(opening, executions, realized=Decimal("19"))
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "RUNTIME_LEDGER_VSSF_REALIZED_PNL_DIVERGENCE" in result.issues


















def test_cancelled_order_without_fill_keeps_open_lot_and_has_no_fee_or_close_event():
    opening = [_lot("OPEN-1", "BUY", 1, 10)]
    result, store, ledger = _run(opening, [])
    assert result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert len(store.open_lots()) == 1
    assert store.close_events() == ()
    assert ledger.total(run_id="FRESH30") == Decimal("0")


def _compare_single_open_lot(*, duplicate_history=False, duplicate_open=False):
    lot = _lot("OPEN-DUPLICATE", "BUY", 1, 10)
    store = VirtualPositionLotStore()
    store.apply_execution(lot)
    history = store.history()
    open_lots = store.open_lots()
    if duplicate_history:
        history = history + history
    if duplicate_open:
        open_lots = open_lots + open_lots
    return ValidationOnlyRuntimeLedgerComparator().compare(
        opening_lots=[{
            "instrument_id": "SYNTH-OPT", "execution_id": "OPEN-DUPLICATE",
            "side": "BUY", "quantity": 1, "unit_price": "10",
            "contract_multiplier": "10", "executed_at": STAMP,
        }],
        executions=[], expected_fee_records=[],
        actual_position_lot_history=history, actual_open_position_lots=open_lots,
        actual_close_events=(), actual_fee_records=(),
        vssf_positions={"SYNTH-OPT": {"side": "BUY", "qty": 1, "avg_price": Decimal("10")}},
        vssf_realized_pnl_delta=Decimal("0"), vssf_unrealized_pnl=Decimal("20"),
        mark_prices={"SYNTH-OPT": Decimal("12")},
        source_namespace="SYNTHETIC:POSITION-LOT-DUPLICATE",
        deterministic_rule_id="POSITION-LOT-DUPLICATE-IDENTITY-v1",
        source_manifest_sha256="b" * 64, source_anchor_refs=("SYNTHETIC:OPEN-ANCHOR",),
        source_anchor_as_of=STAMP, scenario_timestamp=STAMP,
        evidence_refs=("TEST:POSITION-LOT-DUPLICATE",),
    )


def test_duplicate_position_lot_history_execution_id_is_not_silently_collapsed():
    result = _compare_single_open_lot(duplicate_history=True)

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "RUNTIME_LEDGER_DUPLICATE_POSITION_LOT_HISTORY_EXECUTION_ID:OPEN-DUPLICATE" in result.issues


def test_duplicate_open_position_lot_key_is_not_silently_collapsed():
    result = _compare_single_open_lot(duplicate_open=True)

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "RUNTIME_LEDGER_DUPLICATE_OPEN_POSITION_LOT_KEY:SYNTH-OPT:OPEN-DUPLICATE" in result.issues
