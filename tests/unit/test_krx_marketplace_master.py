from decimal import Decimal

from contracts.futures_contract_spec import FuturesProductType
from infrastructure.krx.krx_marketplace_master import (
    load_futures_master,
    load_option_master,
)

ROOT = "C:/Users/white/Desktop/MovingProject/KOSPI200_Project"


def test_loads_krx_kospi200_option_excel_as_authoritative_identity():
    master = load_option_master([f"{ROOT}/data_2801_20260919.xlsx"])
    identity = master.get_contract_identity("B016A752")
    assert identity is not None
    assert identity.shrn_iscd == "B016A752"
    assert identity.stnd_iscd == "KR4B016A7520"
    assert identity.expiry == "2026-10-08"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("752.5")
    assert identity.contract_multiplier == Decimal("250000.0")


def test_loads_mini_kospi200_futures_excel():
    master = load_futures_master([f"{ROOT}/data_2836_20260919.xlsx"], FuturesProductType.MINI)
    identity = master.get_contract_identity("A056A000")
    assert identity is not None
    assert identity.shrn_iscd == "A056A000"
    assert identity.stnd_iscd == "KR4A056A0007"
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == Decimal("50000.0")
    assert identity.identity_source.startswith("KRX_MARKETPLACE:data_2836_20260919.xlsx")


class DirectMaster:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, code):
        return self.identity if code == self.identity.shrn_iscd else None


def test_weekly_option_files_are_separate_identity_sources():
    thursday = load_option_master([f"{ROOT}/data_2923_20260919.xlsx"])
    monday = load_option_master([f"{ROOT}/data_2935_20260919.xlsx"])
    assert len(thursday.identities) == 196
    assert len(monday.identities) == 232
    assert thursday.get_contract_identity("B09FE937").expiry == "2026-09-23"
    assert monday.get_contract_identity("BAFBY922").expiry == "2026-09-21"


def test_merge_preserves_standard_and_mini_futures_identity_types():
    standard = load_futures_master([f"{ROOT}/data_0900_20260919.xlsx"], FuturesProductType.STANDARD)
    mini = load_futures_master([f"{ROOT}/data_2836_20260919.xlsx"], FuturesProductType.MINI)
    from infrastructure.krx.krx_marketplace_master import merge_futures_masters
    merged = merge_futures_masters(standard, mini)
    assert merged.get_contract_identity("A016C000").product_type is FuturesProductType.STANDARD
    assert merged.get_contract_identity("A056A000").product_type is FuturesProductType.MINI
