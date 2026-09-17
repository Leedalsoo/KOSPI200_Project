from dataclasses import dataclass
import pytest
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import StandardOrderRouter
from core.position.position_aggregate import PositionAggregate
from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext, route_from_runtime_authoritative_sources
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide

class PositionSource:
    def snapshot(self): return {"FUTURES:K200": PositionAggregate("BUY", 2, 350.0)}
class Account:
    total_balance=1_000_000.0; realized_pnl=0.0; used_margin=0.0; free_margin=1_000_000.0
@dataclass
class Result:
    decision: str = "ALLOW"; reduced_command: object = None; rejection_reason: str | None = None
class Gate:
    def __init__(self, reduced=None): self.last_evaluation_result=Result('REDUCE' if reduced else 'ALLOW', reduced); self.reduced=reduced
    def admit_order(self, *args): return True, 'TOKEN', None
class Broker:
    def submit(self, command): return BrokerOrderResponse(command.client_order_id, True, 'B-1')

def canonical(qty=5):
    return CanonicalOrderCommand("ORD-1","T1",CanonicalAssetType.FUTURES,CanonicalOrderSide.BUY,qty,350.0,symbol="K200")
def broker_command(qty=5):
    return BrokerOrderCommand("ORD-1","AUTH-FUT-1","BUY",qty,"LIMIT",broker_symbol="101V09")

def test_runtime_risk_router_to_standard_router_ack_e2e_allow():
    fsm=OrderStateMachine(); router=StandardOrderRouter(order_state_machine=fsm, broker_adapter=Broker())
    result=route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(), context=RiskRouterContext(Account(),PositionSource(),router,broker_command()))
# assert result.routed is True
    assert fsm.get("ORD-1").status == "ACKED"

def test_reduce_only_projects_authoritative_quantity():
    effective=type('Reduced',(),{'client_order_id':'ORD-1','qty':2})()
    fsm=OrderStateMachine(); router=StandardOrderRouter(order_state_machine=fsm, broker_adapter=Broker())
    result=route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(effective), context=RiskRouterContext(Account(),PositionSource(),router,broker_command()))
    assert result.decision == 'REDUCE'
    assert fsm.command_for("ORD-1").quantity == 2

def test_risk_quantity_increase_fails_closed():
    effective=type('Bad',(),{'client_order_id':'ORD-1','qty':6})()
    with pytest.raises(ValueError, match='RISK_QUANTITY_INCREASE_FORBIDDEN'):
        route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(effective), context=RiskRouterContext(Account(),PositionSource(),object(),broker_command()))
