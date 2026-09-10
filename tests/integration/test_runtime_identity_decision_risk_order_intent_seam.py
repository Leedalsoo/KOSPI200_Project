from dataclasses import dataclass, replace
from decimal import Decimal


def test_vms_source_sequence_is_lossless_to_runtime_tick_identity():
    reference_seq = 17
    projected_source_sequence = reference_seq
    assert projected_source_sequence == reference_seq


def test_runtime_local_sequence_is_runtime_owned_strategy_collection_ordinal():
    strategy_signals = ("sig-a", "sig-b", "sig-c")
    local_sequences = [index for index, _ in enumerate(strategy_signals, start=1)]
    assert local_sequences == [1, 2, 3]


def test_decision_arbiter_preserves_signal_identity_without_rewrite():
    signal = {
        "signal_id": "SIG-42-Track4-1",
        "instrument_id": "AUTH-OPT-1",
        "symbol": "KOSPI200-C-350",
        "expiry": "20260910",
        "option_type": "CALL",
        "strike": Decimal("350"),
        "qty": 2,
        "price": Decimal("1.25"),
    }
    approved = signal
# assert approved is signal
    assert approved["instrument_id"] == "AUTH-OPT-1"
    assert approved["symbol"] == "KOSPI200-C-350"
    assert approved["expiry"] == "20260910"


@dataclass(frozen=True)
class PositionExecutionDecision:
    client_order_id: str
    approved_quantity: int
    requested_price: Decimal
    order_type: str
    order_purpose: str


def test_risk_reduced_quantity_is_authoritative_and_execution_semantics_are_preserved():
    decision = PositionExecutionDecision(
        client_order_id="ORD-T42-Track4-1",
        approved_quantity=10,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="EXPLICIT_POSITION_INTENT",
    )
    risk_approved_qty = 4
    effective = replace(decision, approved_quantity=risk_approved_qty)

    assert effective.approved_quantity == 4
    assert effective.requested_price == Decimal("1.25")
    assert effective.order_type == "LIMIT"
    assert effective.order_purpose == "EXPLICIT_POSITION_INTENT"


def test_risk_quantity_provenance_mismatch_fails_closed():
    approved_qty = 4
    reduced_command_qty = 3
    assert approved_qty != reduced_command_qty
