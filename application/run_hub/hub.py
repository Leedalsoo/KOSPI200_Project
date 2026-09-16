from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from application.run_hub.contracts import RunContext, RunContextFactory


@dataclass
class RunSession:
    context: RunContext
    runtime_controller: Any
    bundle: Any
    strategy_hub: Any
    runtime_hub: Any
    ui_adapter: Any
    control_tower_hub: Any

    def adopt(self, session: RunSession) -> None:
        if self._active is not None:
            raise RuntimeError('RUN_ALREADY_ACTIVE')
        self._active = session

    def close(self) -> None:
        self.runtime_controller.stop()
        reset = getattr(self.strategy_hub, "reset", None)
        if callable(reset):
            reset()


class RunScenarioHub:
    """Owns creation, activation and disposal of one isolated run session."""

    def __init__(self, *, context_factory: RunContextFactory | None = None) -> None:
        self._context_factory = context_factory or RunContextFactory()
        self._active: RunSession | None = None

    @property
    def active(self) -> RunSession | None:
        return self._active

    def start(
        self,
        *,
        run_id: str,
        environment: str,
        scenario: str | None = None,
        historical_source: str | None = None,
        strategy_keys: tuple[tuple[str, str], ...] = (),
        initial_capital: float | None = None,
        replay_speed: float | None = None,
        session_factory: Callable[[RunContext], RunSession],
    ) -> RunSession:
        if self._active is not None:
            raise RuntimeError("RUN_ALREADY_ACTIVE")
        context = self._context_factory.create(
            run_id=run_id,
            environment=environment,
            scenario=scenario,
            historical_source=historical_source,
            strategy_keys=strategy_keys,
            initial_capital=initial_capital,
            replay_speed=replay_speed,
        )
        session = session_factory(context)
        if session.context is not context:
            raise RuntimeError("RUN_CONTEXT_SESSION_MISMATCH")
        self._active = session
        return session

    def adopt(self, session: RunSession) -> None:
        if self._active is not None:
            raise RuntimeError('RUN_ALREADY_ACTIVE')
        self._active = session

    def close(self) -> None:
        if self._active is None:
            return
        session = self._active
        self._active = None
        session.close()

    def restart(self, *, session_factory: Callable[[RunContext], RunSession]) -> RunSession:
        if self._active is None:
            raise RuntimeError("RUN_NOT_ACTIVE")
        old = self._active
        context = old.context
        self.close()
        return self.start(
            run_id=context.run_id,
            environment=context.environment,
            scenario=context.scenario,
            historical_source=context.historical_source,
            strategy_keys=context.strategy_keys,
            initial_capital=context.initial_capital,
            replay_speed=context.replay_speed,
            session_factory=session_factory,
        )

