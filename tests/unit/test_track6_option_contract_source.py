from decimal import Decimal
from types import SimpleNamespace
import pytest

from application.composition.track6_option_contract_source import (
    Track6OptionContractSource,
    Track6OptionContractSelection,
)


def master(*strikes):
    return SimpleNamespace(
        list_contract_identities=lambda expiry: tuple(
            SimpleNamespace(
                shrn_iscd=f"OPT-{t[0]}-{s}",
                expiry="2026-09-10",
                option_type=t,
                strike=Decimal(str(s)),
                contract_multiplier=Decimal("250000"),
            )
            for s in strikes for t in ("CALL", "PUT")
        )
    )


def test_selects_actual_listed_atm_and_exact_offset_contracts():
    selection = Track6OptionContractSource(master(337.5, 350, 362.5)).select(
        expiry="202609", current_price=Decimal("351")
    )
    assert isinstance(selection, Track6OptionContractSelection)
    assert selection.atm_strike == Decimal("350")
    assert selection.put.strike == Decimal("337.5")
    assert selection.call.strike == Decimal("362.5")
    assert selection.put.contract_multiplier == Decimal("250000")
    assert selection.call.contract_multiplier == Decimal("250000")


def test_fails_closed_when_target_offset_is_not_listed():
    with pytest.raises(ValueError, match="TRACK6_LISTED_STRIKE_NOT_FOUND"):
        Track6OptionContractSource(master(350, 360, 362.5)).select(
            expiry="202609", current_price=351
        )


def test_fails_closed_on_multiplier_missing():
    bad = SimpleNamespace(
        shrn_iscd="OPT-P-3375", expiry="2026-09-10", option_type="PUT",
        strike=Decimal("337.5"), contract_multiplier=None,
    )
    good = SimpleNamespace(
        shrn_iscd="OPT-C-3625", expiry="2026-09-10", option_type="CALL",
        strike=Decimal("362.5"), contract_multiplier=Decimal("250000"),
    )
    atm_c = SimpleNamespace(shrn_iscd="ATM-C", expiry="2026-09-10", option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"))
    atm_p = SimpleNamespace(shrn_iscd="ATM-P", expiry="2026-09-10", option_type="PUT", strike=Decimal("350"), contract_multiplier=Decimal("250000"))
    source = Track6OptionContractSource(SimpleNamespace(list_contract_identities=lambda expiry: (atm_c, atm_p, bad, good)))
    with pytest.raises(ValueError, match="TRACK6_CONTRACT_MULTIPLIER_REQUIRED"):
        source.select(expiry="202609", current_price=351)

