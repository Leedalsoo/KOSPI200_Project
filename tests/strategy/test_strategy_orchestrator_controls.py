from decimal import Decimal

from core.strategy.contracts import Signal
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def _signal(tag: str) -> Signal:
    return Signal(
        strategy_id="test_strategy",
        direction="BUY",
        confidence=1.0,
        reason=tag,
        execution_proposal=StrategyExecutionProposal(
            proposed_quantity=1,
            asset_type="OPTION",
            side="BUY",
            track_id="test_strategy",
            tag_id=tag,
            strike=Decimal("100"),
        ),
    )


class _Registry:
    pass


def _orchestrator() -> StrategyOrchestrator:
    return StrategyOrchestrator(_Registry(), (("test_strategy", "1.0"),))


def test_entry_control_blocks_entry_only():
    hub = _orchestrator()
    hub.set_entry_enabled("test_strategy", "1.0", False)
    result = hub._apply_lifecycle_controls((_signal("TEST_ENTRY"), _signal("TEST_EXIT")))
    assert [signal.reason for signal in result] == ["TEST_EXIT"]


def test_exit_control_blocks_exit_only():
    hub = _orchestrator()
    hub.set_exit_enabled("test_strategy", "1.0", False)
    result = hub._apply_lifecycle_controls((_signal("TEST_ENTRY"), _signal("TEST_EXIT")))
    assert [signal.reason for signal in result] == ["TEST_ENTRY"]


def test_strategy_control_readback_tracks_all_three_switches():
    hub = _orchestrator()
    hub.set_enabled("test_strategy", "1.0", False)
    hub.set_entry_enabled("test_strategy", "1.0", False)
    hub.set_exit_enabled("test_strategy", "1.0", True)
    assert hub.is_enabled("test_strategy", "1.0") is False
    assert hub.is_entry_enabled("test_strategy", "1.0") is False
    assert hub.is_exit_enabled("test_strategy", "1.0") is True
