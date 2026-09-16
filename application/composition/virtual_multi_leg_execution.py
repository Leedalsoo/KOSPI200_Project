"""Runtime-owned multi-leg execution bridge for the Virtual environment."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from contracts.types import BrokerOrderCommand, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.option.option_master import IOptionContractMaster
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.oms.position_group import PositionGroup, PositionGroupLeg, PositionGroupLegPnL, PositionGroupRegistry, PositionGroupSnapshot, LegStatus
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_approval_read_model import RiskApprovalReadModel, RiskApprovalRecord
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

    def __init__(self, *, bundle: Any, option_master: IOptionContractMaster | None = None, risk_config: RiskConfig | None = None) -> None:
        self.bundle = bundle
        self.option_master = option_master or getattr(bundle, "option_master", None)
        self.fsm = OrderStateMachine()
        self.ack = _AckAdapter(bundle.broker)
        self.router = StandardOrderRouter(order_state_machine=self.fsm, broker_adapter=self.ack)
        vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
        self.risk_gate = RiskGate(RiskEngine(risk_config or RiskConfig(), margin_engine=vssf.margin_engine))
        self.risk_approval_read_model = RiskApprovalReadModel()
        self.command_context = CanonicalVSSFCommandContextProvider()
        self.groups: dict[str, list[ExecutionReport]] = {}
        self.position_groups = PositionGroupRegistry()
        self.provenance: dict[str, dict[str, str]] = {}

    def identity_for_leg(self, plan: MultiLegExecutionPlan, leg) -> OptionInstrumentIdentity:
        if leg.option_type not in {"CALL", "PUT"} or leg.strike is None:
            raise ValueError("MULTI_LEG_OPTION_IDENTITY_REQUIRED")
        if self.option_master is None:
            raise ValueError("MULTI_LEG_OPTION_MASTER_REQUIRED")
        option_quotes = getattr(self.bundle.market, "option_quotes", {})
        matching_expiries = sorted({
            str(expiry).replace("-", "")[:6]
            for key in option_quotes
            if isinstance(key, tuple) and len(key) == 3
            and str(key[0]).upper() == str(leg.option_type).upper()
            and float(key[1]) == float(leg.strike)
            for expiry in (key[2],)
        })
        if len(matching_expiries) != 1:
            raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_EXPIRY_REQUIRED")
        identity = self.option_master.find_contract_identity(
            matching_expiries[0], leg.option_type, Decimal(str(leg.strike))
        )
        if identity is None or not identity.shrn_iscd:
            raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_IDENTITY_NOT_FOUND")
        return OptionInstrumentIdentity(
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            expiry=identity.expiry.replace("-", "")[:6],
            option_type=identity.option_type,
            strike=identity.strike,
        )

    def execute(self, plan: MultiLegExecutionPlan, *, price: Decimal | None = None) -> MultiLegExecutionResult:
        if not plan.legs:
            raise ValueError("MULTI_LEG_PLAN_EMPTY")
        reports: list[ExecutionReport] = []
        approved = routed = filled = 0
        account = self.bundle.account.snapshot()
        position = self.bundle.position

        for leg in plan.legs:
            identity = self.identity_for_leg(plan, leg)
            client_order_id = f"{plan.group_id}-{leg.leg_id}"
            vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
            option_quotes = getattr(self.bundle.market, "option_quotes", {})
            quote_key = (identity.option_type, float(identity.strike), identity.expiry)
            quote = option_quotes.get(quote_key)
            if quote is None:
                raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_QUOTE_NOT_FOUND")
            authoritative = self.option_master.get_contract_identity(identity.instrument_id)
            if authoritative is None or authoritative.contract_multiplier is None:
                raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_MULTIPLIER_REQUIRED")
            quote_multiplier = quote.get("contract_multiplier")
            if quote_multiplier is None or Decimal(str(quote_multiplier)) != authoritative.contract_multiplier:
                raise ValueError("MULTI_LEG_OPTION_CONTRACT_MULTIPLIER_MISMATCH")
            bid = Decimal(str(quote.get("bid", "0")))
            ask = Decimal(str(quote.get("ask", "0")))
            execution_reference = ask if leg.side == "BUY" else bid
            if execution_reference <= 0:
                raise ValueError("MULTI_LEG_OPTION_QUOTE_INVALID")
            broker_command = BrokerOrderCommand(
                client_order_id=client_order_id,
                instrument_id=identity.instrument_id,
                side=leg.side,
                quantity=leg.quantity,
                order_type="LIMIT",
                broker_symbol=identity.symbol,
                instrument_identity=identity,
                asset_type="OPTION",
                requested_price=execution_reference,
                strategy_id=plan.strategy_id,
                order_purpose=plan.purpose or "MULTI_LEG",
                track_id=plan.strategy_id,
                tag_id=leg.leg_id,
                group_id=plan.group_id,
                leg_id=leg.leg_id,
            )
            canonical = self.command_context.build_command(broker_command)
            vssf.order_book.update_bid_ask(float(bid), float(ask), identity.instrument_id)
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
            risk_evaluation = self.risk_gate.last_evaluation_result
            if risk_evaluation is None:
                raise RuntimeError("MULTI_LEG_RISK_RESULT_UNAVAILABLE")
            self.risk_approval_read_model.record(
                RiskApprovalRecord(
                    plan.strategy_id, plan.group_id, leg.leg_id, client_order_id, risk_evaluation
                )
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
                "instrument_id": identity.instrument_id, "symbol": identity.symbol,
                "expiry": identity.expiry or "", "option_type": identity.option_type or "",
                "strike": str(identity.strike),
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
            identity = self.identity_for_leg(plan, leg)
            quote = option_quotes.get((identity.option_type, float(identity.strike), identity.expiry))
            if quote is None or quote.get("last") is None:
                raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_MARK_NOT_FOUND")
            current = float(quote["last"])
            multiplier = Decimal(str(quote.get("contract_multiplier", "0")))
            if multiplier <= 0:
                raise ValueError("MULTI_LEG_OPTION_CONTRACT_MULTIPLIER_REQUIRED")
            pnl = (
                Decimal(str(current)) - Decimal(str(rep.execution_price))
            ) * Decimal(str(rep.filled_quantity)) * Decimal(str(direction)) * multiplier
            pnl_legs.append(
                PositionGroupLegPnL(
                    leg.leg_id, plan.group_id, rep.filled_quantity,
                    float(rep.execution_price), current, float(pnl)
                )
            )
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

    def risk_approvals(self, group_id: str) -> tuple[RiskApprovalRecord, ...]:
        return self.risk_approval_read_model.for_group(group_id)
