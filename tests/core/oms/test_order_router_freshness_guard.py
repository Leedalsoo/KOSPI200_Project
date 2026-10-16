from types import SimpleNamespace

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext, route_from_runtime_authoritative_sources,
)
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide,
)


def _command():
    return CanonicalOrderCommand(
        client_order_id="client-1", track_id="S1",
        asset_type=CanonicalAssetType.OPTION, side=CanonicalOrderSide.BUY,
        qty=1, price=1.0, symbol="A12345", expiry="20261029",
        instrument_id="OPT-1",
    )


class _Router:
    def __init__(self):
        self.calls = 0

    def register_and_route(self, *args, **kwargs):
        self.calls += 1


class _RejectingGate:
    def __init__(self):
        self.calls = 0
        self.last_evaluation_result = None

    def admit_order(self, *args, **kwargs):
        self.calls += 1
        return False, None, "TEST_RISK_DENY"


def _fresh_verdict():
    return FreshnessVerdict(
        FreshnessStatus.FRESH, "test approved", "test-v1",
        source="KIS_VTS_REST", tr_id="FHMIF10010000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        evidence_sha256="a" * 64,
    )


def test_fresh09_pending_cancel_or_partial_fill_without_fresh_verdict_stays_blocked():
    for state in ("CANCEL_PENDING", "PARTIALLY_FILLED", "LATE_FILL_PENDING"):
        router = _Router()
        gate = _RejectingGate()
        context = RiskRouterContext(
            account_snapshot=SimpleNamespace(total_balance=1000, realized_pnl=0, used_margin=0, free_margin=1000),
            position_source=SimpleNamespace(positions={}),
            order_router=router,
        )
        result = route_from_runtime_authoritative_sources(
            _command(), risk_gate=gate, context=context,
            allow_reduction=True, freshness_verdict=None,
        )
        assert not result.routed, state
        assert gate.calls == 0, state
        assert router.calls == 0, state


def test_fresh12_risk_gate_denial_means_no_router_call_even_when_fresh():
    router = _Router()
    gate = _RejectingGate()
    context = RiskRouterContext(
        account_snapshot=SimpleNamespace(total_balance=1000, realized_pnl=0, used_margin=0, free_margin=1000),
        position_source=SimpleNamespace(positions={}),
        order_router=router,
    )
    result = route_from_runtime_authoritative_sources(
        _command(), risk_gate=gate, context=context,
        freshness_verdict=_fresh_verdict(),
    )
    assert gate.calls == 1
    assert router.calls == 0
    assert not result.routed

def test_standard_order_router_blocks_direct_bypass_without_freshness_evidence():
    from contracts.types import BrokerOrderCommand
    from core.oms.order_router import OrderRouterError, StandardOrderRouter

    class Broker:
        def __init__(self):
            self.calls = 0

        def submit(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("broker must not be called")

    broker = Broker()
    router = StandardOrderRouter(order_state_machine=object(), broker_adapter=broker)
    command = BrokerOrderCommand(
        client_order_id="client-1", instrument_id="OPT-1", side="BUY",
        quantity=1, order_type="LIMIT", broker_symbol="A12345",
    )
    try:
        router.register_and_route(command, object())
    except OrderRouterError as exc:
        assert str(exc) == "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED"
    else:
        raise AssertionError("missing freshness verdict must be rejected")
    assert broker.calls == 0


def test_standard_order_router_rejects_wrong_contract_or_unhashed_fresh_verdict():
    from contracts.types import BrokerOrderCommand
    from core.oms.order_router import OrderRouterError, StandardOrderRouter

    class Broker:
        def submit(self, *args, **kwargs):
            raise AssertionError("broker must not be called")

    router = StandardOrderRouter(order_state_machine=object(), broker_adapter=Broker())
    command = BrokerOrderCommand(
        client_order_id="client-1", instrument_id="OPT-1", side="BUY",
        quantity=1, order_type="LIMIT", broker_symbol="A12345",
    )
    wrong = FreshnessVerdict(
        FreshnessStatus.FRESH, "test", "v1", source="KIS_VTS_REST",
        tr_id="H0IOASP0", environment="VIRTUAL", instrument_id="OTHER",
        symbol="A12345", evidence_sha256="a" * 64,
    )
    unhashed = FreshnessVerdict(
        FreshnessStatus.FRESH, "test", "v1", source="KIS_VTS_REST",
        tr_id="H0IOASP0", environment="VIRTUAL", instrument_id="OPT-1",
        symbol="A12345", evidence_sha256=None,
    )
    for verdict, expected in (
        (wrong, "MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH"),
        (unhashed, "MARKET_DATA_FRESHNESS_EVIDENCE_REQUIRED"),
    ):
        try:
            router.register_and_route(command, object(), freshness_verdict=verdict)
        except OrderRouterError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError("expected rejection: " + expected)

def test_standard_order_router_accepts_matching_fresh_verdict_and_does_not_forward_it_to_broker():
    from contracts.types import BrokerOrderCommand, BrokerOrderResponse
    from core.oms.order_router import StandardOrderRouter

    class FSM:
        def get(self, client_order_id):
            return object()

        def register_broker_order_command(self, command):
            pass

        def apply_ack(self, event):
            pass

    class Broker:
        def __init__(self):
            self.calls = 0
            self.kwargs = None

        def submit(self, command, **kwargs):
            self.calls += 1
            self.kwargs = kwargs
            return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="broker-1")

    broker = Broker()
    router = StandardOrderRouter(order_state_machine=FSM(), broker_adapter=broker)
    command = BrokerOrderCommand(
        client_order_id="client-1", instrument_id="OPT-1", side="BUY",
        quantity=1, order_type="LIMIT", broker_symbol="A12345",
    )
    verdict = FreshnessVerdict(
        FreshnessStatus.FRESH, "approved test evidence", "test-v1",
        source="KIS_VTS_REST", tr_id="FHMIF10010000",
        environment="VIRTUAL", instrument_id="OPT-1", symbol="A12345",
        source_instant=__import__("datetime").datetime(2026, 10, 15, 10, 15, tzinfo=__import__("datetime").timezone.utc),
        received_at=__import__("datetime").datetime(2026, 10, 15, 10, 15, tzinfo=__import__("datetime").timezone.utc),
        evidence_sha256="f" * 64,
    )
    response = router.register_and_route(command, object(), freshness_verdict=verdict)
    assert response.accepted
    assert broker.calls == 1
    assert broker.kwargs == {}
