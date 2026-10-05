from decimal import Decimal

from application.composition.track6_option_contract_source import Track6OptionContractSource
from core.option.option_master import (
    InMemoryOptionContractMaster,
    KisOptionContractIdentity,
    parse_kis_fo_idx_mst_result,
)


class _Calendar:
    def is_trading_day(self, day):
        return day.weekday() < 5

    def prev_trading_day(self, day):
        from datetime import timedelta
        day -= timedelta(days=1)
        while not self.is_trading_day(day):
            day -= timedelta(days=1)
        return day


def test_standard_and_mini_kospi200_option_multipliers_are_distinct():
    raw = "\n".join(
        (
            "5|B01610A49|KR4B016AA495|C 202610 1,117.5|3|01117.50| |2001|KOSPI200",
            "6|C01610A40|KR4C016AA403|P 202610 1,092.5|3|01092.50| |2001|KOSPI200",
            "D|B05610A48|KR4B056AA483|미니 C 202610 1,117.5|3|01117.50| |2001|KOSPI200",
            "E|C05610A38|KR4C056AA383|미니 P 202610 1,092.5|3|01092.50| |2001|KOSPI200",
        )
    )

    result = parse_kis_fo_idx_mst_result(raw, _Calendar())

    assert result.identities["C01610A40"].contract_multiplier == Decimal("250000")
    assert result.identities["B01610A49"].contract_multiplier == Decimal("250000")
    assert result.identities["C05610A38"].contract_multiplier == Decimal("50000")
    assert result.identities["B05610A48"].contract_multiplier == Decimal("50000")


def test_standard_and_mini_same_economic_terms_are_not_duplicate_authoritative_contracts():
    raw = "\n".join(
        (
            "6|C01610A40|KR4C016AA403|P 202610 1,092.5|3|01092.50| |2001|KOSPI200",
            "E|C05610A38|KR4C056AA383|미니 P 202610 1,092.5|3|01092.50| |2001|KOSPI200",
        )
    )

    result = parse_kis_fo_idx_mst_result(raw, _Calendar())
    identities = list(result.identities.values())
    standard = [x for x in identities if x.contract_multiplier == Decimal("250000")]
    mini = [x for x in identities if x.contract_multiplier == Decimal("50000")]

    assert len(standard) == 1
    assert len(mini) == 1
    assert standard[0].shrn_iscd == "C01610A40"
    assert mini[0].shrn_iscd == "C05610A38"


def test_track6_selects_standard_kospi200_identity_when_mini_has_same_strike():
    master = InMemoryOptionContractMaster()
    for option_type, strike, symbol, multiplier in (
        ("PUT", Decimal("1092.5"), "C01610A40", Decimal("250000")),
        ("PUT", Decimal("1092.5"), "C05610A38", Decimal("50000")),
        ("CALL", Decimal("1117.5"), "B01610A49", Decimal("250000")),
        ("CALL", Decimal("1117.5"), "B05610A48", Decimal("50000")),
        ("PUT", Decimal("1105.0"), "C01610A42", Decimal("250000")),
        ("CALL", Decimal("1105.0"), "B01610A51", Decimal("250000")),
    ):
        master.register_contract_identity(KisOptionContractIdentity(
            shrn_iscd=symbol,
            stnd_iscd=None,
            expiry="2026-10-08",
            option_type=option_type,
            strike=strike,
            contract_multiplier=multiplier,
        ))

    selection = Track6OptionContractSource(master).select(
        expiry="202610", current_price=Decimal("1105.06")
    )

    assert selection.put.shrn_iscd == "C01610A40"
    assert selection.call.shrn_iscd == "B01610A49"
    assert selection.put.contract_multiplier == Decimal("250000")
    assert selection.call.contract_multiplier == Decimal("250000")


def test_find_contract_identity_prefers_standard_option_when_mini_matches():`r`n    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="C01610A40", stnd_iscd=None, expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1092.5"), contract_multiplier=Decimal("250000"),
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="C05610A38", stnd_iscd=None, expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1092.5"), contract_multiplier=Decimal("50000"),
    ))

    identity = master.find_contract_identity(
        "202610", "PUT", Decimal("1092.5")
    )

    assert identity is not None
    assert identity.shrn_iscd == "C01610A40"
    assert identity.contract_multiplier == Decimal("250000")


def test_track6_ignores_option_identity_without_multiplier():
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="UNSET", stnd_iscd=None, expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1092.5"), contract_multiplier=None,
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="C01610A40", stnd_iscd=None, expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1092.5"), contract_multiplier=Decimal("250000"),
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="B01610A49", stnd_iscd=None, expiry="2026-10-08",
        option_type="CALL", strike=Decimal("1117.5"), contract_multiplier=Decimal("250000"),
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="C01610A42", stnd_iscd=None, expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1105"), contract_multiplier=Decimal("250000"),
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="B01610A51", stnd_iscd=None, expiry="2026-10-08",
        option_type="CALL", strike=Decimal("1105"), contract_multiplier=Decimal("250000"),
    ))

    selection = Track6OptionContractSource(master).select(
        expiry="202610", current_price=Decimal("1105.06")
    )

    assert selection.put.shrn_iscd == "C01610A40"
    assert selection.call.shrn_iscd == "B01610A49"
