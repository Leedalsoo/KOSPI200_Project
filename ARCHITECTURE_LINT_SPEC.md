Static gate rules:

- core must not import application/environments/infrastructure/interfaces

- strategy must not import broker/UI implementations

- contracts must not import concrete environment implementations

- interfaces must not import concrete broker/VMS/VSSF/KIS modules

- legacy paths are forbidden from new runtime imports

Implementation approach:

AST import scanner in tests/architecture/test_dependency_rules.py.

Forbidden imports fail CI.

This is a design gate specification; execution requires the physical Python workspace.