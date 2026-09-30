from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from core.decision.decision_arbiter import DecisionArbiter, STRATEGY_PRIORITY_MAP


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
        signal("z", "track2_asymmetric_trap", qty=10),
        signal("b", "TRACK1_TAIL_DEFENSE", qty=1),
        signal("a", "TRACK1_TAIL_DEFENSE", qty=5),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["a", "b", "z"]


def test_opposite_side_same_instrument_keeps_preceding_signal_and_rejects_later():
    signals = [
        signal("win", "TRACK1_TAIL_DEFENSE", qty=5, side=Side.BUY),
        signal("lose", "track2_asymmetric_trap", qty=1, side=Side.SELL),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["win"]
    assert [item[0].signal_id for item in result.rejected_signals] == ["lose"]
    assert result.rejected_signals[0][1] == "CLASH_NETTING_REJECTED: Subordinate to TRACK1_TAIL_DEFENSE (BUY)"
    assert len(result.netted_clashes) == 1


def test_same_side_signals_are_all_approved_without_quantity_aggregation():
    signals = [
        signal("one", "TRACK1_TAIL_DEFENSE", qty=3, side=Side.BUY),
        signal("two", "track2_asymmetric_trap", qty=7, side=Side.BUY),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["one", "two"]
    assert [item.qty for item in result.approved_signals] == [3, 7]
    assert result.rejected_signals == []


def test_runtime_strategy_ids_use_authoritative_priority_map():
    expected = {
        "TRACK1_TAIL_DEFENSE": 2,
        "track6_daily_tail_insurance": 3,
        "track9_event_overnight_insurance": 3,
        "Strategy_3_StatArb": 4,
        "track4_gamma_scalping": 4,
        "track7_volatility_skew_weekly_insurance": 5,
        "track8_macro_regime_monthly_strangle": 5,
        "track2_asymmetric_trap": 6,
        "track5_gap_divergence": 6,
    }
    assert {key: STRATEGY_PRIORITY_MAP[key] for key in expected} == expected


def test_unregistered_track_uses_reference_priority_99():
    result = DecisionArbiter().arbitrate(
        [signal("known", "TRACK1_TAIL_DEFENSE"), signal("unknown", "UnknownTrack")],
        account=None,
    )
    assert [item.signal_id for item in result.approved_signals] == ["known", "unknown"]


def test_option_type_none_is_part_of_instrument_key():
    buy = signal("buy", "TRACK1_TAIL_DEFENSE", side=Side.BUY, option_type=None)
    sell = signal("sell", "track2_asymmetric_trap", side=Side.SELL, option_type=OptionType.CALL)
    result = DecisionArbiter().arbitrate([buy, sell], account=None)
    assert len(result.approved_signals) == 2
    assert result.rejected_signals == []
