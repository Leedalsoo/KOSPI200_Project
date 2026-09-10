from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from contracts.types import BrokerOrderCommand


class KisOrderPayloadError(ValueError):
    """Raised when a KIS domestic futures/options order payload is unsafe."""


@dataclass(frozen=True)
class KisOrderAccountContext:
    cano: str
    acnt_prdt_cd: str


@dataclass(frozen=True)
class KisDomesticFuturesOrderPayloadAdapter:
    """Serialize a validated BrokerOrderCommand into the KIS order body.

    This adapter performs only environment-specific serialization. It does not
    invent an instrument code, infer an order type, or perform network I/O.
    """

    account: KisOrderAccountContext
    is_vts: bool = False

    def to_payload(self, command: BrokerOrderCommand) -> dict[str, str]:
        if command.asset_type != "FUTURES":
            pass
            raise KisOrderPayloadError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.broker_symbol:
            pass
            raise KisOrderPayloadError("SHTN_PDNO_REQUIRED")
        if not re.fullmatch(r"[A-Za-z0-9]{8}", command.broker_symbol):
            pass
            raise KisOrderPayloadError("SHTN_PDNO_MUST_BE_8_ALPHANUMERIC")
        if command.broker_symbol[0] != "1":
            pass
            raise KisOrderPayloadError("FUTURES_SHTN_PDNO_PRODUCT_PREFIX_REQUIRED")
        if command.quantity <= 0:
            pass
            raise KisOrderPayloadError("ORD_QTY_REQUIRED")
        if command.requested_price is None or command.requested_price <= 0:
            pass
            raise KisOrderPayloadError("UNIT_PRICE_REQUIRED")
        if command.order_type != "LIMIT":
            pass
            # Current Standard contract does not define a safe market-order mapping.
            raise KisOrderPayloadError("UNSUPPORTED_ORDER_TYPE")

        side = str(command.side).upper()
        if side not in {"BUY", "SELL"}:
            pass
            raise KisOrderPayloadError("SIDE_REQUIRED")

        return {
            "CANO": self.account.cano,
            "ACNT_PRDT_CD": self.account.acnt_prdt_cd,
            "SHTN_PDNO": command.broker_symbol,
            "ORD_PRCS_DVSN_CD": "02",
            "SLL_BUY_DVSN_CD": "02" if side == "BUY" else "01",
            "ORD_DVSN_CD": "00",
            "UNIT_PRICE": f"{Decimal(command.requested_price):.2f}",
            "ORD_QTY": str(command.quantity),
            "NMPR_TYPE_CD": "01",
            "KRX_NMPR_CNDT_CD": "0",
        }

    def tr_id(self) -> str:
        return "VTTO1101U" if self.is_vts else "TTTO1101U"
