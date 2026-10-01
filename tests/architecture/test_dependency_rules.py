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
