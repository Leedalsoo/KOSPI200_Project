from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.futures_identity_source import KisFuturesIdentitySource


def test_futures_identity_refuses_krx_derived_runtime_specification():
    contract = SimpleNamespace(
        shrn_iscd="101S9000",
        product_type="STANDARD",
        contract_multiplier=Decimal("250000"),
        identity_source="KIS_FUTURES_MASTER+KRX_FUTURES_SPEC",
    )

    with pytest.raises(ValueError, match="FUTURES_IDENTITY_KRX_RUNTIME_SOURCE_FORBIDDEN"):
        KisFuturesIdentitySource._to_identity(contract)
