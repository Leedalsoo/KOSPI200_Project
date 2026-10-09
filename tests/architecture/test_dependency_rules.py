from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _python_files(directory: str):
    return (ROOT / directory).rglob("*.py")


def test_contracts_do_not_depend_on_runtime_layers():
    forbidden = ("application", "core", "infrastructure", "interfaces")
    violations = []
    for path in _python_files("contracts"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Forbidden contracts dependency:\n" + "\n".join(sorted(violations))


def test_core_does_not_depend_on_outer_layers():
    forbidden = ("application", "infrastructure", "interfaces")
    violations = []
    for path in _python_files("core"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Forbidden core dependency:\n" + "\n".join(sorted(violations))


def test_strategy_plugins_do_not_import_adapters_or_orchestration():
    forbidden = ("application", "infrastructure", "interfaces")
    violations = []
    for path in _python_files("core/strategy"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Forbidden strategy dependency:\n" + "\n".join(sorted(violations))


def test_infrastructure_does_not_depend_on_application_orchestration():
    violations = []
    for path in _python_files("infrastructure"):
        for module in _imports(path):
            if module.startswith("application"):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Forbidden infrastructure dependency:\n" + "\n".join(sorted(violations))


def test_execution_resolver_registry_exists_and_has_no_strategy_if_chain():
    path = ROOT / "application/composition/execution_multi_leg_resolver_registry.py"
    text = path.read_text(encoding="utf-8")
    assert "class ExecutionMultiLegResolverRegistry" in text
    assert "if strategy_id ==" not in text
    assert "def register" in text and "def resolve" in text


def test_project_gate_runtime_evidence_workflow_uses_existing_probe():
    workflow = (ROOT / ".github/workflows/project200-gate.yml").read_text(encoding="utf-8")
    probe = ROOT / "verification/runtime_evidence.py"
    assert probe.is_file()
    assert "run: python verification/runtime_evidence.py" in workflow
    assert "project200_runtime_evidence_probe.py" not in workflow
    assert "continue-on-error: true" in workflow
    assert "deterministic-gate" in workflow


def test_interfaces_do_not_depend_on_environment_or_infrastructure_adapters():
    forbidden = ("environments", "infrastructure")
    violations = []
    for path in _python_files("interfaces"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Forbidden interfaces dependency:\n" + "\n".join(sorted(violations))


def test_runtime_yaml_parser_is_declared_as_a_project_dependency():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert any(item.lower().startswith("pyyaml>=") for item in dependencies)
