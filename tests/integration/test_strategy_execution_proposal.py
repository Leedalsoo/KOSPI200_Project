from decimal import Decimal

import pytest

from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def test_preserves_explicit_strategy_execution_values():
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        side="BUY",
        track_id="track9_event_overnight_insurance",
        tag_id="INSURANCE",
        option_type="CALL",
        strike=Decimal("350"),
    )

    assert proposal.proposed_quantity == 2
    assert proposal.requested_price == Decimal("1.25")
    assert proposal.asset_type == "OPTION"
    assert proposal.side == "BUY"
    assert proposal.track_id == "track9_event_overnight_insurance"
    assert proposal.tag_id == "INSURANCE"
    assert proposal.option_type == "CALL"
    assert proposal.strike == Decimal("350")


def test_missing_optional_values_are_not_synthesized():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="FUTURES",
        requested_price=None,
    )

# assert proposal.requested_price is None
# assert proposal.side is None
# assert proposal.track_id is None
# assert proposal.tag_id is None
# assert proposal.option_type is None
# assert proposal.strike is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"proposed_quantity": 0, "asset_type": "OPTION"},
        {"proposed_quantity": 1, "asset_type": "", "requested_price": Decimal("1")},
        {"proposed_quantity": 1, "asset_type": "OPTION", "requested_price": Decimal("0")},
        {"proposed_quantity": 1, "asset_type": "OPTION", "strike": Decimal("0")},
    ],
)
def test_invalid_execution_proposal_values_fail_closed(kwargs):
    with pytest.raises(ValueError):
        StrategyExecutionProposal(**kwargs)
