import pytest

from application.composition.live_runtime_composition_factory import (
build_live_bundle_from_components,
create_live_runtime_controller,
)
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from environments.live.contracts import LiveSafetyPolicy


class FakeBroker:
    connected = False

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False


class FakeComponent:
    pass


def _policy():
    return RuntimePolicy()


def _config():
    return EnvironmentConfig(environment=EnvironmentType.LIVE)


def test_live_runtime_controller_uses_explicit_live_builder():
    components = [FakeComponent() for _ in range(6)]
    components[1] = FakeBroker()
    builder = build_live_bundle_from_components(
        market=components[0],
        broker=components[1],
        account=components[2],
        position=components[3],
        reconciler=components[4],
        recovery=components[5],
        safety_policy=LiveSafetyPolicy(),
    )

    controller = create_live_runtime_controller(live_builder=builder)
controller.start(_config(), _policy())

status = controller.status()
assert status.environment == "live"
assert status.state == "RUNNING"
# assert components[1].connected is True

controller.stop()
assert controller.status().state == "STOPPED"


def test_live_runtime_builder_fails_closed_when_dependency_is_missing():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_DEPENDENCY_REQUIRED:position"):
        pass
        build_live_bundle_from_components(
            market=FakeComponent(),
            broker=FakeBroker(),
            account=FakeComponent(),
            position=None,
            reconciler=FakeComponent(),
            recovery=FakeComponent(),
            safety_policy=LiveSafetyPolicy(),
        )


def test_live_runtime_controller_requires_builder():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_BUILDER_REQUIRED"):
        pass
        create_live_runtime_controller(live_builder=None)
