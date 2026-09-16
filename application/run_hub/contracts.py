from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RunContext:
    """Immutable identity/config boundary for one repeatable test or paper run."""

    run_id: str
    environment: str
    scenario: str | None = None
    historical_source: str | None = None
    strategy_keys: tuple[tuple[str, str], ...] = ()
    initial_capital: float | None = None
    replay_speed: float | None = None


class RunContextFactory:
    def create(self, *, run_id: str, environment: str, scenario: str | None = None,
               historical_source: str | None = None,
               strategy_keys: tuple[tuple[str, str], ...] = (),
               initial_capital: float | None = None,
               replay_speed: float | None = None) -> RunContext:
        if not run_id.strip():
            raise ValueError("RUN_ID_REQUIRED")
        if not environment.strip():
            raise ValueError("RUN_ENVIRONMENT_REQUIRED")
        return RunContext(run_id=run_id, environment=environment, scenario=scenario,
                          historical_source=historical_source, strategy_keys=strategy_keys,
                          initial_capital=initial_capital, replay_speed=replay_speed)
