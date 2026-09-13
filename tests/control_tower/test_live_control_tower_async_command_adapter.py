import asyncio
from types import SimpleNamespace

import pytest

from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from interfaces.control_tower.contracts import LiveLifecycleCommand
from interfaces.control_tower.live_runtime_api import LiveControlTowerRuntimeAPI


def live_command(environment=EnvironmentType.LIVE):
    return LiveLifecycleCommand(
        EnvironmentConfig(environment=environment, name="live"),
        RuntimePolicy(),
        "HTS-1",
        "RECOVERY-1",
    )


class FakeController:
    def __init__(self):
        self.calls = []

    def start(self, config, policy):
        self.calls.append(("controller.start", config, policy))

    def stop(self):
        self.calls.append(("controller.stop",))

    def status(self):
        return SimpleNamespace(environment="live", state="STOPPED", connected=False)


class FakeCoordinator:
    def __init__(self):
        self.runtime_controller = FakeController()
        self.technical_state = None
        self.events = []

    async def start(self, config, policy, *, hts_id, recovery_query):
        self.events.append(("start", config, policy, hts_id, recovery_query))
        return "RECOVERED"

    async def stop(self):
        self.events.append(("stop",))


def test_live_async_start_delegates_canonical_command_to_coordinator():
    coordinator = FakeCoordinator()
    api = LiveControlTowerRuntimeAPI(coordinator)
    result = asyncio.run(api.start_live(live_command()))
    assert result == "RECOVERED"
    assert coordinator.events[0][0] == "start"
    assert coordinator.events[0][3:] == ("HTS-1", "RECOVERY-1")
    assert coordinator.runtime_controller.calls == []


def test_live_async_stop_delegates_to_coordinator():
    coordinator = FakeCoordinator()
    api = LiveControlTowerRuntimeAPI(coordinator)
    asyncio.run(api.stop_live())
    assert coordinator.events == [("stop",)]


def test_live_async_restart_is_stop_then_start():
    coordinator = FakeCoordinator()
    api = LiveControlTowerRuntimeAPI(coordinator)
    result = asyncio.run(api.restart_live(live_command()))
    assert result == "RECOVERED"
    assert [event[0] for event in coordinator.events] == ["stop", "start"]


def test_live_sync_commands_are_never_available():
    api = LiveControlTowerRuntimeAPI(FakeCoordinator())
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.start("C", "P")
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.stop()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.restart("C", "P")


def test_live_command_requires_live_environment():
    api = LiveControlTowerRuntimeAPI(FakeCoordinator())
    with pytest.raises(ValueError, match="LIVE_RUNTIME_COMMAND_ENVIRONMENT_REQUIRED"):
        asyncio.run(api.start_live(live_command(EnvironmentType.PAPER)))


def test_live_command_requires_typed_command():
    api = LiveControlTowerRuntimeAPI(FakeCoordinator())
    with pytest.raises(TypeError, match="LIVE_RUNTIME_COMMAND_REQUIRED"):
        asyncio.run(api.start_live("bad-command"))


def test_concurrent_live_commands_are_serialized():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        events = []

        class Coordinator(FakeCoordinator):
            async def start(self, config, policy, *, hts_id, recovery_query):
                events.append("start-enter")
                entered.set()
                await release.wait()
                events.append("start-exit")
                return "OK"

            async def stop(self):
                events.append("stop")

        api = LiveControlTowerRuntimeAPI(Coordinator())
        first = asyncio.create_task(api.start_live(live_command()))
        await entered.wait()
        second = asyncio.create_task(api.stop_live())
        await asyncio.sleep(0)
        assert events == ["start-enter"]
        release.set()
        await asyncio.gather(first, second)
        assert events == ["start-enter", "start-exit", "stop"]

    asyncio.run(scenario())
