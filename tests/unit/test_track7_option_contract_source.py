from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track7_option_contract_source import Track7OptionContractSource
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7ExecutionInput,
    Track7VolatilitySkewWeeklyInsurance,
)
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def identity(option_type, strike, multiplier=Decimal("250000")):
    return SimpleNamespace(
        shrn_iscd=f"OPT-{option_type[0]}-{strike}",
        expiry="2026-09-10",
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=multiplier,
    )


def master():
    return SimpleNamespace(
        find_contract_identity=lambda expiry, option_type, strike: identity(option_type, strike)
    )


def test_track7_option_source_resolves_both_legs_from_option_master():
    selection = Track7OptionContractSource(master()).select(
        expiry="202609", strike=Decimal("350")
    )
    assert selection.put.option_type == "PUT"
    assert selection.call.option_type == "CALL"
    assert selection.put.strike == Decimal("350")
    assert selection.call.strike == Decimal("350")
    assert selection.contract_multiplier == Decimal("250000")


def test_track7_option_source_fails_closed_if_one_leg_is_missing():
    def lookup(expiry, option_type, strike):
        return None if option_type == "CALL" else identity("PUT", strike)

    with pytest.raises(ValueError, match="TRACK7_CALL_CONTRACT_NOT_FOUND"):
        Track7OptionContractSource(SimpleNamespace(find_contract_identity=lookup)).select(
            expiry="202609", strike=Decimal("350")
        )


def test_track7_plan_long_put_short_call():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.state = strategy.state.__class__(
        skew_active=True,
        skew_direction="LONG_PUT_SHORT_CALL",
        put_strike=Decimal("350"),
        call_strike=Decimal("350"),
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        option_type="PUT", strike=Decimal("350"),
    )
    plan = strategy.build_execution_plan("T7-G1", proposal=proposal)
    assert [(x.option_type, x.strike, x.side) for x in plan.legs] == [
        ("PUT", Decimal("350"), "BUY"), ("CALL", Decimal("350"), "SELL")
    ]


def test_track7_plan_long_call_short_put():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.state = strategy.state.__class__(
        skew_active=True,
        skew_direction="LONG_CALL_SHORT_PUT",
        put_strike=Decimal("350"),
        call_strike=Decimal("350"),
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        option_type="CALL", strike=Decimal("350"),
    )
    plan = strategy.build_execution_plan("T7-G2", proposal=proposal)
    assert [(x.option_type, x.strike, x.side) for x in plan.legs] == [
        ("CALL", Decimal("350"), "BUY"), ("PUT", Decimal("350"), "SELL")
    ]
