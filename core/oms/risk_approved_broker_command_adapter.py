"""Lossless Risk-effective quantity projection onto an authoritative BrokerOrderCommand."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts.types import BrokerOrderCommand

class RiskApprovedBrokerCommandError(ValueError):
    pass

def project_risk_effective_quantity(*, original: BrokerOrderCommand, effective: Any) -> BrokerOrderCommand:
    if original is None:
        raise RiskApprovedBrokerCommandError("BROKER_ORDER_COMMAND_REQUIRED")
    if effective is None:
        raise RiskApprovedBrokerCommandError("RISK_EFFECTIVE_COMMAND_REQUIRED")
    if str(original.client_order_id) != str(getattr(effective, 'client_order_id', '')):
        raise RiskApprovedBrokerCommandError("CLIENT_ORDER_ID_MISMATCH")
    original_qty = int(original.quantity)
    effective_qty = int(getattr(effective, 'qty', 0))
    if original_qty <= 0 or effective_qty <= 0:
        raise RiskApprovedBrokerCommandError("QUANTITY_REQUIRED")
    if effective_qty > original_qty:
        raise RiskApprovedBrokerCommandError("RISK_QUANTITY_INCREASE_FORBIDDEN")

    # Only Risk-authoritative quantity may change. Identity and execution semantics
    # remain exactly those supplied by the authoritative BrokerOrderCommand source.
    return replace(original, quantity=effective_qty)

__all__ = ("RiskApprovedBrokerCommandError", "project_risk_effective_quantity")
