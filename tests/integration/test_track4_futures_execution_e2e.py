from datetime import datetime
from decimal import Decimal
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_identity_source import KisFuturesIdentitySource
from application.composition.futures_target_configuration import FuturesTargetConfiguration
from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext, route_from_runtime_authoritative_sources
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from contracts.types import BrokerOrderResponse, ExecutionReport
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from application.composition.track4_market_input_materializer import Track4RuntimeInputMaterializer
from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from contracts.futures_contract_spec import FuturesProductType
from contracts.types import BrokerOrderCommand
from core.decision.decision_arbiter import DecisionArbiter
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track4_gamma_scalping import Track4MarketInput, Track4GammaScalping
from tests.risk_guard_test_support import allow_risk_guard


def _identity():
    raw = Path("fo_idx_code_mts.mst").read_bytes().decode("cp949", errors="replace")
    source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(raw))
    target = FuturesTargetConfiguration(underlying_short_code="2001", product_type=FuturesProductType.STANDARD)
    return KisFuturesIdentitySource(source, target).current_identity()


class _BrokerAck:
    def __init__(self, broker):
        self.broker = broker
        self.last_report = None

    def submit(self, command, **kwargs):
        self.last_report = self.broker.submit(command)
        if self.last_report is None:
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        return BrokerOrderResponse(command.client_order_id, True, broker_order_id=f"VIRTUAL-{self.last_report.execution_id}")


def _context(data):
    analytics = build_track4_analytics_snapshot(data, run_id="track4-e2e", as_of=data.observed_at)
    return StrategyContext(
        strategy_id="track4_gamma_scalping",
        input=StrategyInput(
            common=CommonStrategyInput(as_of=data.observed_at, current_price=data.current_price),
            payload=data,
        ),
        analytics=analytics,
    )


def test_track4_strategy_to_virtual_execution_position_pnl_e2e():
    as_of = datetime(2026, 9, 18, 10, 0)
    data = Track4MarketInput(
        observed_at=as_of,
        current_price=Decimal("500"),
        active_vol=Decimal("0.12"),
        base_vol=Decimal("0.10"),
        time_str="10:00:00",
        current_delta=Decimal("0.52"),
        current_gamma=Decimal("0.18"),
        current_pnl=Decimal("0"),
        current_equity=Decimal("250000000"),
        price_history=(Decimal("499"), Decimal("500")),
    )
    strategy = Track4GammaScalping()
    context = _context(data)
    signals = strategy.evaluate(context)
    execution = [s for s in signals if s.execution_proposal is not None]
    assert execution
    signal = execution[0]
    identity = _identity()
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1, context=context, result=type("Result", (), {"signals": tuple(signals), "failures": ()})()
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=500.0,
        timestamp=as_of.isoformat(),
        account={"available_cash": 250_000_000},
        instrument_identity_provider=lambda _evaluation, _tick: identity,
    )
    approved = decision.arbitration.approved_signals
    assert approved
    assert any(s.track_id == signal.strategy_id and s.side.value == signal.direction for s in approved)
    canonical = RuntimeDecisionCommandAdapter().build_commands(evaluations, approved)[0]
    assert canonical.asset_type.value == "FUTURES"
    assert canonical.instrument_id == identity.instrument_id
    assert canonical.contract_multiplier == float(identity.contract_multiplier)

    bootstrap = create_virtual_runtime_bootstrap(
        initial_capital=500_000_000.0,
        risk_guard_status_source=allow_risk_guard(),
    )
    bundle = bootstrap.bundle
    market_tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    bundle.broker.process_market_data(market_tick)
    broker_command = BrokerOrderCommand(
        client_order_id=canonical.client_order_id,
        instrument_id=identity.instrument_id,
        side=canonical.side.value,
        quantity=canonical.qty,
        order_type="LIMIT",
        broker_symbol=identity.symbol,
        instrument_identity=identity,
        asset_type="FUTURES",
        requested_price=Decimal(str(market_tick.bid_price if canonical.side.value == "SELL" else market_tick.ask_price)),
        strategy_id=canonical.track_id,
        order_purpose="TRACK4_GAMMA_REBALANCE",
        track_id=canonical.track_id,
        tag_id=canonical.tag_id or "GAMMA_REBALANCE",
    )
    ack = _BrokerAck(bundle.broker)
    router = StandardOrderRouter(order_state_machine=OrderStateMachine(), broker_adapter=ack)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    risk_gate = RiskGate(RiskEngine(RiskConfig(), margin_engine=vssf.margin_engine), risk_guard_status_source=allow_risk_guard())
    routed = route_from_runtime_authoritative_sources(
        canonical,
        risk_gate=risk_gate,
        context=RiskRouterContext(bundle.account.snapshot(), bundle.position, router, broker_command),
    )
    assert routed.approved is True
    assert routed.routed is True
    report = ack.last_report
    assert report is not None
    assert report.status == "FILLED"
    assert report.filled_quantity == canonical.qty
    assert report.execution_id
    assert bundle.position.snapshot()
    balances = bundle.account.snapshot().balances
    assert balances["margin_used"] > 0
    assert balances["unrealized_pnl"] is not None
    print("TRACK4_E2E_EVIDENCE", {
        "track": canonical.track_id,
        "signal_direction": signal.direction,
        "instrument_id": identity.instrument_id,
        "identity_source": identity.identity_source,
        "client_order_id": report.client_order_id,
        "execution_id": report.execution_id,
        "filled": report.filled_quantity,
        "execution_price": report.execution_price,
        "position_count": len(bundle.position.snapshot()),
        "margin_used": balances["margin_used"],
        "unrealized_pnl": balances["unrealized_pnl"],
    })
