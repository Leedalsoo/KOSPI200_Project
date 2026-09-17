from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.oms.option_identity_resolver import OptionIdentityResolver
from core.oms.order_intent_factory import (
OrderIntentExecutionInput,
OrderIntentFactory,
OrderIntentValidationError,
)
from core.strategy.contracts import Signal


def identity():
    return OptionInstrumentIdentity(
        instrument_id="OPT-202609-C-700",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )


def test_option_signal_resolves_identity_and_preserves_execution_semantics():
    signal = Signal(
        strategy_id="track1",
        direction="LONG",
        confidence=0.9,
        reason="test",
        instrument_identity=identity(),
        option_type_override="CALL",
        strike_override=Decimal("700"),
    )
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-1",
        quantity=2,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="track1",
        tag_id="tail-defense",
    )

    result = OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)

    assert result.side == "BUY"
    assert result.quantity == 2
    assert result.requested_price == Decimal("1.25")
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.instrument_identity.option_type == "CALL"
    assert result.instrument_identity.strike == Decimal("700")
    assert result.instrument_id == "OPT-202609-C-700"


def test_contract_changing_override_fails_closed():
    signal = Signal(
        strategy_id="track1",
        direction="LONG",
        confidence=0.9,
        reason="test",
        instrument_identity=identity(),
        strike_override=Decimal("695"),
    )
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-override",
        quantity=1,
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
    )
    with pytest.raises(ValueError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)


def test_flat_signal_is_not_executable():
    signal = Signal(strategy_id="track1", direction="FLAT", confidence=0.1, reason="none")
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-2",
        quantity=1,
        requested_price=None,
        order_type="MARKET",
        order_purpose="EXIT",
        asset_type="OPTION",
    )
    with pytest.raises(OrderIntentValidationError, match="ORDER_SIDE_REQUIRED"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)


def test_missing_option_identity_fails_closed():
    signal = Signal(strategy_id="track1", direction="LONG", confidence=0.8, reason="test")
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-3",
        quantity=1,
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
    )
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)
