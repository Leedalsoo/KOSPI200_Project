from __future__ import annotations

import pytest

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.standard_registry import build_standard_strategy_registry


def test_prepare_reports_all_missing_required_sources_in_one_diagnostic() -> None:
    registry = build_standard_strategy_registry()
    context = StrategyContext(
        market_state=None,
        strategy_id="Strategy_3_StatArb",
        input=StrategyInput(
            data_status={
                "track3": "AVAILABLE",
                "source": "VirtualExchange.VMS+VirtualBroker.VSSF",
            }
        ),
    )

    with pytest.raises(ValueError) as raised:
        registry.prepare("Strategy_3_StatArb", "1.0", context)

    message = str(raised.value)
    assert message.startswith("STRATEGY_REQUIRED_SOURCE_UNAVAILABLE:Strategy_3_StatArb:")
    assert "common_analytics=STATUS_UNDECLARED" in message
    assert "authoritative_futures_identity=STATUS_UNDECLARED" in message
    assert "execution_totals=STATUS_UNDECLARED" in message
    assert "contract_multiplier=STATUS_UNDECLARED" in message
