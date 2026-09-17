import pytest

from core.runtime.runtime_execution_context import RuntimeExecutionContext


def test_runtime_context_derives_stable_ids_from_authoritative_sequences():
    context = RuntimeExecutionContext(tick_sequence=42, local_sequence=3)

    assert context.signal_id("TRACK1") == "SIG-42-TRACK1-3"
    assert context.client_order_id("TRACK1") == "ORD-T42-TRACK1-3"


@pytest.mark.parametrize("tick_sequence,local_sequence", [(0, 1), (-1, 1), (1, 0), (1, -1)])
def test_runtime_context_fails_closed_for_missing_or_invalid_sequences(
    tick_sequence,
    local_sequence,
):
    with pytest.raises(ValueError):
        RuntimeExecutionContext(
            tick_sequence=tick_sequence,
            local_sequence=local_sequence,
        )
