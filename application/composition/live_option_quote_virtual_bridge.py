from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from core.option.option_master import IOptionContractMaster


class LiveOptionQuoteBridgeError(ValueError):
    """Raised when a live option quote cannot be bound to an authoritative contract."""


@dataclass(frozen=True)
class LiveOptionQuoteVirtualBridge:
    """Bind a KIS option observation to Option Master and Virtual quote storage."""

    option_master: IOptionContractMaster
    virtual_market: Any
    contract_multiplier: Decimal

    def publish(self, observation: KisIndexOptionMarketObservation) -> tuple[str, str, Decimal, str]:
        identity = self.option_master.get_contract_identity(observation.shrn_iscd)
        if identity is None:
            raise LiveOptionQuoteBridgeError(
                "LIVE_OPTION_MASTER_IDENTITY_NOT_FOUND"
            )
        if identity.option_type not in {"CALL", "PUT"} or identity.strike is None:
            raise LiveOptionQuoteBridgeError(
                "LIVE_OPTION_MASTER_OPTION_IDENTITY_INCOMPLETE"
            )
        if self.contract_multiplier <= 0:
            raise LiveOptionQuoteBridgeError(
                "OPTION_CONTRACT_MULTIPLIER_REQUIRED"
            )
        if observation.bid_price is None or observation.ask_price is None:
            raise LiveOptionQuoteBridgeError("LIVE_OPTION_BID_ASK_REQUIRED")
        if observation.bid_price <= 0 or observation.ask_price <= 0:
            raise LiveOptionQuoteBridgeError("LIVE_OPTION_BID_ASK_INVALID")
        if observation.last_price is not None and observation.last_price <= 0:
            raise LiveOptionQuoteBridgeError("LIVE_OPTION_LAST_INVALID")

        expiry_key = identity.expiry.replace("-", "")[:6]
        key = (identity.option_type, float(identity.strike), expiry_key)
        quote = {
            "bid": observation.bid_price,
            "ask": observation.ask_price,
            "last": observation.last_price,
            "contract_multiplier": self.contract_multiplier,
            "timestamp": observation.observed_hour,
            "source": observation.source,
            "shrn_iscd": identity.shrn_iscd,
            "stnd_iscd": identity.stnd_iscd,
        }
        self.virtual_market.publish_authoritative_option_quote(key, quote)
        return key
