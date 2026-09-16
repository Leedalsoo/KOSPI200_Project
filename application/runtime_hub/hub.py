from __future__ import annotations

from typing import Any


class RuntimeHub:
    """Stable application boundary for a single runtime execution loop."""

    def __init__(self, loop: Any) -> None:
        self._loop = loop

    @property
    def loop(self) -> Any:
        return self._loop

    @property
    def last_result(self) -> Any | None:
        return getattr(self._loop, "last_result", None)

    def on_tick(self, tick: Any) -> Any:
        return self._loop.on_tick(tick)

    def reset(self) -> None:
        reset = getattr(self._loop, "reset", None)
        if callable(reset):
            reset()
