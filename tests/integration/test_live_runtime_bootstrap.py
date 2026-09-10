from __future__ import annotations

from dataclasses import dataclass

import pytest

from application.bootstrap import LiveRuntimeBootstrap


@dataclass
class FakeFSM:
    pass


@dataclass
class FakeSettlement:
    order_state_machine: object


@dataclass
class FakeExecution:
    settlement: FakeSettlement


class FakeRouter:
    def __init__(self, fsm: object) -> None:
        self._order_state_machine = fsm


class FakeRecoveryService:
    def __init__(self) -> None:
        self.queries = []

    def recover(self, query):
        self.queries.append(query)
        return ("SETTLED",)


def test_startup_reconcile_uses_injected_recovery_service():
    fsm = FakeFSM()
    recovery = FakeRecoveryService()
    query = object()
    bootstrap = LiveRuntimeBootstrap(
        execution=FakeExecution(FakeSettlement(fsm)),
        order_router=FakeRouter(fsm),
        recovery_service=recovery,
    )

    assert bootstrap.startup_reconcile(query) == ("SETTLED",)
    assert recovery.queries == [query]


def test_startup_reconcile_fails_closed_without_recovery_service():
    fsm = FakeFSM()
    bootstrap = LiveRuntimeBootstrap(
        execution=FakeExecution(FakeSettlement(fsm)),
        order_router=FakeRouter(fsm),
    )

    with pytest.raises(ValueError, match="LIVE_RUNTIME_RECOVERY_SERVICE_REQUIRED"):
        pass
# bootstrap.startup_reconcile(object())


def test_oms_ownership_mismatch_fails_closed():
    execution_fsm = FakeFSM()
    router_fsm = FakeFSM()

    with pytest.raises(ValueError, match="LIVE_RUNTIME_OMS_OWNERSHIP_MISMATCH"):
        pass
        LiveRuntimeBootstrap(
            execution=FakeExecution(FakeSettlement(execution_fsm)),
            order_router=FakeRouter(router_fsm),
        )
