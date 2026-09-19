from dataclasses import dataclass

from infrastructure.kis.krx_kis_master_identity_resolver import (
    KRXKISMasterIdentityResolver,
)


@dataclass(frozen=True)
class Identity:
    shrn_iscd: str
    stnd_iscd: str
    expiry: str
    option_type: str | None = None
    strike: object | None = None
    contract_multiplier: object | None = 250000


class Master:
    def __init__(self, identities):
        self.identities = identities

    def get_contract_identity(self, code):
        return self.identities.get(code)


def test_resolves_krx_code_through_kis_short_code():
    master = Master({"B05610752": Identity("B05610752", "KR4B056A7521", "2026-10-08")})
    resolver = KRXKISMasterIdentityResolver(master)
    identity = resolver.get_contract_identity("B056A752")
    assert identity.shrn_iscd == "B05610752"


def test_unmatched_krx_code_stays_unresolved():
    resolver = KRXKISMasterIdentityResolver(Master({}))
    assert resolver.get_contract_identity("A016C000") is None


def test_direct_krx_marketplace_identity_is_preferred_over_derived_kis_code():
    direct = Identity("B016A752", "KR4B016A7520", "2026-10-08", "CALL", 752.5, 250000)
    derived = Identity("B01610752", "KR4B056A7521", "2026-10-08", "CALL", 752.5, 250000)
    resolver = KRXKISMasterIdentityResolver(Master({derived.shrn_iscd: derived}), DirectMaster(direct))
    assert resolver.get_contract_identity("B016A752") is direct


class DirectMaster:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, code):
        return self.identity if code == self.identity.shrn_iscd else None
