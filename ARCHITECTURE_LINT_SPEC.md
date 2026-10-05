# Architecture Lint Specification

Project200 executable dependency baseline.

## Layer rules

- `contracts/` may depend only on the Python standard library and other `contracts/` modules.
- `core/` may depend on `contracts/` and other `core/` modules, but not `application/`, `infrastructure/`, or `interfaces/`.
- `core/strategy/` follows the same rule; strategies must not import adapters or orchestration layers.
- `application/` may compose `contracts/`, `core/`, `infrastructure/`, and approved interfaces, but strategy logic remains in `core/strategy/`.
- `infrastructure/` must not import `application/` orchestration modules.

## Forbidden dependency directions

- core → KIS / VMS / VSSF
- core → UI
- strategy → broker / UI
- UI → environment implementation / KIS / VMS / VSSF
- environment implementation → private core internals

Static checks must detect forbidden imports. Compatibility import aliases are not introduced merely to preserve old paths.

## Runtime boundary rules

- Strategy-specific execution/multi-leg resolution is supplied through `ExecutionMultiLegResolverRegistry` rather than a central strategy-id if/elif chain.
- Calendar facts are supplied through `MarketCalendarHub` / `MarketCalendarSnapshot`; strategy-specific calendar sources must not recalculate the same trading-day boundaries in the standard runtime path.
- Runtime orchestration belongs to `application/`; environment-neutral runtime state belongs to core/runtime; external synchronization crosses standard contracts.
- The Control Tower UI uses runtime command/status contracts and does not inspect environment-internal objects directly.
- No main entrypoint may directly instantiate a specific VMS/VSSF/KIS implementation; environment assembly is performed through the application composition/environment boundary.

## Environment bundle boundary

An environment is assembled as a coherent bundle rather than by replacing only an endpoint:

- market data
- clock/time policy
- broker
- account
- execution
- runtime policy

High-Speed uses deterministic/replayable input and accelerated time/execution policy. Virtual Trading may use real-time or simulated time. Paper and Live use real clock policy. Live additionally requires credential isolation, kill-switch and execution safety/reconciliation controls.

## Market time and data boundary

Source → transport → environment adapter → `CanonicalMarketTick` → market state → Standard Core.

Core never receives raw KIS/VMS/VSSF payloads. Data validity states such as UNAVAILABLE, STALE, PARTIAL and SYNTHETIC remain distinguishable. Synthetic input is permitted only when the active environment explicitly declares it.

Market timestamp and execution timestamp remain distinct. Strategy/Core does not directly call wall-clock APIs as a source of business time; clock policy is injected through contracts.

## Collector evidence rule

A daily collector manifest may not claim `websocket=NOT_STARTED` when a non-empty `kis_vts_websocket*.jsonl` raw evidence file exists in the same date partition. Finalization must reconcile manifest state with filesystem evidence.
