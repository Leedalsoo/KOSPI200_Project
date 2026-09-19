from dataclasses import dataclass
from typing import Optional

from contracts.futures_contract_master import FuturesProductType


class FuturesTargetConfigurationError(ValueError):
    """Raised when the futures target configuration is ambiguous or incomplete."""


@dataclass(frozen=True)
class FuturesTargetConfiguration:
    """Application-owned explicit target selector input for FUTURES composition."""

    underlying_short_code: Optional[str] = None
    underlying_name: Optional[str] = None
    product_type: FuturesProductType | None = None

    def __post_init__(self) -> None:
        short_code = (self.underlying_short_code or "").strip()
        name = (self.underlying_name or "").strip()
        if bool(short_code) == bool(name):
            raise FuturesTargetConfigurationError(
                "exactly one of underlying_short_code or underlying_name is required"
            )
        if self.product_type is None:
            raise FuturesTargetConfigurationError("futures product_type is required")

    def selector_kwargs(self) -> dict[str, object]:
        short_code = (self.underlying_short_code or "").strip()
        name = (self.underlying_name or "").strip()
        selector = {"underlying_short_code": short_code} if short_code else {"underlying_name": name}
        selector["product_type"] = self.product_type
        return selector
