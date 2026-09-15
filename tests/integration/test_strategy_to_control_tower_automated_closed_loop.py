from datetime import datetime
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext, route_from_runtime_authoritative_sources
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, ExecutionReport, OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_config import RiskConfig
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import build_standard_strategy_registry
from core.strategy.track1_tail_defense import Track1Input
from core.domain.market_models import MarketState
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


class BrokerAckAdapter:
    """OMS broker boundary: real VirtualBroker execution + transport ACK."""
    def __init__(self, broker):
        self.broker = broker
        self.last_report = None

    def submit(self, command, **kwargs):
        self.last_report = self.broker.submit(command)
        if self.last_report is None:
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        return BrokerOrderResponse(
            command.client_order_id, True, broker_order_id=f"VIRTUAL-{self.last_report.execution_id}"
        )


def test_actual_strategy_orchestrator_to_virtual_broker_position_pnl_control_tower_loop():
    # Authoritative Virtual Runtime composition: VMS -> VSSF -> Broker/Execution.
    bootstrap = create_virtual_runtime_bootstrap(initial_capital=250_000_000.0)
    bundle = bootstrap.bundle
    tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    as_of = datetime.fromisoformat(tick.timestamp)
    market_state = MarketState(
        as_of=as_of,
        ticks={"KOSPI200": type("Tick", (), {
            "instrument_id": "KOSPI200", "observed_at": as_of,
            "price": Decimal(str(tick.underlying_price)), "volume": Decimal(str(tick.volume)),
        })()},
        quality={},
    )

    # Actual registered strategy + actual StrategyOrchestrator lifecycle.
    registry = build_standard_strategy_registry()
    orchestrator = StrategyOrchestrator(registry, (("TRACK1_TAIL_DEFENSE", "1.1.0"),))
    context = StrategyContext(
        market_state=market_state,
        strategy_id="TRACK1_TAIL_DEFENSE",
        input=StrategyInput(
            common=CommonStrategyInput(as_of=as_of, current_price=Decimal(str(tick.underlying_price))),
            payload=Track1Input(days_to_expiry=10.0, current_time=as_of, active_vol=1.0, base_vol=1.0),
        ),
    )
    strategy_result = orchestrator.run({"TRACK1_TAIL_DEFENSE": context})
    assert strategy_result.failures == ()
    assert strategy_result.signals

    # Runtime-owned IDs -> canonical signal -> Decision arbitration.
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=tick.seq_id, context=context, result=strategy_result
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=tick.ask_price,
        timestamp=tick.timestamp,
        account=bundle.account.snapshot(),
        instrument_identity_provider=lambda ev: OptionInstrumentIdentity(
            instrument_id="KOSPI200", symbol="KOSPI200", expiry=tick.expiry,
            option_type=ev.result.execution_proposal.option_type,
            strike=ev.result.execution_proposal.strike,
        ),
    )
    assert decision.arbitration.approved_signals
    approved = (decision.arbitration.approved_signals[0],)
    canonical = RuntimeDecisionCommandAdapter().build_commands(evaluations, approved)[0]

    # Preserve the authoritative option identity and actual Virtual ask price.
    broker_command = BrokerOrderCommand(
        client_order_id=canonical.client_order_id,
        instrument_id="KOSPI200",
        side=canonical.side.value,
        quantity=canonical.qty,
        order_type="LIMIT",
        broker_symbol="KOSPI200",
        instrument_identity=OptionInstrumentIdentity(
            instrument_id="KOSPI200", symbol="KOSPI200", expiry=canonical.expiry,
            option_type=canonical.option_type.value, strike=Decimal(str(canonical.strike)),
        ),
        asset_type=canonical.asset_type.value,
        requested_price=Decimal(str(tick.ask_price)),
        strategy_id=canonical.track_id,
        order_purpose="AUTOMATED_STRATEGY_TEST",
        track_id=canonical.track_id,
        tag_id=canonical.tag_id or "STRATEGY",
    )

    # Actual RiskGate -> OMS OrderRouter -> VirtualBroker path.
    ack_adapter = BrokerAckAdapter(bundle.broker)
    fsm = OrderStateMachine()
    router = StandardOrderRouter(order_state_machine=fsm, broker_adapter=ack_adapter)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    risk_gate = RiskGate(RiskEngine(RiskConfig(), margin_engine=vssf.margin_engine))
    routed = route_from_runtime_authoritative_sources(
        canonical,
        risk_gate=risk_gate,
        context=RiskRouterContext(bundle.account.snapshot(), bundle.position, router, broker_command),
    )
    assert routed.approved is True
    assert routed.routed is True
    assert ack_adapter.last_report is not None
    report = ack_adapter.last_report
    assert report.filled_quantity == canonical.qty
    assert report.execution_price == tick.ask_price

    # OMS receives ACK and then the actual execution report.
    state = fsm.get(broker_command.client_order_id)
    assert state is not None and state.status == "ACKED"
    fsm.apply_execution(ExecutionReport(
        client_order_id=report.client_order_id,
        broker_order_id=f"VIRTUAL-{report.execution_id}",
        execution_id=report.execution_id,
        status="FILLED",
        filled_quantity=report.filled_quantity,
        remaining_quantity=0,
        execution_price=Decimal(str(report.execution_price)),
        execution_timestamp=datetime.fromisoformat(report.execution_timestamp.isoformat()),
    ))
    assert fsm.get(broker_command.client_order_id).status == "FILLED"

    # Authoritative Position/Margin/PnL state and Control Tower DTO are read back.
    assert bundle.position.snapshot()
    balances = bundle.account.snapshot().balances
    assert balances["margin_used"] > 0
    assert "available_cash" in balances
    assert bundle.execution.reports()

    class Hub: active = bundle
    class Controller:
        _hub = Hub()
        def status(self): return type("Status", (), {"state": "RUNNING"})()

    tower = ControlTowerUIAdapter(runtime_controller=Controller(), risk_engine=risk_gate.engine)
    view = tower.get_tab_detail("virtual_broker")
    assert view["recent_executions"]
    assert view["positions"]
    assert view["margin_used"] == float(balances["margin_used"])
    assert view["margin_available"] == float(balances["available_cash"])
    assert view["realized_pnl"] is not None
    assert view["unrealized_pnl"] is not None

    print("AUTOMATED_LOOP_EVIDENCE", {"tick_seq": tick.seq_id, "underlying": tick.underlying_price, "ask": tick.ask_price, "strategy_signals": len(strategy_result.signals), "approved": len(decision.arbitration.approved_signals), "track": canonical.track_id, "client_order_id": broker_command.client_order_id, "execution_id": report.execution_id, "filled": report.filled_quantity, "execution_price": report.execution_price, "position_count": len(bundle.position.snapshot()), "margin_used": balances["margin_used"], "margin_available": balances["available_cash"], "realized_pnl": balances["realized_pnl"], "unrealized_pnl": balances["unrealized_pnl"], "control_tower_executions": len(view["recent_executions"]), "control_tower_positions": len(view["positions"])})
