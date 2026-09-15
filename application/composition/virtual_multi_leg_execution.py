"""Runtime-owned multi-leg execution bridge for the Virtual environment."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from contracts.types import BrokerOrderCommand, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.oms.position_group import PositionGroup, PositionGroupLeg, PositionGroupLegPnL, PositionGroupRegistry, PositionGroupSnapshot, LegStatus
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext, route_from_runtime_authoritative_sources,
)
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


@dataclass(frozen=True)
class MultiLegExecutionResult:
    group_id: str
    strategy_id: str
    planned_legs: int
    approved_legs: int
    routed_legs: int
    filled_legs: int
    reports: tuple[ExecutionReport, ...]
    group_complete: bool


class _AckAdapter:
    def __init__(self, broker: Any) -> None:
        self.broker = broker
        self.last_report = None

    def submit(self, command: BrokerOrderCommand, **kwargs: Any):
        report = self.broker.submit(command)
        self.last_report = report
        if report is None:
            from contracts.types import BrokerOrderResponse
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        from contracts.types import BrokerOrderResponse
        return BrokerOrderResponse(command.client_order_id, True, broker_order_id=f"VIRTUAL-{report.execution_id}")


class VirtualMultiLegExecutionBridge:
    """Preserve group/leg identity while routing every leg through Risk -> OMS -> VSSF."""

    def __init__(self, *, bundle: Any, risk_config: RiskConfig | None = None) -> None:
        self.bundle = bundle
        self.fsm = OrderStateMachine()
        self.ack = _AckAdapter(bundle.broker)
        self.router = StandardOrderRouter(order_state_machine=self.fsm, broker_adapter=self.ack)
        vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
        self.risk_gate = RiskGate(RiskEngine(risk_config or RiskConfig(), margin_engine=vssf.margin_engine))
        self.command_context = CanonicalVSSFCommandContextProvider()
        self.groups: dict[str, list[ExecutionReport]] = {}
        self.position_groups = PositionGroupRegistry()
        self.provenance: dict[str, dict[str, str]] = {}

    @staticmethod
    def identity_for_leg(plan: MultiLegExecutionPlan, leg) -> OptionInstrumentIdentity:
        if leg.option_type not in {"CALL", "PUT"} or leg.strike is None:
            raise ValueError("MULTI_LEG_OPTION_IDENTITY_REQUIRED")
        symbol = f"KOSPI200_{plan.group_id}_{leg.leg_id}"
        return OptionInstrumentIdentity(
            instrument_id=symbol,
            symbol=symbol,
            expiry="202609",
            option_type=leg.option_type,
            strike=Decimal(str(leg.strike)),
        )

    def execute(self, plan: MultiLegExecutionPlan, *, price: Decimal) -> MultiLegExecutionResult:
        if not plan.legs:
            raise ValueError("MULTI_LEG_PLAN_EMPTY")
        reports: list[ExecutionReport] = []
        approved = routed = filled = 0
        account = self.bundle.account.snapshot()
        position = self.bundle.position

        for leg in plan.legs:
            identity = self.identity_for_leg(plan, leg)
            client_order_id = f"{plan.group_id}-{leg.leg_id}"
            broker_command = BrokerOrderCommand(
                client_order_id=client_order_id,
                instrument_id=identity.instrument_id,
                side=leg.side,
                quantity=leg.quantity,
                order_type="LIMIT",
                broker_symbol=identity.symbol,
                instrument_identity=identity,
                asset_type="OPTION",
                requested_price=price,
                strategy_id=plan.strategy_id,
                order_purpose=plan.purpose or "MULTI_LEG",
                track_id=plan.strategy_id,
                tag_id=leg.leg_id,
                group_id=plan.group_id,
                leg_id=leg.leg_id,
            )
            canonical = self.command_context.build_command(broker_command)
            # The Virtual VSSF order book is instrument-agnostic; load the
            # authoritative leg quote immediately before that leg is submitted.
            vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
            spread = Decimal("0.05")
            if leg.side == "BUY":
                vssf.order_book.update_bid_ask(float(price - spread), float(price))
            else:
                vssf.order_book.update_bid_ask(float(price), float(price + spread))
            result = route_from_runtime_authoritative_sources(
                canonical,
                risk_gate=self.risk_gate,
                context=RiskRouterContext(
                    account_snapshot=account,
                    position_source=position,
                    order_router=self.router,
                    broker_command=broker_command,
                ),
            )
            if not result.routed:
                continue
            approved += 1
            routed += 1
            raw = self.ack.last_report
            if raw is None:
                continue
            report = ExecutionReport(
                client_order_id=raw.client_order_id,
                broker_order_id=f"VIRTUAL-{raw.execution_id}",
                execution_id=raw.execution_id,
                status=raw.status,
                filled_quantity=raw.filled_quantity,
                remaining_quantity=raw.remaining_quantity,
                execution_price=raw.execution_price,
                execution_timestamp=raw.execution_timestamp,
                group_id=plan.group_id,
                leg_id=leg.leg_id,
            )
            reports.append(report)
            self.provenance[report.execution_id or client_order_id] = {
                "strategy_id": plan.strategy_id, "group_id": plan.group_id,
                "leg_id": leg.leg_id, "execution_id": report.execution_id or "",
            }
            if report.status == "FILLED":
                filled += report.filled_quantity

        self.groups[plan.group_id] = list(reports)
        group_legs = tuple(
            PositionGroupLeg(
                leg_id=leg.leg_id, group_id=plan.group_id,
                instrument_id=self.identity_for_leg(plan, leg).instrument_id,
                side=leg.side, quantity=leg.quantity,
                status=LegStatus.FILLED if any(r.leg_id == leg.leg_id and r.status == "FILLED" for r in reports) else LegStatus.REJECTED,
            ) for leg in plan.legs
        )
        group = PositionGroup(plan.group_id, plan.strategy_id, "MULTI_LEG", group_legs)
        if plan.group_id not in self.position_groups.all():
            self.position_groups.register(group)
        else:
            self.position_groups.replace(group)
        current_futures = float(getattr(self.bundle.market, "futures_price", price))
        option_quotes = getattr(self.bundle.market, "option_quotes", {})
        pnl_legs = []
        for leg in plan.legs:
            rep = next((r for r in reports if r.leg_id == leg.leg_id), None)
            if rep is None or rep.execution_price is None:
                continue
            direction = 1.0 if leg.side == "BUY" else -1.0
            quote = option_quotes.get((leg.option_type, float(leg.strike), self.identity_for_leg(plan, leg).expiry), {})
            current = float(quote.get("last", quote.get("ask" if leg.side == "BUY" else "bid", rep.execution_price)))
            pnl_legs.append(PositionGroupLegPnL(leg.leg_id, plan.group_id, rep.filled_quantity, float(rep.execution_price), current, (current-float(rep.execution_price))*rep.filled_quantity*direction*250000.0))
        snapshot = PositionGroupSnapshot(plan.group_id, plan.strategy_id, group.is_complete, tuple(pnl_legs), sum(x.pnl for x in pnl_legs))
        self.position_groups.update_snapshot(snapshot)
        return MultiLegExecutionResult(
            group_id=plan.group_id,
            strategy_id=plan.strategy_id,
            planned_legs=len(plan.legs),
            approved_legs=approved,
            routed_legs=routed,
            filled_legs=filled,
            reports=tuple(reports),
            group_complete=(len(reports) == len(plan.legs) and all(r.status == "FILLED" for r in reports)),
        )

    def group_reports(self, group_id: str) -> tuple[ExecutionReport, ...]:
        return tuple(self.groups.get(group_id, ()))
