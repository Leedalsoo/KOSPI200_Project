from __future__ import annotations

from typing import Any


class ControlTowerHub:
    """Stable read/command facade consumed by the Control Tower UI/API."""

    def __init__(self, *, runtime_controller: Any, ui_adapter: Any, strategy_hub: Any | None = None, run_context: Any | None = None) -> None:
        self._runtime_controller = runtime_controller
        self._ui_adapter = ui_adapter
        self._strategy_hub = strategy_hub
        self._run_context = run_context

    def status(self) -> dict[str, Any]:
        return self._ui_adapter.get_summary()

    def environment(self, tab_id: str) -> dict[str, Any]:
        return self._ui_adapter.get_tab_detail(tab_id)

    def command(self, command: str) -> dict[str, Any]:
        return self._ui_adapter.handle_command(command)

    @property
    def runtime_controller(self) -> Any:
        return self._runtime_controller

    @property
    def strategy_hub(self) -> Any | None:
        return self._strategy_hub

    @property
    def run_context(self) -> Any | None:
        return self._run_context
