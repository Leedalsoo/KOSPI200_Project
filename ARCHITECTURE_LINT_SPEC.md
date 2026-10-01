# Architecture Lint Specification

Project200 executable dependency baseline.

## Layer rules

- `contracts/` may depend only on the Python standard library and other `contracts/` modules.
- `core/` may depend on `contracts/` and other `core/` modules, but not `application/`, `infrastructure/`, or `interfaces/`.
- `core/strategy/` follows the same rule; strategies must not import adapters or orchestration layers.
- `application/` may compose `contracts/`, `core/`, `infrastructure/`, and approved interfaces, but strategy logic remains in `core/strategy/`.
- `infrastructure/` must not import `application/` orchestration modules.

## Runtime boundary rules

- Strategy-specific execution/multi-leg resolution is supplied through `ExecutionMultiLegResolverRegistry` rather than a central strategy-id if/elif chain.
- Calendar facts are supplied through `MarketCalendarHub` / `MarketCalendarSnapshot`; strategy-specific calendar sources must not recalculate the same trading-day boundaries in the standard runtime path.

## Collector evidence rule

A daily collector manifest may not claim `websocket=NOT_STARTED` when a non-empty `kis_vts_websocket*.jsonl` raw evidence file exists in the same date partition. Finalization must reconcile manifest state with filesystem evidence.
