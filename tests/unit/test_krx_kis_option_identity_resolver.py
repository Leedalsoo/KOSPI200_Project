from decimal import Decimal

from core.option.option_master import KisOptionContractIdentity
from infrastructure.kis.krx_kis_option_identity_resolver import (
    KRXKISOptionIdentityResolver,
    parse_kis_index_option_master,
)


def test_parse_fixed_width_kis_master_record():
    line = "5B01610A41KR4B016AA412C 202610 1,097.5                        201097.50 2001     KOSPI200                                "
    master = parse_kis_index_option_master(line)
    assert master["B01610A41"].stnd_iscd == "KR4B016AA412"
    assert master["B01610A41"].option_type == "CALL"


def test_resolver_matches_krx_and_kis_by_authoritative_standard_code():
    krx = KisOptionContractIdentity(
        "B016AA41", "KR4B016AA412", "2026-10-08", "CALL", Decimal("1097.5"),
        "KRX_MARKETPLACE", Decimal("250000"),
    )
    kis = KisOptionContractIdentity(
        "B01610A41", "KR4B016AA412", "202610", "CALL", Decimal("1097.5"),
        "KIS_INDEX_OPTION_MASTER", Decimal("250000"),
    )
    resolver = KRXKISOptionIdentityResolver({kis.shrn_iscd: kis})
    resolved = resolver.get_contract_identity(krx.shrn_iscd, krx)
    assert resolved is not None
    assert resolved.instrument_id == "B016AA41"
    assert resolved.symbol == "B01610A41"
    assert resolved.expiry == "2026-10-08"


def test_resolver_rejects_missing_standard_code_match():
    krx = KisOptionContractIdentity("B016AA41", "KR4B016AA412", "2026-10-08", "CALL", Decimal("1097.5"), "KRX_MARKETPLACE", Decimal("250000"))
    resolver = KRXKISOptionIdentityResolver({})
    assert resolver.get_contract_identity(krx.shrn_iscd, krx) is None
