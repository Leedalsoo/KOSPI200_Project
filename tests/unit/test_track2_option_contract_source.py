from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from application.composition.track2_option_contract_source import Track2OptionContractSource


@dataclass(frozen=True)
class Identity:
    expiry: str
    option_type: str
    strike: Decimal
    shrn_iscd: str
    contract_multiplier: Decimal


class FakeOptionMaster:
    def __init__(self, identities):
        self.identities = tuple(identities)

    def list_contract_identities(self, expiry=None):
        if expiry is None:
            return self.identities
        return tuple(identity for identity in self.identities if identity.expiry.replace("-", "")[:6] == expiry)


def test_select_uses_authoritative_listed_atm_and_preserves_identity_pair():
    identities = (
        Identity("2026-10-08", "PUT", Decimal("1087.5"), "P10875", Decimal("250000")),
        Identity("2026-10-08", "CALL", Decimal("1087.5"), "C10875", Decimal("250000")),
        Identity("2026-10-08", "PUT", Decimal("1090.0"), "P10900", Decimal("250000")),
        Identity("2026-10-08", "CALL", Decimal("1090.0"), "C10900", Decimal("250000")),
    )
    source = Track2OptionContractSource(FakeOptionMaster(identities))

    selection = source.select(expiry="202610", current_price=Decimal("1089.39011"))

    assert selection.atm_strike == Decimal("1090.0")
    assert selection.put.shrn_iscd == "P10900"
    assert selection.call.shrn_iscd == "C10900"


def test_nearest_expiry_uses_option_master_identities():
    identities = (
        Identity("2026-11-12", "PUT", Decimal("1090"), "P10900", Decimal("250000")),
        Identity("2026-10-08", "CALL", Decimal("1090"), "C10900", Decimal("250000")),
    )
    source = Track2OptionContractSource(FakeOptionMaster(identities))

    assert source.nearest_expiry(as_of=date(2026, 9, 30)) == "202610"


def test_missing_option_master_fails_closed():
    with pytest.raises(ValueError, match="TRACK2_OPTION_MASTER_REQUIRED"):
        Track2OptionContractSource(None).nearest_expiry(as_of=date(2026, 9, 30))
