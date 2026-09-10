from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from .decision_arbiter import DecisionArbiter, STRATEGY_PRIORITY_MAP


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    qty: int
    asset_type: AssetType
    strike: Decimal
    option_type: OptionType | None
    side: Side


def signal(signal_id, track_id, qty=1, side=Side.BUY, strike=Decimal("350"), option_type=OptionType.CALL):
    return Signal(signal_id, track_id, qty, AssetType.OPTION, strike, option_type, side)


def test_empty_input_returns_empty_reference_shape():
    result = DecisionArbiter().arbitrate([], account=None)
    assert result.approved_signals == []
    assert result.rejected_signals == []
    assert result.netted_clashes == []


def test_priority_then_quantity_then_signal_id_is_reference_order():
    signals = [
        signal("z", "Track2", qty=10),
        signal("b", "Track1", qty=1),
        signal("a", "Track1", qty=5),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["a", "b", "z"]


def test_opposite_side_same_instrument_keeps_preceding_signal_and_rejects_later():
    signals = [
        signal("win", "Track1", qty=5, side=Side.BUY),
        signal("lose", "Track2", qty=1, side=Side.SELL),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["win"]
    assert [item[0].signal_id for item in result.rejected_signals] == ["lose"]
    assert result.rejected_signals[0][1] == "CLASH_NETTING_REJECTED: Subordinate to Track1 (BUY)"
    assert len(result.netted_clashes) == 1


def test_same_side_signals_are_all_approved_without_quantity_aggregation():
    signals = [
        signal("one", "Track1", qty=3, side=Side.BUY),
        signal("two", "Track2", qty=7, side=Side.BUY),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["one", "two"]
    assert [item.qty for item in result.approved_signals] == [3, 7]
    assert result.rejected_signals == []


def test_unregistered_track_uses_reference_priority_99():
    assert STRATEGY_PRIORITY_MAP["Track1"] == 2
    result = DecisionArbiter().arbitrate(
        [signal("known", "Track1"), signal("unknown", "UnknownTrack")],
        account=None,
    )
    assert [item.signal_id for item in result.approved_signals] == ["known", "unknown"]


def test_option_type_none_is_part_of_instrument_key():
    buy = signal("buy", "Track1", side=Side.BUY, option_type=None)
    sell = signal("sell", "Track2", side=Side.SELL, option_type=OptionType.CALL)
    result = DecisionArbiter().arbitrate([buy, sell], account=None)
    assert len(result.approved_signals) == 2
    assert result.rejected_signals == []
