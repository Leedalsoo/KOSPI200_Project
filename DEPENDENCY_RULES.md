## Allowed direction

interfaces → application

application → contracts + core

environments → contracts + core/domain public APIs

infrastructure → contracts

core → core/domain only

## Forbidden

- core → KIS

- core → VMS

- core → VSSF

- core → UI

- strategy → broker

- strategy → UI

- UI → environment implementation

- UI → KIS/VMS/VSSF

- environment implementation → private core internals

## Enforcement

Static checks must detect forbidden imports.

No compatibility import aliases are introduced merely to preserve old paths.

Reference Baseline imports are never copied unchanged without ownership review.