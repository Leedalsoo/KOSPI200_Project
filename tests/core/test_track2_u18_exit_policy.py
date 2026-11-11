from decimal import Decimal
import pytest
from core.risk.track2_u18_exit_policy import U18ExitDecision, U18ExitPolicy, U18GroupPnlEvidence, evaluate_u18_exit

def policy(**overrides):
    values = dict(stop_loss_ratio=Decimal("-0.50"),
        trailing_activation_ratio=Decimal("0.40"), trailing_pullback_ratio=Decimal("0.25"))
    values.update(overrides)
    return U18ExitPolicy(**values)

def evidence(*, pnl="100", **overrides):
    values = dict(complete_four_legs=True, all_marks_are_bid_ask_mid=True,
        initial_net_premium_received=Decimal("1000"),
        realized_and_unrealized_fees_present=True,
        realized_and_unrealized_slippage_present=True,
        net_pnl_after_costs=Decimal(pnl), quote_freshness_verified=True)
    values.update(overrides)
    return U18GroupPnlEvidence(**values)

def run(pnl, peak=None, p=None, e=None):
    return evaluate_u18_exit(evidence=e if e is not None else evidence(pnl=pnl),
        policy=p or policy(), peak_pnl_ratio=peak)

def test_null_u18_ratios_block_by_default():
    assert run("100", p=U18ExitPolicy()).decision is U18ExitDecision.POLICY_INPUT_BLOCKED

@pytest.mark.parametrize("p", [
    policy(stop_loss_ratio=Decimal("0")), policy(stop_loss_ratio=Decimal("0.1")),
    policy(trailing_activation_ratio=Decimal("0")),
    policy(trailing_pullback_ratio=Decimal("0")),
    policy(trailing_pullback_ratio=Decimal("1.1")),
    policy(trailing_pullback_ratio=Decimal("-0.1")),
])
def test_invalid_u18_ratio_inputs_block(p):
    assert run("100", p=p).decision is U18ExitDecision.POLICY_INPUT_BLOCKED

@pytest.mark.parametrize("changes", [
    {"complete_four_legs": False}, {"all_marks_are_bid_ask_mid": False},
    {"initial_net_premium_received": None}, {"initial_net_premium_received": Decimal("0")},
    {"realized_and_unrealized_fees_present": False},
    {"realized_and_unrealized_slippage_present": False},
    {"net_pnl_after_costs": None}, {"quote_freshness_verified": False},
])
def test_incomplete_group_cost_or_freshness_evidence_blocks(changes):
    assert run("100", e=evidence(**changes)).decision is U18ExitDecision.EVIDENCE_BLOCKED

def test_stop_loss_uses_net_pnl_after_costs_over_initial_net_premium():
    result = run("-500")
    assert result.decision is U18ExitDecision.STOP_LOSS
    assert result.net_pnl_ratio == Decimal("-0.5")

def test_trailing_activation_and_pullback_boundary():
    assert run("400", peak=Decimal("0.50")).decision is U18ExitDecision.HOLD
    result = run("375", peak=Decimal("0.50"))
    assert result.decision is U18ExitDecision.TRAILING_EXIT
    assert result.pullback_ratio == Decimal("0.25")

def test_below_activation_does_not_trigger_trailing():
    assert run("300", peak=Decimal("0.39")).decision is U18ExitDecision.HOLD

def test_peak_is_monotonic_for_validation_evaluation():
    assert run("350", peak=Decimal("0.30")).peak_pnl_ratio == Decimal("0.35")

def test_no_validation_exit_result_enables_order_submission():
    for pnl in ("-500", "400", "375", "100"):
        assert run(pnl, peak=Decimal("0.50")).order_submission_enabled is False
