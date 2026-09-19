from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class FuturesProductType(StrEnum):
    STANDARD = "STANDARD"
    MINI = "MINI"


@dataclass(frozen=True)
class KRXFuturesContractSpec:
    product_type: FuturesProductType
    contract_multiplier: Decimal
    source: str


class KRXFuturesContractSpecSource:
    """Authoritative KRX product specification used for futures multiplier."""

    SOURCE = "KRX_INDEX_FUTURES_CONTRACT_SPEC"
    STANDARD = KRXFuturesContractSpec(FuturesProductType.STANDARD, Decimal("250000"), SOURCE)
    MINI = KRXFuturesContractSpec(FuturesProductType.MINI, Decimal("50000"), SOURCE)

    @classmethod
    def get(cls, product_type: FuturesProductType) -> KRXFuturesContractSpec:
        if product_type is FuturesProductType.STANDARD:
            return cls.STANDARD
        if product_type is FuturesProductType.MINI:
            return cls.MINI
        raise ValueError("FUTURES_PRODUCT_SPEC_UNAVAILABLE")
