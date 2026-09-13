"""Async Control Tower boundary for the authoritative Live lifecycle coordinator."""
from __future__ import annotations

import asyncio

from application.environment_hub.contracts import EnvironmentType
from interfaces.control_tower.contracts import LiveLifecycleCommand
from interfaces.control_tower.runtime_api import ControlTowerRuntimeAPI


class LiveControlTowerRuntimeAPI(ControlTowerRuntimeAPI):
    """Serialize Live lifecycle commands through one coordinator instance."""

    def __init__(self, lifecycle_coordinator):
        if lifecycle_coordinator is None:
            raise ValueError("LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED")
        controller = lifecycle_coordinator.runtime_controller
        super().__init__(controller, lifecycle_status_source=lifecycle_coordinator)
        self._lifecycle_coordinator = lifecycle_coordinator
        self._command_lock = asyncio.Lock()

    def start(self, *args, **kwargs):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def stop(self):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def restart(self, *args, **kwargs):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def _validate_live_command(self, command: LiveLifecycleCommand) -> None:
        if not isinstance(command, LiveLifecycleCommand):
            raise TypeError("LIVE_RUNTIME_COMMAND_REQUIRED")
        if command.config.environment is not EnvironmentType.LIVE:
            raise ValueError("LIVE_RUNTIME_COMMAND_ENVIRONMENT_REQUIRED")

    async def start_live(self, command: LiveLifecycleCommand):
        self._validate_live_command(command)
        async with self._command_lock:
            return await self._lifecycle_coordinator.start(
                command.config,
                command.policy,
                hts_id=command.hts_id,
                recovery_query=command.recovery_query,
            )

    async def stop_live(self) -> None:
        async with self._command_lock:
            await self._lifecycle_coordinator.stop()

    async def restart_live(self, command: LiveLifecycleCommand):
        self._validate_live_command(command)
        async with self._command_lock:
            await self._lifecycle_coordinator.stop()
            return await self._lifecycle_coordinator.start(
                command.config,
                command.policy,
                hts_id=command.hts_id,
                recovery_query=command.recovery_query,
            )
