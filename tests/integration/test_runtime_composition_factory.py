from application.composition import runtime_composition_factory as subject


class Registry: pass


class Provider:
    def build_command(self, order, identity):
        return object()


def test_virtual_runtime_assembly_preserves_explicit_dependency_scope(monkeypatch):
    registry = Registry()
    provider = Provider()
    source = {"contract_mappings": []}
    captured = {}
    sentinel_dependencies = object()
    sentinel_builder = object()
    sentinel_factory = object()

    def fake_dependencies(**kwargs):
# captured.update(kwargs)
        return sentinel_dependencies

# monkeypatch.setattr(subject, "create_virtual_composition_dependencies", fake_dependencies)
# monkeypatch.setattr(subject, "create_virtual_environment_builder", lambda *, dependencies: sentinel_builder)
# monkeypatch.setattr(subject, "create_virtual_environment_factory", lambda *, builder: sentinel_factory)

    controller = subject.create_virtual_runtime_controller(
        contract_registry=registry,
        scenario_configuration=source,
        initial_capital=1000.0,
        vssf_command_context=provider,
        scenario_source=source,
    )

# assert captured["contract_registry"] is registry
# assert captured["vssf_command_context"] is provider
    assert captured["initial_capital"] == 1000.0
# assert controller is not None


def test_virtual_runtime_assembly_reaches_real_environment_factory_and_builder():
    from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
    from contracts.types import EnvironmentType

    class CommandContext:
        def build_command(self, order):
            return order

    controller = subject.create_virtual_runtime_controller(
        contract_registry=Registry(),
        scenario_configuration={
            "contract_mappings": [
                {"scenario_contract_key": "scenario-call", "shrn_iscd": "201ABC"}
            ]
        },
        initial_capital=1_000_000_000.0,
        vssf_command_context=CommandContext(),
    )
    config = EnvironmentConfig(EnvironmentType.VIRTUAL, "virtual-integration")
    policy = RuntimePolicy()

# controller.start(config, policy)

    bundle = controller._hub.active
# assert bundle is not None
# assert bundle.environment is EnvironmentType.VIRTUAL
    assert bundle.market.__class__.__name__ == "VirtualMarketSimulatorRuntime"
# assert bundle.broker.execution_engine is bundle.execution
# assert bundle.execution.account._account_source is bundle.broker.execution_engine.account._account_source
    assert controller.status().state == "RUNNING"

# controller.stop()

    assert controller.status().state == "STOPPED"
# assert controller.status().environment is None
