from datetime import datetime

import pytest

from contracts.types import CanonicalMarketTick
from core.oms.canonical_order_command_adapter import (
CanonicalOrderCommandAdapter,
CanonicalOrderCommandValidationError,
)
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from shared.contracts.canonical import (
CanonicalAssetType,
CanonicalOptionType,
CanonicalOrderSide,
CanonicalStrategySignal,
)


def runtime() -> RuntimeExecutionContext:
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=42,
    )
    return RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=7)


def option_signal(instrument_id="OPT-AUTH-1", symbol="KOSPI200", expiry="20260910"):
    return CanonicalStrategySignal(
        signal_id="SIG-42-Track4-7",
        track_id="Track4",
        asset_type=CanonicalAssetType.OPTION,
        side=CanonicalOrderSide.BUY,
        qty=2,
        price=3.5,
        option_type=CanonicalOptionType.CALL,
        strike=350.0,
        tag_id="T4",
        timestamp="2026-09-06T09:00:01",
        symbol=symbol,
        expiry=expiry,
        instrument_id=instrument_id,
    )


def test_command_uses_runtime_authoritative_client_order_id_and_preserves_identity():
    command = CanonicalOrderCommandAdapter().create(option_signal(), runtime())

    assert command.client_order_id == "ORD-T42-Track4-7"
    assert command.track_id == "Track4"
    assert option_signal().instrument_id == "OPT-AUTH-1"
    assert command.asset_type == CanonicalAssetType.OPTION
    assert command.side == CanonicalOrderSide.BUY
    assert command.qty == 2
    assert command.price == 3.5
    assert command.symbol == "KOSPI200"
    assert command.expiry == "20260910"
    assert command.option_type == CanonicalOptionType.CALL
    assert command.strike == 350.0
    assert command.tag_id == "T4"


def test_missing_authoritative_instrument_id_fails_closed():
    with pytest.raises(CanonicalOrderCommandValidationError, match="AUTHORITATIVE_INSTRUMENT_ID_REQUIRED"):
        CanonicalOrderCommandAdapter().create(option_signal(instrument_id=""), runtime())


def test_option_identity_defaults_are_not_used_as_fallbacks():
    with pytest.raises(CanonicalOrderCommandValidationError, match="OPTION_SYMBOL_EXPIRY_REQUIRED"):
        CanonicalOrderCommandAdapter().create(option_signal(symbol="", expiry=""), runtime())


def test_command_id_does_not_use_signal_id_or_tick_seq_fallback_from_adapter():
    signal = option_signal()
    signal = CanonicalStrategySignal(**{**signal.__dict__, "signal_id": "UNRELATED"})
    command = CanonicalOrderCommandAdapter().create(signal, runtime())
    assert command.client_order_id == "ORD-T42-Track4-7"
