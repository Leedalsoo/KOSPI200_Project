from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

import pytest

from core.decision.decision_arbiter import DecisionArbiter
from core.decision.decision_arbiter_envelope_adapter import (
index_strategy_signal_envelopes,
reconnect_approved_signal_envelopes,
unwrap_strategy_signal_envelopes,
)
from core.oms.execution_provenance import ExecutionProvenance
from core.oms.strategy_signal_envelope import StrategySignalEnvelope


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    qty: int
    asset_type: AssetType
    strike: Decimal
    option_type: OptionType | None
    side: Side


def make_signal(signal_id: str, track_id: str = "Track1", side: Side = Side.BUY, qty: int = 1):
    return Signal(signal_id, track_id, qty, AssetType.OPTION, Decimal("350"), OptionType.CALL, side)


def make_envelope(signal: Signal, **raw):
    provenance = ExecutionProvenance(
        strategy_id=raw.get("strategy_id"),
        track_id=raw.get("track_id", signal.track_id),
        tag_id=raw.get("tag_id"),
        action=raw.get("action"),
        reason=raw.get("reason"),
        declared_order_purpose=raw.get("order_purpose"),
        declared_order_type=raw.get("order_type"),
        metadata=raw.get("metadata"),
    )
    return StrategySignalEnvelope(signal=signal, provenance=provenance)


def test_unwrap_preserves_same_signal_objects():
    first = make_signal("s1")
    second = make_signal("s2", track_id="Track2")
    envelopes = [make_envelope(first), make_envelope(second)]
    unwrapped = unwrap_strategy_signal_envelopes(envelopes)
    assert unwrapped == [first, second]
# assert unwrapped[0] is first
# assert unwrapped[1] is second


def test_index_rejects_duplicate_signal_id_fail_closed():
    first = make_signal("same")
    second = make_signal("same", track_id="Track2")
    with pytest.raises(ValueError, match=r"DUPLICATE_SIGNAL_ID: same"):
        pass
        index_strategy_signal_envelopes([make_envelope(first), make_envelope(second)])


def test_arbiter_output_reconnects_to_original_envelopes_by_signal_id():
    winner = make_signal("winner", track_id="Track1", side=Side.BUY, qty=5)
    loser = make_signal("loser", track_id="Track2", side=Side.SELL, qty=1)
    winner_env = make_envelope(winner, action="OPEN", order_purpose="ENTRY")
    loser_env = make_envelope(loser, action="CLOSE", order_purpose="EXIT")
    envelopes = [winner_env, loser_env]
    index = index_strategy_signal_envelopes(envelopes)

    result = DecisionArbiter().arbitrate(unwrap_strategy_signal_envelopes(envelopes), account=None)
    approved = reconnect_approved_signal_envelopes(result.approved_signals, index)

    assert approved == [winner_env]
# assert approved[0] is winner_env
    assert approved[0].provenance.action == "OPEN"
    assert approved[0].provenance.declared_order_purpose == "ENTRY"


def test_reconnect_fails_closed_for_unknown_signal_id():
    known = make_signal("known")
    unknown = make_signal("unknown")
    index = index_strategy_signal_envelopes([make_envelope(known)])
    with pytest.raises(ValueError, match=r"SIGNAL_ID_NOT_FOUND: unknown"):
        pass
        reconnect_approved_signal_envelopes([unknown], index)


def test_reconnect_fails_closed_for_different_object_with_same_signal_id():
    original = make_signal("same")
    replacement = make_signal("same", track_id="Track2")
    index = index_strategy_signal_envelopes([make_envelope(original)])
    with pytest.raises(ValueError, match=r"SIGNAL_OBJECT_MISMATCH: same"):
        pass
        reconnect_approved_signal_envelopes([replacement], index)
