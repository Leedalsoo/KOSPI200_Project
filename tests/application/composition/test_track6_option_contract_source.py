from decimal import Decimal
from types import SimpleNamespace

from application.composition.track6_option_contract_source import Track6OptionContractSource


def identity(group, option_type, strike):
    prefix = f"SYNTHETIC_CONTRACT:SYNTH-S6-{group}-20261102"
    return SimpleNamespace(
        shrn_iscd=f"{prefix}-{option_type}-{strike}",
        expiry="20261102",
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
    )


class Master:
    def __init__(self, identities):
        self.identities = tuple(identities)

    def list_contract_identities(self, expiry):
        return tuple(item for item in self.identities if item.expiry == expiry)


def test_synthetic_contract_selection_is_scoped_to_current_scenario_group():
    identities = []
    for group in (1, 2):
        identities.extend((
            identity(group, "PUT", "487.5"),
            identity(group, "PUT", "500"),
            identity(group, "CALL", "500"),
            identity(group, "CALL", "512.5"),
        ))
    source = Track6OptionContractSource(Master(identities))
    selected = source.select(
        expiry="20261102",
        current_price=Decimal("500"),
        identity_prefix="SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102",
    )
    assert selected.put.shrn_iscd.endswith("-PUT-487.5")
    assert selected.call.shrn_iscd.endswith("-CALL-512.5")
    assert "SYNTH-S6-1-" in selected.put.shrn_iscd
    assert "SYNTH-S6-1-" in selected.call.shrn_iscd


def test_synthetic_contract_selection_rejects_empty_or_invalid_scope():
    source = Track6OptionContractSource(Master(()))
    try:
        source.select(expiry="20261102", current_price=Decimal("500"), identity_prefix="SYNTHETIC_CONTRACT:SYNTH-S6-9-20261102")
    except ValueError as exc:
        assert str(exc) == "TRACK6_SYNTHETIC_IDENTITY_SCOPE_EMPTY"
    else:
        raise AssertionError("empty scenario scope must fail closed")


def test_ranked_contract_candidates_return_rank5_and_rank6_without_selecting_a_default():
    identities = [
        identity(1, "PUT", "487.5"),
        identity(1, "PUT", "485"),
        identity(1, "PUT", "500"),
        identity(1, "CALL", "500"),
        identity(1, "CALL", "512.5"),
        identity(1, "CALL", "515"),
    ]
    source = Track6OptionContractSource(Master(identities))
    candidates = source.select_ranked_candidates(
        expiry="20261102",
        current_price=Decimal("500"),
        identity_prefix="SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102",
    )
    assert [item.rank for item in candidates] == [5, 6]
    assert candidates[0].put.strike == Decimal("487.5")
    assert candidates[0].call.strike == Decimal("512.5")
    assert candidates[1].put.strike == Decimal("485")
    assert candidates[1].call.strike == Decimal("515")


def test_ranked_contract_candidates_omit_unlisted_rank_instead_of_inventing_contracts():
    identities = [
        identity(1, "PUT", "485"),
        identity(1, "PUT", "500"),
        identity(1, "CALL", "500"),
        identity(1, "CALL", "515"),
    ]
    source = Track6OptionContractSource(Master(identities))
    candidates = source.select_ranked_candidates(
        expiry="20261102",
        current_price=Decimal("500"),
        identity_prefix="SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102",
    )
    assert [item.rank for item in candidates] == [6]
