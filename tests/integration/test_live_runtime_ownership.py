import asyncio
import pytest
from application.bootstrap import LiveRuntimeBootstrap

class X:
    async def start_execution(self, h): pass
    async def receive_execution_once(self): return None
    async def close_execution(self): pass

class Settlement:
    def __init__(self, fsm): self.order_state_machine=fsm
class Execution:
    def __init__(self, fsm): self.settlement=Settlement(fsm)
    async def start_execution(self,h): pass
    async def receive_execution_once(self): return None
    async def close_execution(self): pass
class Router:
    def __init__(self, fsm): self._order_state_machine=fsm
    def register_and_route(self,*a,**k): return None
class Ctx:
    def __init__(self, router): self.order_router=router
class Transport:
    def __init__(self, router): self.risk_context=Ctx(router)

def test_shared_oms_and_router_ownership_passes():
    fsm=object(); router=Router(fsm)
    bootstrap=LiveRuntimeBootstrap(Execution(fsm),router,Transport(router))
# assert bootstrap.execution.settlement.order_state_machine is router._order_state_machine

def test_mismatched_oms_or_router_fails_closed():
    with pytest.raises(ValueError, match='LIVE_RUNTIME_OMS_OWNERSHIP_MISMATCH'):
        LiveRuntimeBootstrap(Execution(object()),Router(object()))
    fsm=object(); router=Router(fsm)
    with pytest.raises(ValueError, match='LIVE_RUNTIME_ROUTER_OWNERSHIP_MISMATCH'):
        LiveRuntimeBootstrap(Execution(fsm),router,Transport(Router(fsm)))
