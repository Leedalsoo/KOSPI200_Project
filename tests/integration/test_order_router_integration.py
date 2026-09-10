from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import OrderRouterError, StandardOrderRouter

class Broker:
    def __init__(self): self.calls = []
    def submit(self, command):
        self.calls.append(command)
        return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="B-1")

def command():
    return BrokerOrderCommand(client_order_id="C-1", instrument_id="FUT-1", side="BUY", quantity=2, order_type="LIMIT", broker_symbol="101V09")

def test_router_registers_submits_and_applies_ack():
    fsm = OrderStateMachine(); broker = Broker()
    router = StandardOrderRouter(order_state_machine=fsm, broker_adapter=broker)
    response = router.register_and_route(command(), token=object())
    assert response.accepted is True and len(broker.calls) == 1
    state = fsm.get("C-1")
    assert state is not None and state.status == "ACKED" and state.broker_order_id == "B-1"

def test_router_fails_closed_without_token_or_broker():
    fsm = OrderStateMachine(); router = StandardOrderRouter(order_state_machine=fsm)
    try: router.register_and_route(command(), token=None)
    except OrderRouterError as exc: assert str(exc) == "RISK_APPROVAL_TOKEN_REQUIRED"
    else: raise AssertionError("expected token fail-closed")
    try: router.register_and_route(command(), token=object())
    except OrderRouterError as exc: assert str(exc) == "BROKER_ADAPTER_REQUIRED"
    else: raise AssertionError("expected broker fail-closed")
