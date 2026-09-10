from dataclasses import dataclass
from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from core.risk.risk_input import RiskAccountInput


@dataclass(frozen=True)
class Command:
    client_order_id: str = "boundary-order"
    track_id: str = "boundary-track"
    qty: int = 1
    price: Decimal = Decimal("1")
    side: str = "BUY"
    tag_id: str = ""

    def get_instrument_key(self):
        return "OPTION_BOUNDARY"


class ExactMargin:
    def __init__(self, margin):
        self.margin = Decimal(str(margin))

    def calculate_order_margin(self, command):
        return self.margin * command.qty


def account(*, total="100", realized="0", used="0", free="100"):
    return RiskAccountInput(
        Decimal(str(total)),
        Decimal(str(realized)),
        Decimal(str(used)),
        Decimal(str(free)),
    )


def test_daily_loss_threshold_distinguishes_one_decimal_ulp():
    engine = RiskEngine(RiskConfig(max_daily_loss_krw=100.0), ExactMargin("1"))
    below = engine.evaluate_order(Command(), account(realized="-99.999999999999999999"))
    at_limit = engine.evaluate_order(Command(), account(realized="-100.000000000000000000"))
    assert below.decision == "ALLOW"
    assert at_limit.decision == "DENY"


def test_free_margin_affordability_distinguishes_sub_float_epsilon():
    margin = Decimal("1.000000000000000001")
    engine = RiskEngine(margin_engine=ExactMargin(margin))
    result = engine.evaluate_order(Command(), account(free="1.000000000000000000"))
    assert result.decision == "DENY"
    assert result.required_margin == margin


def test_margin_ratio_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(max_margin_utilization_ratio=0.85)
    engine = RiskEngine(config, ExactMargin("0.000000000000000001"))
    result = engine.evaluate_order(
        Command(),
        account(total="1", used="0.850000000000000000"),
    )
    assert result.decision == "DENY"
# assert result.estimated_margin_ratio > Decimal("0.85")


def test_reduction_uses_exact_decimal_unit_margin():
    engine = RiskEngine(margin_engine=ExactMargin("0.500000000000000001"))
    result = engine.evaluate_order(Command(qty=3), account(free="1.000000000000000002"), allow_reduction=True)
    assert result.decision == "REDUCE"
    assert result.approved_qty == 2
    assert result.required_margin == Decimal("1.000000000000000002")
