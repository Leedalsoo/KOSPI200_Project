from datetime import date
from decimal import Decimal

import pytest

from application.composition.option_expiry_source import KisOptionMasterExpirySource
from contracts.option_expiry_source import resolve_authoritative_option_expiry
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity


def test_kis_option_master_expiry_source_returns_exact_master_date() -> None:
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="201V12345", stnd_iscd="KR4V123450", expiry="2026-10-15",
        option_type="CALL", strike=Decimal("510"), contract_multiplier=Decimal("250000"),
    ))
    source = KisOptionMasterExpirySource(master)
    assert resolve_authoritative_option_expiry(source, "201V12345") == date(2026, 10, 15)


def test_missing_master_contract_fails_closed() -> None:
    source = KisOptionMasterExpirySource(InMemoryOptionContractMaster())
    with pytest.raises(ValueError, match="AUTHORITATIVE_OPTION_EXPIRY_NOT_FOUND"):
        resolve_authoritative_option_expiry(source, "MISSING")


def test_invalid_master_expiry_is_not_accepted() -> None:
    master = InMemoryOptionContractMaster({"201V12345": "202610"})
    source = KisOptionMasterExpirySource(master)
    with pytest.raises(ValueError, match="AUTHORITATIVE_OPTION_EXPIRY_INVALID"):
        source.resolve_expiry("201V12345")
