"""Test Virtual Execution Fail Closed — test specification.

import pytest
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
def test_missing_authoritative_execution_adapter_fails_closed() -> None:
engine = VirtualExecutionEngine(position=object(), account=object())
with pytest.raises(
RuntimeError,
match="AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED",
):
engine.execute(object())
"""
