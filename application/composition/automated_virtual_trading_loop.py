"""Runtime-owned Strategy -> Orchestrator -> Risk/OMS -> Virtual Broker loop."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Callable

from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext, route_from_runtime_authoritative_sources,
)
from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, ExecutionReport, OptionInstrumentIdentity
from contracts.track9_fee_ledger import Track9FeeRecord, Track9FeeLedger
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_config import RiskConfig
from core.strategy.contracts import StrategyContext
from application.strategy_hub.contracts import StrategyHubPort
from application.strategy_hub.hub import StrategyHub
from core.domain.market_models import MarketState
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


@dataclass(frozen=True)
class AutomatedTickResult:
    tick_sequence: int
    signals: int
    approved: int
    routed: int
    filled: int
    rejected: int
    execution_ids: tuple[str, ...]


class _VirtualBrokerAckAdapter:
    def __init__(self, broker) -> None:
        self.broker = broker
        self.last_report = None

    def submit(self, command, **kwargs):
        report = self.broker.submit(command)
        self.last_report = report
        if report is None:
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        return BrokerOrderResponse(
            command.client_order_id, True, broker_order_id=f"VIRTUAL-{report.execution_id}"
        )


class AutomatedVirtualTradingLoop:
    """Connect real Virtual Market ticks to registered Strategy execution."""

    def __init__(self, *, bundle, strategy_hub: StrategyHubPort, run_id: str, fee_ledger: Track9FeeLedger | None = None,
                 context_builder: Callable[[object, MarketState], dict[str, StrategyContext]],
                 identity_provider: Callable[[object], OptionInstrumentIdentity],
                 risk_config: RiskConfig | None = None) -> None:
        if not run_id.strip():
            raise ValueError("AUTOMATED_RUNTIME_RUN_ID_REQUIRED")
        self.bundle = bundle
        self.run_id = run_id
        self.fee_ledger = fee_ledger
        self.strategy_hub = strategy_hub
        self.context_builder = context_builder
        self.identity_provider = identity_provider
        self.strategy_results = RuntimeStrategyResultCollectionAdapter()
        self.strategy_to_decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
        self.decision_to_command = RuntimeDecisionCommandAdapter()
        self.fsm = OrderStateMachine()
        self.broker_adapter = _VirtualBrokerAckAdapter(bundle.broker)
        self.router = StandardOrderRouter(order_state_machine=self.fsm, broker_adapter=self.broker_adapter)
        vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
        self.risk_gate = RiskGate(RiskEngine(risk_config or RiskConfig(), margin_engine=vssf.margin_engine))
        self._last_result: AutomatedTickResult | None = None

    @property
    def last_result(self) -> AutomatedTickResult | None:
        return self._last_result

    def on_tick(self, tick) -> AutomatedTickResult:
        as_of = datetime.fromisoformat(tick.timestamp)
        state = MarketState(
            as_of=as_of,
            ticks={"KOSPI200": type("Tick", (), {
                "instrument_id": "KOSPI200", "observed_at": as_of,
                "price": Decimal(str(tick.underlying_price)), "volume": Decimal(str(tick.volume)),
            })()},
            quality={},
        )
        contexts = self.context_builder(tick, state)
        strategy_result = self.strategy_hub.run(contexts)
        evaluations = self.strategy_results.collect(
            tick_sequence=tick.seq_id, context=next(iter(contexts.values())), result=strategy_result
        )
        decision = self.strategy_to_decision.arbitrate(
            evaluations, price=tick.ask_price, timestamp=tick.timestamp,
            account=self.bundle.account.snapshot(),
            instrument_identity_provider=self.identity_provider,
            market_tick=tick,
        )
        approved = tuple(decision.arbitration.approved_signals[:1])
        commands = self.decision_to_command.build_commands(evaluations, approved)
        routed = 0
        filled = 0
        rejected = len(decision.arbitration.rejected_signals)
        execution_ids: list[str] = []

        for canonical in commands:
            broker_command = BrokerOrderCommand(
                client_order_id=canonical.client_order_id,
                instrument_id=canonical.symbol or "KOSPI200",
                side=canonical.side.value,
                quantity=canonical.qty,
                order_type="LIMIT",
                broker_symbol=canonical.symbol or "KOSPI200",
                instrument_identity=(self.identity_provider(next(e for e in evaluations if e.runtime_context.client_order_id(canonical.track_id) == canonical.client_order_id), tick) if canonical.asset_type.value == "OPTION" else None),
                asset_type=canonical.asset_type.value,
                requested_price=Decimal(str(tick.ask_price)),
                strategy_id=canonical.track_id,
                order_purpose="AUTOMATED_STRATEGY",
                track_id=canonical.track_id,
                tag_id=canonical.tag_id or "STRATEGY",
                group_id=canonical.client_order_id,
                leg_id=canonical.tag_id or canonical.client_order_id,
            )
            account = self.bundle.account.snapshot()
            risk_command = replace(canonical, symbol=canonical.symbol or "KOSPI200")
            result = route_from_runtime_authoritative_sources(
                risk_command, risk_gate=self.risk_gate,
                context=RiskRouterContext(account, self.bundle.position, self.router, broker_command),
            )
            if not result.routed or self.broker_adapter.last_report is None:
                rejected += 1
                continue
            routed += 1
            report = self.broker_adapter.last_report
            broker_id = f"VIRTUAL-{report.execution_id}"
            self.fsm.apply_execution(ExecutionReport(
                client_order_id=report.client_order_id,
                broker_order_id=broker_id,
                execution_id=report.execution_id,
                status=report.status,
                filled_quantity=report.filled_quantity,
                remaining_quantity=report.remaining_quantity,
                execution_price=report.execution_price,
                execution_timestamp=report.execution_timestamp,
                fee=report.fee,
                group_id=report.group_id,
                leg_id=report.leg_id,
            ))
            if report.status == "FILLED":
                if self.fee_ledger is not None:
                    if report.execution_id is None or report.execution_timestamp is None or report.execution_price is None or report.fee is None:
                        raise RuntimeError("AUTOMATED_RUNTIME_FEE_PROVENANCE_REQUIRED")
                    self.fee_ledger.record(
                        Track9FeeRecord(
                            run_id=self.run_id,
                            strategy_id=canonical.track_id,
                            group_id=broker_command.group_id or "",
                            leg_id=broker_command.leg_id or "",
                            client_order_id=report.client_order_id,
                            execution_id=report.execution_id,
                            instrument_id=broker_command.instrument_id,
                            fee_amount=report.fee,
                            executed_quantity=report.filled_quantity,
                            executed_price=report.execution_price,
                            executed_at=report.execution_timestamp,
                            source="VSSF:CanonicalExecutionReport.fee",
                        )
                    )
                filled += report.filled_quantity
                execution_ids.append(report.execution_id)

        self._last_result = AutomatedTickResult(
            tick_sequence=tick.seq_id, signals=len(strategy_result.signals),
            approved=len(approved), routed=routed, filled=filled,
            rejected=rejected, execution_ids=tuple(execution_ids),
        )
        return self._last_result



