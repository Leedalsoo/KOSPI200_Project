"""Reference-compatible Decision -> RiskGate -> OrderRouter execution seam.

OrderIntent is intentionally not inserted here. This module preserves the existing
Reference execution transport while keeping Standard OrderIntent as a future seam.
"""
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand
from core.risk.risk_runtime_adapter import build_risk_runtime_inputs


class OrderRouterLike(Protocol):
    def register_and_route(self, command: Any) -> Any: ...


@dataclass(frozen=True)
class CanonicalRiskCommandAdapter:
    """Structural compatibility adapter for Standard Risk without synthetic identity."""

    client_order_id: str
    track_id: str
    asset_type: Any
    side: Any
    qty: int
    price: float
    tag_id: str
    option_type: Any = None
    strike: float = 0.0
    symbol: str = ""
    expiry: str = ""
    contract_multiplier: float | None = None
    identity_source: str = ""

    @classmethod
    def from_command(cls, command: CanonicalOrderCommand) -> "CanonicalRiskCommandAdapter":
        return cls(
            client_order_id=command.client_order_id,
            track_id=command.track_id,
            asset_type=command.asset_type,
            side=command.side,
            qty=command.qty,
            price=command.price,
            tag_id=command.tag_id,
            option_type=command.option_type,
            strike=command.strike,
            symbol=command.symbol,
            expiry=command.expiry,
            contract_multiplier=command.contract_multiplier, identity_source=command.identity_source,
        )

    def get_instrument_key(self) -> str:
        """Derive only a Risk lookup key from fields already present on command."""
        asset = getattr(self.asset_type, "value", self.asset_type)
        if str(asset) == CanonicalAssetType.OPTION.value:
            if not self.symbol or not self.expiry or self.option_type is None or not self.strike:
                raise ValueError("OPTION_RISK_INSTRUMENT_KEY_INCOMPLETE")
            option_type = getattr(self.option_type, "value", self.option_type)
            return f"{asset}:{self.symbol}:{self.expiry}:{option_type}:{self.strike}"
        if not self.symbol:
            raise ValueError("FUTURES_RISK_INSTRUMENT_KEY_REQUIRED")
        return f"{asset}:{self.symbol}"


@dataclass(frozen=True)
class ReferenceExecutionResult:
    approved: bool
    decision: str
    routed: bool
    effective_command: Optional[CanonicalRiskCommandAdapter]
    rejection_reason: Optional[str] = None


def route_after_risk(
    command: CanonicalOrderCommand,
    *,
    risk_gate: Any,
    account: Any,
    positions: Any,
    order_router: OrderRouterLike,
    sensor_snapshot: Any = None,
    allow_reduction: bool = False,
) -> ReferenceExecutionResult:
    """Preserve Reference ALLOW/REDUCE/DENY semantics at the Risk->Router boundary."""
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    approved, _token, rejection_reason = risk_gate.admit_order(
        adapted,
        account,
        positions,
        sensor_snapshot,
        allow_reduction,
    )
    result = risk_gate.last_evaluation_result

    if not approved or result is None:
        return ReferenceExecutionResult(
            approved=False,
            decision=getattr(result, "decision", "DENY"),
            routed=False,
            effective_command=None,
            rejection_reason=rejection_reason or getattr(result, "rejection_reason", None),
        )

    effective = (
        result.reduced_command
        if result.decision == "REDUCE" and result.reduced_command is not None
        else adapted
    )
    order_router.register_and_route(effective)
    return ReferenceExecutionResult(
        approved=True,
        decision=result.decision,
        routed=True,
        effective_command=effective,
    )


# 기존 route_after_risk()는 이미 변환된 Risk Account/Position 입력을 받는다.
# 실제 authoritative source를 직접 조립하는 별도 진입점은 향후 구현 예정.
def route_from_authoritative_sources(
    command: CanonicalOrderCommand,
    *,
    risk_gate: Any,
    account_snapshot: Any,
    position_manager: Any,
    order_router: OrderRouterLike,
    sensor_snapshot: Any = None,
    allow_reduction: bool = False,
) -> ReferenceExecutionResult:
    """Build Standard Risk inputs from authoritative sources, then route the result."""
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    inputs = build_risk_runtime_inputs(adapted, account_snapshot, position_manager)
    approved, _token, rejection_reason = risk_gate.admit_order(
        inputs.command, inputs.account, inputs.positions, sensor_snapshot, allow_reduction=allow_reduction
    )
    result = risk_gate.last_evaluation_result
    if not approved or result is None:
        return ReferenceExecutionResult(False, getattr(result, "decision", "DENY"), False, None, rejection_reason or getattr(result, "rejection_reason", None))
    effective = result.reduced_command if result.decision == "REDUCE" and result.reduced_command is not None else inputs.command
    order_router.register_and_route(effective)
    return ReferenceExecutionResult(True, result.decision, True, effective)


@dataclass(frozen=True)
class DecisionCommandContext:
    """Authoritative order identity supplied by Runtime/Controller."""
    client_order_id: str


def approved_signal_to_command(
    signal: Any,
    *,
    context: DecisionCommandContext,
) -> CanonicalOrderCommand:
    """Lossless approved CanonicalStrategySignal -> CanonicalOrderCommand transport.

    This boundary does not generate order identity or execution fields.
    """
    client_order_id = str(context.client_order_id or "").strip()
    if not client_order_id:
        raise ValueError("CLIENT_ORDER_ID_REQUIRED")
    if int(signal.qty) <= 0:
        raise ValueError("QTY_REQUIRED")
    if not str(signal.track_id or "").strip():
        raise ValueError("TRACK_ID_REQUIRED")

    asset_type = getattr(signal.asset_type, "value", signal.asset_type)
    if str(asset_type) == CanonicalAssetType.OPTION.value:
        if not str(getattr(signal, "symbol", "") or "").strip():
            raise ValueError("OPTION_SYMBOL_REQUIRED")
        if not str(getattr(signal, "expiry", "") or "").strip():
            raise ValueError("OPTION_EXPIRY_REQUIRED")
        if getattr(signal, "option_type", None) is None:
            raise ValueError("OPTION_TYPE_REQUIRED")

    return CanonicalOrderCommand(
        client_order_id=client_order_id,
        track_id=signal.track_id,
        asset_type=signal.asset_type,
        side=signal.side,
        qty=signal.qty,
        price=signal.price,
        option_type=signal.option_type,
        strike=signal.strike,
        symbol=getattr(signal, "symbol", ""),
        expiry=getattr(signal, "expiry", ""),
        tag_id=signal.tag_id,
        instrument_id=getattr(signal, "instrument_id", ""),
        contract_multiplier=getattr(signal, "contract_multiplier", None),
        identity_source=getattr(signal, "identity_source", ""),
    )
