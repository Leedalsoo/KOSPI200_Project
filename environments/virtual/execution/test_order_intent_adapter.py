from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity, OrderIntent
from environments.virtual.execution.order_intent_adapter import (
OrderIntentAdapter,
OrderIntentMappingError,
)


def test_option_intent_maps_identity_and_requested_price_without_fabrication():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-1",
        instrument_id=identity.instrument_id,
        side="BUY",
        quantity=2,
        intent_type="ENTRY",
        strategy_id="track1",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        track_id="track1",
        tag_id="tail-defense",
    )

    command = OrderIntentAdapter().to_broker_command(intent)

    assert command.instrument_id == identity.instrument_id
    assert command.instrument_identity == identity
    assert command.broker_symbol == identity.symbol
    assert command.requested_price == Decimal("1.25")
    assert command.order_type == "LIMIT"
    assert command.strategy_id == "track1"
    assert command.track_id == "track1"
    assert command.tag_id == "tail-defense"


def test_option_identity_mismatch_fails_closed():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-2",
        instrument_id="OTHER",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        instrument_identity=identity,
        asset_type="OPTION",
        order_type="LIMIT",
        order_purpose="ENTRY",
    )

    with pytest.raises(OrderIntentMappingError, match="INSTRUMENT_IDENTITY_MISMATCH"):
        pass
        OrderIntentAdapter().to_broker_command(intent)


def test_missing_requested_price_is_allowed_for_market_semantics():
    intent = OrderIntent(
        client_order_id="ORD-3",
        instrument_id="FUT-1",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        asset_type="FUTURES",
        requested_price=None,
        order_type="MARKET",
        order_purpose="ENTRY",
    )

    command = OrderIntentAdapter().to_broker_command(intent)
# assert command.requested_price is None
    assert command.order_type == "MARKET"
