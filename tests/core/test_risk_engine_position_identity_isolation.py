from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from core.risk.risk_input import RiskAccountInput, RiskPosition, RiskPositionInput


class _MarginEngine:
    def calculate_order_margin(self, command) -> float:
        return float(command.qty)


class _Command:
    client_order_id = "SYNTHETIC-RISK-POSITION-IDENTITY-001"
    track_id = "track4_gamma_scalping"
    tag_id = "GAMMA_REBALANCE"
    symbol = "SYNTHETIC-MINI-NEW"
    side = "BUY"
    qty = 1
    price = 1000.0

    def get_instrument_key(self) -> str:
        return "SYNTHETIC-MINI-NEW"


def _engine() -> RiskEngine:
    return RiskEngine(
        RiskConfig(max_position_per_instrument=5),
        margin_engine=_MarginEngine(),
    )


def _account() -> RiskAccountInput:
    return RiskAccountInput(
        total_balance=Decimal("1000000"),
        realized_pnl=Decimal("0"),
        used_margin=Decimal("0"),
        free_margin=Decimal("1000000"),
    )


def test_unrelated_single_position_is_not_used_as_order_instrument_position():
    positions = RiskPositionInput(
        positions={"SYNTHETIC-OTHER-INSTRUMENT": RiskPosition(side="BUY", qty=5)}
    )

    expected = _engine().calculate_expected_position(_Command(), positions)

    assert expected == {
        "instrument_key": "SYNTHETIC-MINI-NEW",
        "side": "BUY",
        "qty": 1,
    }


def test_unrelated_single_position_does_not_cause_false_position_limit_rejection():
    result = _engine().evaluate_order(
        _Command(),
        _account(),
        RiskPositionInput(
            positions={"SYNTHETIC-OTHER-INSTRUMENT": RiskPosition(side="BUY", qty=5)}
        ),
    )

    assert result.is_approved is True
    assert result.approved_qty == 1
    assert result.rejection_reason is None


def test_symbol_alias_still_matches_when_instrument_id_key_is_absent():
    command = _Command()
    command.get_instrument_key = lambda: "SYNTHETIC-MINI-ID"
    positions = RiskPositionInput(
        positions={command.symbol: RiskPosition(side="BUY", qty=5)}
    )

    expected = _engine().calculate_expected_position(command, positions)

    assert expected["qty"] == 6


def test_unrelated_opposite_position_does_not_receive_pure_reduction_bypass():
    command = _Command()
    command.side = "SELL"
    result = _engine().evaluate_order(
        command,
        _account(),
        RiskPositionInput(
            positions={"SYNTHETIC-OTHER-INSTRUMENT": RiskPosition(side="BUY", qty=5)}
        ),
    )

    assert result.is_approved is True
    assert result.required_margin == Decimal("1")
