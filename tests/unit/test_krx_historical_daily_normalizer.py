from decimal import Decimal

import pytest

from contracts.historical_market_ohlc import HistoricalDailyOHLC
from contracts.futures_contract_master import KisFuturesContractIdentity
from core.option.option_master import KisOptionContractIdentity
from infrastructure.kis.krx_historical_daily_normalizer import (
    KRXDailyHistoricalNormalizer,
    KRXDailyNormalizationError,
)
from infrastructure.kis.krx_kis_master_identity_resolver import KRXKISMasterIdentityResolver


class OptionMaster:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, shrn_iscd):
        return self.identity if shrn_iscd == self.identity.shrn_iscd else None


class FuturesMaster:
    def __init__(self, identities):
        self.identities = {item.shrn_iscd: item for item in identities}

    def get_contract_identity(self, shrn_iscd):
        return self.identities.get(shrn_iscd)


def option_master():
    return OptionMaster(KisOptionContractIdentity(
        shrn_iscd="A123456", stnd_iscd="STD", expiry="2026-10-15",
        option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"),
    ))


def futures_master():
    return FuturesMaster([KisFuturesContractIdentity(
        shrn_iscd="A016C000", stnd_iscd="STD", info_type="1",
        mmsc_cls_code="1", unas_shrn_iscd="2001", unas_kor_name="KOSPI200",
        kor_name="KOSPI200", contract_multiplier=Decimal("250000"),
        identity_source="KIS_FUTURES_MASTER+KRX", product_type=None,
    )])


def test_normalizes_actual_krx_option_daily_row_to_canonical_ohlc():
    normalizer = KRXDailyHistoricalNormalizer(option_master=option_master(), futures_master=futures_master())
    row = {"BAS_DD": "20260918", "ISU_CD": "A123456", "TDD_CLSPRC": "2.50", "TDD_OPNPRC": "2.00", "TDD_HGPRC": "3.00", "TDD_LWPRC": "1.50"}
    result = normalizer.normalize_option_row(row)
    assert isinstance(result, HistoricalDailyOHLC)
    assert result.symbol == "A123456"
    assert result.trading_date.isoformat() == "2026-09-18"
    assert result.open == Decimal("2.00")
    assert result.high == Decimal("3.00")
    assert result.low == Decimal("1.50")
    assert result.close == Decimal("2.50")
    assert result.source == "KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD=A123456"


def test_normalizes_krx_code_through_kis_master_resolver_to_kis_identity():
    kis_identity = KisOptionContractIdentity(
        shrn_iscd="B05610752", stnd_iscd="KR4B056A7520", expiry="2026-10-15",
        option_type="CALL", strike=Decimal("752.5"), contract_multiplier=Decimal("250000"),
    )
    resolver = KRXKISMasterIdentityResolver(OptionMaster(kis_identity))
    normalizer = KRXDailyHistoricalNormalizer(option_master=resolver, futures_master=futures_master())
    row = {"BAS_DD": "20260918", "ISU_CD": "B056A752", "TDD_CLSPRC": "5.0", "TDD_OPNPRC": "4.0", "TDD_HGPRC": "6.0", "TDD_LWPRC": "3.0"}
    result = normalizer.normalize_option_row(row)
    assert result.symbol == "B05610752"
    assert "KRX_ISU_CD=B056A752" in result.source


def test_normalizes_actual_krx_futures_daily_row_to_canonical_ohlc():
    normalizer = KRXDailyHistoricalNormalizer(option_master=option_master(), futures_master=futures_master())
    row = {"BAS_DD": "20260918", "ISU_CD": "A016C000", "TDD_CLSPRC": "1094.55", "TDD_OPNPRC": "1067.55", "TDD_HGPRC": "1099.50", "TDD_LWPRC": "1065.35"}
    result = normalizer.normalize_futures_row(row)
    assert result.symbol == "A016C000"
    assert result.close == Decimal("1094.55")
    assert result.source == "KRX_OPEN_API:fut_bydd_trd;KRX_ISU_CD=A016C000"


def test_missing_option_identity_fails_closed():
    normalizer = KRXDailyHistoricalNormalizer(option_master=option_master(), futures_master=futures_master())
    row = {"BAS_DD": "20260918", "ISU_CD": "UNKNOWN", "TDD_CLSPRC": "1", "TDD_OPNPRC": "1", "TDD_HGPRC": "1", "TDD_LWPRC": "1"}
    with pytest.raises(KRXDailyNormalizationError, match="OPTION_IDENTITY_REQUIRED"):
        normalizer.normalize_option_row(row)


def test_incomplete_ohlc_fails_closed():
    normalizer = KRXDailyHistoricalNormalizer(option_master=option_master(), futures_master=futures_master())
    row = {"BAS_DD": "20260918", "ISU_CD": "A123456", "TDD_CLSPRC": "", "TDD_OPNPRC": "2", "TDD_HGPRC": "3", "TDD_LWPRC": "1"}
    with pytest.raises(KRXDailyNormalizationError, match="OHLC_PRICE_REQUIRED"):
        normalizer.normalize_option_row(row)


def test_wrong_date_shape_fails_closed():
    normalizer = KRXDailyHistoricalNormalizer(option_master=option_master(), futures_master=futures_master())
    row = {"BAS_DD": "2026-09-18", "ISU_CD": "A123456", "TDD_CLSPRC": "1", "TDD_OPNPRC": "1", "TDD_HGPRC": "1", "TDD_LWPRC": "1"}
    with pytest.raises(KRXDailyNormalizationError, match="INVALID_BAS_DD"):
        normalizer.normalize_option_row(row)
