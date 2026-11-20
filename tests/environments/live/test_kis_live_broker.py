from __future__ import annotations

import pytest

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from environments.live.broker.kis_live_broker import LiveBrokerAdapter


class _Idempotency:
    def __init__(self):
        self.calls = 0

    def reserve(self, _identity):
        self.calls += 1
        return True


class _Gate:
    def __init__(self):
        self.calls = 0

    def evaluate(self, *_args, **_kwargs):
        self.calls += 1
        return type("Verdict", (), {"allowed": True, "reason": None})()


class _Transport:
    def __init__(self):
        self.submissions = []

    def submit(self, command):
        self.submissions.append(command)
        raise AssertionError("unsupported live asset must not reach transport")


@pytest.mark.parametrize("asset_type", ["OPTION", "OPTIONS", None])
def test_live_broker_rejects_non_futures_before_reserving_or_gating(asset_type):
    idempotency = _Idempotency()
    gate = _Gate()
    transport = _Transport()
    adapter = LiveBrokerAdapter(
        transport=transport,
        gate=gate,
        policy=None,
        idempotency=idempotency,
        connected=True,
    )
    command = BrokerOrderCommand(
        client_order_id="synthetic-option-order",
        instrument_id="SYNTHETIC_CONTRACT:S2:CALL:20261112:500.0",
        side="BUY",
        quantity=1,
        order_type="LIMIT",
        broker_symbol="SYNTHETIC_CONTRACT:S2:CALL:20261112:500.0",
        asset_type=asset_type,
    )

    with pytest.raises(RuntimeError, match="LIVE_BROKER_FUTURES_ONLY"):
        adapter.submit(command, identity=None, account_age_seconds=0)

    assert idempotency.calls == 0
    assert gate.calls == 0
    assert transport.submissions == []


def test_live_broker_keeps_authoritative_futures_command_mapping():
    idempotency = _Idempotency()
    gate = _Gate()
    transport = _Transport()

    class _FuturesAdapter:
        def to_broker_command(self, command):
            from dataclasses import replace

            return replace(command, broker_symbol="1001FUT01")

    class _AcceptingTransport:
        def __init__(self):
            self.submissions = []

        def submit(self, command):
            self.submissions.append(command)
            return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True)

    transport = _AcceptingTransport()
    adapter = LiveBrokerAdapter(
        transport=transport,
        gate=gate,
        policy=None,
        idempotency=idempotency,
        futures_command_adapter=_FuturesAdapter(),
        connected=True,
    )
    command = BrokerOrderCommand(
        client_order_id="futures-order",
        instrument_id="KIS_FUTURES_MASTER:2001",
        side="BUY",
        quantity=1,
        order_type="LIMIT",
        broker_symbol=None,
        asset_type="FUTURES",
    )

    result = adapter.submit(command, identity=object(), account_age_seconds=0)

    assert result.accepted is True
    assert len(transport.submissions) == 1
    assert transport.submissions[0].broker_symbol == "1001FUT01"
    assert idempotency.calls == 1
    assert gate.calls == 1
