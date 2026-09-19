from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext, route_from_runtime_authoritative_sources
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.types import BrokerOrderCommand, ExecutionReport, MultiLegExecutionPlan
from core.oms.order_router import StandardOrderRouter
from core.oms.oms_fsm import OrderStateMachine
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore


@dataclass(frozen=True)
class FuturesExecutionResult:
    group_id: str
    strategy_id: str
    reports: tuple[ExecutionReport, ...]
    group_complete: bool
    pnl: Decimal


class _AckAdapter:
    def __init__(self, broker: Any) -> None:
        self.broker = broker
        self.last_report = None

    def submit(self, command: BrokerOrderCommand, **kwargs: Any):
        from contracts.types import BrokerOrderResponse
        report = self.broker.submit(command)
        self.last_report = report
        if report is None:
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        return BrokerOrderResponse(command.client_order_id, True, broker_order_id=f"VIRTUAL-{report.execution_id}")


class VirtualFuturesExecutionBridge:
    """Single-leg Track3 Futures bridge through Risk -> OMS -> Virtual Broker/VSSF."""

    def __init__(self, *, bundle: Any, run_id: str, identity: Any, risk_config: RiskConfig | None = None) -> None:
        if not run_id.strip():
            raise ValueError("FUTURES_RUN_ID_REQUIRED")
        self.bundle = bundle
        self.run_id = run_id
        self.identity = identity
        self.position = VirtualPositionAggregate(instrument_id=identity.instrument_id)
        self.lots = VirtualPositionLotStore()
        self.provenance: dict[str, dict[str, str]] = {}
        self._fsm = OrderStateMachine()
        self._ack = _AckAdapter(bundle.broker)
        self._router = StandardOrderRouter(order_state_machine=self._fsm, broker_adapter=self._ack)
        vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
        self._risk_gate = RiskGate(RiskEngine(risk_config or RiskConfig(), margin_engine=vssf.margin_engine))
        self._context = CanonicalVSSFCommandContextProvider()
        self.risk_approvals: list[Any] = []

    def execute(self, plan: MultiLegExecutionPlan) -> FuturesExecutionResult:
        if len(plan.legs) != 1:
            raise ValueError("TRACK3_FUTURES_SINGLE_LEG_REQUIRED")
        leg = plan.legs[0]
        client_order_id = f"{plan.group_id}-{leg.leg_id}"
        price = Decimal(str(getattr(self.bundle.market, "futures_price", "0")))
        if price <= 0:
            raise ValueError("FUTURES_VIRTUAL_QUOTE_REQUIRED")
        broker_command = BrokerOrderCommand(
            client_order_id=client_order_id, instrument_id=self.identity.instrument_id,
            side=leg.side, quantity=leg.quantity, order_type="LIMIT",
            broker_symbol=self.identity.symbol, instrument_identity=self.identity,
            asset_type="FUTURES", requested_price=price, strategy_id=plan.strategy_id,
            order_purpose=plan.purpose or "TRACK3_FUTURES_EXECUTION", track_id=plan.strategy_id,
            tag_id=leg.leg_id, group_id=plan.group_id, leg_id=leg.leg_id,
            position_role=leg.position_role,
        )
        canonical = self._context.build_command(broker_command)
        vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
        vssf.order_book.update_bid_ask(float(price), float(price), self.identity.instrument_id)
        routed = route_from_runtime_authoritative_sources(
            canonical, risk_gate=self._risk_gate,
            context=RiskRouterContext(account_snapshot=self.bundle.account.snapshot(), position_source=self.position,
                                      order_router=self._router, broker_command=broker_command),
        )
        evaluation = self._risk_gate.last_evaluation_result
        self.risk_approvals.append(evaluation)
        if not routed.routed:
            return FuturesExecutionResult(plan.group_id, plan.strategy_id, (), False, Decimal("0"))
        raw = self._ack.last_report
        if raw is None or not raw.execution_id:
            raise RuntimeError("TRACK3_FUTURES_EXECUTION_REPORT_REQUIRED")
        report = ExecutionReport(
            client_order_id=raw.client_order_id, broker_order_id=f"VIRTUAL-{raw.execution_id}",
            execution_id=raw.execution_id, status=raw.status, filled_quantity=raw.filled_quantity,
            remaining_quantity=raw.remaining_quantity, execution_price=raw.execution_price,
            execution_timestamp=raw.execution_timestamp, fee=Decimal(str(getattr(raw, "fee", "0"))),
            group_id=plan.group_id, leg_id=leg.leg_id,
        )
        if report.status != "FILLED" or report.execution_timestamp is None or report.execution_price is None:
            raise RuntimeError("TRACK3_FUTURES_FILL_REQUIRED")
        lot = PositionLotProvenance(
            run_id=self.run_id, instrument_id=self.identity.instrument_id,
            strategy_id=plan.strategy_id, group_id=plan.group_id, leg_id=leg.leg_id,
            client_order_id=client_order_id, execution_id=report.execution_id,
            side=leg.side, opened_quantity=report.filled_quantity,
            remaining_quantity=report.filled_quantity, execution_timestamp=report.execution_timestamp,
            instrument_identity=self.identity, contract_multiplier=self.identity.contract_multiplier,
            identity_source=self.identity.identity_source, position_role=PositionRole(leg.position_role),
        )
        self.lots.apply_execution(lot)
        VirtualPositionFillAdapter(self.position).apply(broker_command, report)
        mark = price
        direction = Decimal("1") if leg.side == "BUY" else Decimal("-1")
        pnl = (mark - Decimal(str(report.execution_price))) * report.filled_quantity * direction * self.identity.contract_multiplier
        self.provenance[report.execution_id] = {
            "run_id": self.run_id, "strategy_id": plan.strategy_id, "group_id": plan.group_id,
            "leg_id": leg.leg_id, "client_order_id": client_order_id, "execution_id": report.execution_id,
            "instrument_id": self.identity.instrument_id, "symbol": self.identity.symbol,
            "product_type": str(self.identity.product_type), "contract_multiplier": str(self.identity.contract_multiplier),
            "identity_source": self.identity.identity_source,
        }
        return FuturesExecutionResult(plan.group_id, plan.strategy_id, (report,), True, pnl)
