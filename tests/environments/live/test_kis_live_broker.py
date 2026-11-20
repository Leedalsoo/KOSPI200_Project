from __future__ import annotations

from decimal import Decimal

import pytest

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, OptionInstrumentIdentity
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
        raise AssertionError("unexpected transport submission")


def _adapter_for_rejection():
    idempotency = _Idempotency()
    gate = _Gate()
    transport = _Transport()
    adapter = LiveBrokerAdapter(
        transport=transport, gate=gate, policy=None,
        idempotency=idempotency, connected=True,
    )
    return adapter, idempotency, gate, transport


def _assert_no_side_effects(idempotency, gate, transport):
    assert idempotency.calls == 0
    assert gate.calls == 0
    assert transport.submissions == []


@pytest.mark.parametrize("asset_type", ["OPTION", "OPTIONS", None])
def test_live_broker_rejects_non_futures_before_reserving_or_gating(asset_type):
    adapter, idempotency, gate, transport = _adapter_for_rejection()
    synthetic_id = "SYNTHETIC_CONTRACT:S2:CALL:20261112:500.0"
    command = BrokerOrderCommand(
        client_order_id="synthetic-option-order", instrument_id=synthetic_id,
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol=synthetic_id,
        asset_type=asset_type,
        instrument_identity=OptionInstrumentIdentity(
            instrument_id=synthetic_id, symbol=synthetic_id, expiry="20261112",
            option_type="CALL", strike=Decimal("500"),
            contract_multiplier=Decimal("250000"),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        ),
    )
    with pytest.raises(RuntimeError, match="LIVE_BROKER_FUTURES_ONLY"):
        adapter.submit(command, identity=None, account_age_seconds=0)
    _assert_no_side_effects(idempotency, gate, transport)


def test_live_broker_rejects_option_identity_mislabeled_as_futures_before_side_effects():
    adapter, idempotency, gate, transport = _adapter_for_rejection()
    synthetic_id = "SYNTHETIC_CONTRACT:S2:CALL:20261112:500.0"
    command = BrokerOrderCommand(
        client_order_id="mislabelled-option", instrument_id=synthetic_id,
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol=synthetic_id,
        asset_type="FUTURES",
        instrument_identity=OptionInstrumentIdentity(
            instrument_id=synthetic_id, symbol=synthetic_id, expiry="20261112",
            option_type="CALL", strike=Decimal("500"),
            contract_multiplier=Decimal("250000"),
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
        ),
    )
    with pytest.raises(RuntimeError, match="LIVE_BROKER_FUTURES_IDENTITY_REQUIRED"):
        adapter.submit(command, identity=None, account_age_seconds=0)
    _assert_no_side_effects(idempotency, gate, transport)


def test_live_broker_rejects_synthetic_futures_identity_before_side_effects():
    adapter, idempotency, gate, transport = _adapter_for_rejection()
    instrument_id = "SYNTHETIC_FUTURES:KOSPI200"
    command = BrokerOrderCommand(
        client_order_id="synthetic-futures", instrument_id=instrument_id,
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol=instrument_id,
        asset_type="FUTURES",
        instrument_identity=FuturesInstrumentIdentity(
            instrument_id=instrument_id, symbol=instrument_id,
            product_type=FuturesProductType.MINI,
            contract_multiplier=Decimal("50000"),
            identity_source="SYNTHETIC:VALIDATION_ONLY",
        ),
    )
    with pytest.raises(RuntimeError, match="LIVE_BROKER_FUTURES_IDENTITY_NOT_AUTHORITATIVE"):
        adapter.submit(command, identity=None, account_age_seconds=0)
    _assert_no_side_effects(idempotency, gate, transport)


def test_live_broker_rejects_futures_identity_instrument_mismatch_before_side_effects():
    adapter, idempotency, gate, transport = _adapter_for_rejection()
    command = BrokerOrderCommand(
        client_order_id="mismatched-futures", instrument_id="KIS-FUTURES-A",
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol="KIS-FUTURES-A",
        asset_type="FUTURES",
        instrument_identity=FuturesInstrumentIdentity(
            instrument_id="KIS-FUTURES-B", symbol="KIS-FUTURES-B",
            product_type=FuturesProductType.MINI,
            contract_multiplier=Decimal("50000"),
            identity_source="KIS_FUTURES_MASTER",
        ),
    )
    with pytest.raises(RuntimeError, match="LIVE_BROKER_FUTURES_IDENTITY_MISMATCH"):
        adapter.submit(command, identity=None, account_age_seconds=0)
    _assert_no_side_effects(idempotency, gate, transport)


def test_live_broker_keeps_authoritative_futures_command_mapping():
    idempotency = _Idempotency()
    gate = _Gate()

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
        transport=transport, gate=gate, policy=None, idempotency=idempotency,
        futures_command_adapter=_FuturesAdapter(), connected=True,
    )
    instrument_id = "KIS-FUTURES-2001"
    identity = FuturesInstrumentIdentity(
        instrument_id=instrument_id, symbol=instrument_id,
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source="KIS_FUTURES_MASTER",
    )
    command = BrokerOrderCommand(
        client_order_id="futures-order", instrument_id=instrument_id,
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol=None,
        asset_type="FUTURES", instrument_identity=identity,
    )
    result = adapter.submit(command, identity=object(), account_age_seconds=0)
    assert result.accepted is True
    assert len(transport.submissions) == 1
    assert transport.submissions[0].broker_symbol == "1001FUT01"
    assert idempotency.calls == 1
    assert gate.calls == 1
