# Grouped Execution and Fill-State Contract

Status: Phase 1 design contract; implementation pending.
Scope: Strategy 1?? entry execution, terminal exits, and authoritative fill/position reconciliation.
Safety: Virtual Execution only; no KIS Live orders.

## 1. Existing contract reuse

- `StrategyExecutionPlan` remains the single public decision output and has exactly one execution shape: `SINGLE_ORDER` or `MULTI_LEG`.
- `MultiLegExecutionPlan` remains the logical leg collection. `ExecutionLeg` describes the intended leg, not broker atomicity or fill completion.
- `OrderIntent` / `BrokerOrderCommand` carry the per-order routing identity. `ExecutionReport` carries execution outcome. `PositionLotStore` / authoritative Position Read Model is the source for currently open quantity.
- Additive fields are preferred; do not fork parallel plan/report/position contracts without evidence that the current types cannot represent the requirement.

## 2. Identity and provenance

| Field | Contract |
|---|---|
| `run_id` | One isolated runtime/replay run; never reuse state across runs. |
| `strategy_id` | Strategy owner; preserve the canonical registered ID. |
| `group_id` | Stable ID for one logical position lifecycle, shared by its entry legs and later exits. Never reuse for a new lifecycle. |
| `evaluation_id` | Identifies one strategy evaluation against one authoritative input snapshot. Replaying the same evaluation must resolve to the same execution intent identity. |
| `exit_batch_id` | Identifies one terminal-close decision for one `group_id`. A duplicate evaluation/retry of the same terminal decision reuses it; a genuinely new terminal decision must not silently merge into an unrelated batch. |
| `leg_id` | Stable semantic role within the group (e.g. `put`, `call`, `futures_hedge`), unique within the plan. |
| `client_order_id` / idempotency key | Deterministic for one logical order intent, including run, group, batch/evaluation, leg, instrument identity, side, quantity and authoritative position version/remaining-quantity revision where applicable. Same intent retry reuses the key; changed residual quantity or a new position revision produces a new intent key. |
| `execution_id` | Authoritative execution/fill identity; duplicate execution IDs must not be applied twice. Conflicting duplicate payloads fail reconciliation. |

`group_id` is not the same as `exit_batch_id`: one logical position can have an entry group and one or more explicitly tracked close attempts/batches while preserving a single lifecycle provenance. If current fields cannot carry these values, extend existing dataclasses additively and preserve backward compatibility for single-order callers.

## 3. Position and close quantity authority

1. The strategy signal decides *whether* a strategy-specific terminal condition occurred; it does not supply authoritative open quantity.
2. Resolve each close leg from the authoritative open-position/lot read model for the same `run_id`, `strategy_id`, `group_id`, instrument identity and position role. Use the exact canonical instrument identity, including exact option expiry.
3. Close quantity equals the actual remaining open quantity for that position lot/leg at the read-model version used by the evaluation. Do not use fixed entry quantity, requested quantity, order's `ExecutionReport.remaining_quantity`, or a strategy's cached quantity as a substitute for open position remaining quantity.
4. Close side is the side required to offset the actual open lot. Exclude zero-remaining/closed lots. Never invent missing legs or tradable instruments; reference-only indices are not order legs.
5. Missing, stale, contradictory, or unresolvable position provenance means `BLOCKED` / `RECONCILIATION_REQUIRED`; do not guess quantities or sides.
6. A partial close only schedules the authoritative residual. Already closed quantity must not be re-submitted.

## 4. Group-wide Risk preflight and submission

1. Materialize and validate the entire required plan before submitting any leg: non-empty unique leg IDs, resolved authoritative instrument identity, valid side/positive quantity, group consistency, quote/freshness and required provenance.
2. Evaluate all required legs as one group against a consistent account/position snapshot and include aggregate group exposure, not only independent per-leg checks. Record each leg result plus one group-level outcome.
3. If any required leg fails preflight or required evidence is missing, submit none of the group's legs; record `PREFLIGHT_REJECTED` or `BLOCKED` and preserve the reason.
4. Once preflight passes, broker submissions may still be sequential and are not atomic. If submission, live revalidation, or a later leg fails after earlier legs have been accepted/filled, do not claim rollback: retain every order/fill result and mark the group `PARTIAL`, `BLOCKED`, or `RECONCILIATION_REQUIRED` as applicable.
5. Broker acceptance/routing is not a fill. Only an authoritative `ExecutionReport` and reconciled position state update fill/closed state.
6. Do not silently skip a required leg because its quote/identity is missing while submitting the rest. Defer the entire group before submission, or record an explicit partial state only if submission had already begun for a separately documented runtime reason.

## 5. Fill and aggregate group state

Per-order/leg state must preserve at least: `PLANNED`, `PREFLIGHT_REJECTED`, `SUBMITTED`/`PENDING`, `PARTIALLY_FILLED`, `FILLED`, `REJECTED`, `CANCELLED`, and `UNKNOWN`/`RECONCILIATION_REQUIRED` as needed by the adapter.

Aggregate group state is derived from all required leg reports and the authoritative Position Read Model:

- `PLANNED`: valid plan exists; no order submitted.
- `PREFLIGHT_REJECTED`: group preflight denied before any submission.
- `SUBMITTING` / `OPEN`: submission is in progress or accepted orders remain unresolved.
- `PARTIAL`: at least one leg/quantity filled but the required group target is not complete.
- `BLOCKED`: progress cannot safely continue due to a known reject, invalid identity, missing evidence or policy failure.
- `RECONCILIATION_REQUIRED`: report/position state is missing, stale, contradictory, or cannot be safely deduplicated.
- `COMPLETED`: all required target quantities have authoritative fills and the Position Read Model confirms the target lifecycle state. A request/ACK alone can never make a group completed.

`ExecutionReport.remaining_quantity` is order-level unfilled quantity, not open-position quantity. The adapter/store must define whether a source report is per-fill delta or cumulative and normalize it so each actual fill is applied once. A positive `PARTIALLY_FILLED` quantity must update position/lot provenance and group state just like any other authoritative fill; it must not be ignored because status is not exactly `FILLED`.

## 6. Retry, rejection and reconciliation

- A duplicate evaluation with the same intent key returns/recognizes the existing order state and must not place another order.
- A timeout with unknown broker outcome is not proof of failure. Query/reconcile by client order ID and authoritative execution/order state before retrying.
- Retry only confirmed remaining position quantity or confirmed unfilled order quantity according to the order state; never resend an already-filled quantity.
- A rejected/cancelled/unfilled leg remains visible. Do not convert it to filled or reset strategy lifecycle.
- If reports and position read model disagree, `RECONCILIATION_REQUIRED` wins over optimistic completion; resolve from authoritative executions/positions, not from strategy intent.
- Close lifecycle and reset strategy-owned active-position state only after authoritative position state confirms all required close legs are flat. Preserve an exit-pending marker and batch ID meanwhile.

## 7. Strategy and compatibility constraints

- Existing entry/exit triggers and investment thesis remain unchanged; this is an execution-boundary contract.
- Apply grouped provenance and per-leg fill tracking to required multi-leg entries as well as terminal exits.
- Preserve single-order backward compatibility for genuinely single-leg intents and independent hedge rebalance actions.
- Preserve non-terminal behavior: Strategy5 gap-fill remains Futures-only; Strategy5 terminal Stop/Timeout/Trailing while hedge is open groups Futures+Option; after hedge closure, Option-only exit remains valid.
- Strategy8 DTE <= 4 `HOLD_LONG_ATTACK` remains NON_EXECUTION and must not be promoted to forced close.
- Strategy3 index is reference-only, not a tradable leg. Strategy4 hedge-only action remains Futures-only unless its actual terminal trigger calls for a group close.
- Never interpret a grouped plan as a guarantee of simultaneous/atomic fills or identical fill prices.

## 8. Required tests before implementation can be accepted

1. All legs pass preflight ??all required intents may be submitted.
2. Any preflight leg reject/missing quote/identity ??zero group submissions.
3. First-leg reject; later-leg reject after an earlier fill; partial quantity; cancellation; timeout with unknown outcome.
4. Duplicate evaluation, duplicate execution report, retry after partial fill, and retry after reconciliation.
5. Actual remaining quantity differs from entry quantity; multiple open lots; one leg already flat; no invented index leg.
6. Missing/stale/conflicting Position Read Model and invalid instrument identity fail closed.
7. Single-order backward compatibility; required multi-leg plan missing fails closed.
8. Strategy5 terminal vs non-terminal distinction and Strategy8 DTE<=4 NON_EXECUTION.
9. PositionLotStore, Position Read Model, Trade P/L and Control Tower provenance agree on actual filled quantities.
10. Run only against Virtual Execution. No KIS Live order submission.

## 9. Implementation order

Phase 2: runtime plan propagation and all-leg preservation ??group Risk preflight ??order/idempotency registry and report normalization ??partial-fill/lot/read-model reconciliation ??exit-pending lifecycle.

Phase 3: apply to Strategy5 reference path, then Strategies 1?? and 6?? using their existing strategy-specific resolvers; preserve the strategy matrix recorded in Notion No.1132.

Phase 4+: focused tests, Virtual Runtime scenarios, bounded replay, architecture/dependency checks, then Playwright/UI regression. Implementation changes to architecture/data contracts require a separate user approval before commit/push.
