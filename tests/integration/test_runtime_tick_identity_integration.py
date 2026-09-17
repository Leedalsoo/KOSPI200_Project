from datetime import datetime

import pytest

from contracts.types import CanonicalMarketTick
from core.runtime.runtime_execution_context import RuntimeExecutionContext


def test_source_sequence_is_the_authoritative_runtime_tick_identity():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=42,
    )

    context = RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=3)

    assert context.signal_id("Track4") == "SIG-42-Track4-3"
    assert context.client_order_id("Track4") == "ORD-T42-Track4-3"


def test_missing_source_sequence_fails_closed_before_identity_derivation():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=None,
    )

    with pytest.raises((TypeError, ValueError)):
        RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=1)


def test_legacy_seq_id_must_not_silently_replace_missing_source_sequence():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        seq_id=99,
        source_sequence=None,
    )

    with pytest.raises((TypeError, ValueError)):
        RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=1)
