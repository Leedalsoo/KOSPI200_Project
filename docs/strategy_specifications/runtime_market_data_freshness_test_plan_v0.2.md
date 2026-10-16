# Market Data Freshness — File Scope and FRESH-01–14 Test Plan v0.2

- Date: 2026-10-15 KST
- Status: **Draft / validation and explicit user approval required / implementation not authorized**
- Branch/HEAD at audit: `Project200` / `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`
- Basis: No.1274, No.1275, `runtime_kis_source_evidence_to_s1_s9_matrix_v0.1.md`, `runtime_s1_s9_kis_runtime_caller_chain_trace_v0.1.md`, existing v0.1 freshness scope and v0.2 order-admission trace.
- No runtime code, tests, Manifest, account config, raw evidence or Git index/history was changed in drafting this plan.

## 1. Current blockers that constrain the plan

1. Official KIS sample says both index-option WS TRs H0IOCNT0 (option trade/Greeks/IV) and H0IOASP0 (option book) are LIVE-only and unsupported in simulated trading: https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py. Treat VTS option WS as `BLOCKED_SOURCE_CAPABILITY`. The 796 H0IOCNT0 frames in the VTS-labeled raw file are conflicting historical evidence, not support proof. Do not retry either TR.
2. REST `aspr_acpt_hour` is time-only; saved responses include missing/000000 values. Official material does not yet prove the calendar-date association, timezone, event/acceptance-time meaning, precision or session rollover well enough to create an absolute source instant.
3. REST normalizer currently returns `observed_at=None` and `raw_reference=None`. Historical replay source may use `collected_at` as ordering time; this is not a live source-age verdict.
4. `automated_virtual_runtime_factory.py` connects the standard Virtual loop to `bootstrap.bundle.market`; current source inspection does not prove KIS raw → each strategy input → signal/plan end-to-end. Track2 observation sink is assigned but its call from the inspected loop was not found.
5. Single-order admission has no required typed freshness verdict. Multi-leg route has a distinct executor boundary and also lacks proven freshness enforcement. Both paths must be covered.
6. `tests/` is absent and Git shows prior test deletions. Preserve deletions; create only new tests after approval.

## 2. Candidate file scope — exact edits remain unapproved

| File or new module | Candidate responsibility | Existing state / constraint |
|---|---|---|
| `contracts/types.py` | Carry distinct source-time raw value, verified source instant, receive/collection time, raw payload hash/reference and provenance | Existing modified file; merge narrowly, preserve diff. |
| `infrastructure/kis/kis_rest_market_observation_collector.py` | Preserve request/receive clocks, TR/endpoint, raw response hash and raw source-time fields | Existing modified file; no whole-file rewrite. |
| `infrastructure/kis/kis_rest_market_observation_normalizer.py` | Produce `observed_at` only if KIS semantics prove an absolute instant; retain raw field and identity | Existing modified file; current `observed_at=None` is safer than guessed date/time. |
| **New** `contracts/market_data_freshness.py` (candidate) | Typed verdict: `FRESH`, `STALE`, `UNKNOWN`, `IDENTITY_CONFLICT`, `BLOCKED_SOURCE_CAPABILITY`; reason, policy version and evidence refs | Architecture choice; new file only after approval. |
| `application/composition/automated_virtual_runtime_factory.py` | Wire verified source/provenance through the real caller graph; remove implicit assumption that an injected port is populated | Existing code is not proven to subscribe KIS raw option frames to the strategy source. |
| `application/composition/standard_runtime_input_provider.py` | Keep per-strategy required source statuses/provenance available to signal/admission | No current modification marker at audit; verify caller graph before editing. |
| `application/composition/automated_virtual_trading_loop.py` | Carry freshness result to both single-order and multi-leg paths; deny if missing/unknown | No current modification marker at audit; preserve existing behavior outside approved scope. |
| `application/composition/runtime_authoritative_risk_router_adapter.py` | Require a validated freshness verdict before `RiskGate.admit_order` | No current modification marker at audit; do not weaken approval-token requirement. |
| `core/runtime/reference_execution_pipeline.py` | Shared admission proof only if caller trace confirms this is the common seam | Existing modified file; preserve diff and avoid assuming every S1–S9 path uses it. |
| `application/composition/virtual_multi_leg_execution.py` | Enforce per-leg source freshness and group exposure gate before routing each leg | Must inspect/confirm actual internal calls; group preflight alone is not freshness proof. |
| `core/oms/order_router.py` | Optional final defensive guard only if architecture review places source verdict here | Do not replace or bypass risk approval token and FSM transitions. |
| New files under `tests/` | Unit, contract and path-coverage tests for FRESH-01–14 | Create new tests only; never restore deleted tests. |
| `verification/evidence/` | Sanitized deterministic result logs, policy version, evidence hashes and traceability | No secrets, full account IDs or live order actions. |

## 3. FRESH-01–14 acceptance plan

| ID | Scenario / seam | Expected outcome and required assertions |
|---|---|---|
| FRESH-01 | Missing/malformed/date-ambiguous source time; REST normalizer → typed verdict | `UNKNOWN`; risk-increasing order denied; no broker call. Preserve raw time and receive time separately. |
| FRESH-02 | Source instant older than the approved age threshold | `STALE`; deny new/add/risk-increasing orders; record measured age and policy version. |
| FRESH-03 | Source instant exceeds approved future-skew bound | `UNKNOWN`; deny; do not clamp the timestamp or substitute receive time. |
| FRESH-04 | REST price and book timestamps conflict or exact contract identity conflicts | `IDENTITY_CONFLICT`; deny and retain both raw evidence references. |
| FRESH-05 | Raw response hash/reference, TR/endpoint, environment or exact contract identity is missing | Deny; no synthetic/fixture/local-master substitution in a KIS-authoritative path. |
| FRESH-06 | Multi-leg entry has any stale/unknown leg or source-time spread above approved limit | Deny the new group; preserve each leg state and do not pretend atomic fill. |
| FRESH-07 | Receive-time spread exceeds diagnostic threshold | Emit diagnostic only; never treat receive-time spread as source-time age. |
| FRESH-08 | Exposure exists but current executable-side quote is stale/missing | Do not auto-close/reduce/hedge without fresh exact-contract quote plus reconciled actual position/open orders/fills/cancels; alert/manual intervention. |
| FRESH-09 | Cancel pending, partial fill, late fill during cancel or replacement order requested | Keep exposure/order state unresolved until terminal order state and fills are reconciled; no duplicate/replacement leg. |
| FRESH-10 | Restart/reconnect after source gap | Remain blocked until source capability, timestamp, identity, positions, orders, fills and cancels reconcile. |
| FRESH-11 | Each S1–S9 registry ID and caller route | Prove required source verdict is mandatory before final admission; any uncovered route fails the coverage test and remains blocked. |
| FRESH-12 | RiskGate rejection or absent/invalid approval token while data is fresh | No broker call; freshness cannot override risk denial. |
| FRESH-13 | Deterministic replay/restart with same evidence and policy version | Same verdict and reason; evidence references and per-leg state survive replay/restart. Does not count as REAL_VTS/LIVE proof. |
| FRESH-14 | Unsupported source capability: VTS H0IOCNT0/H0IOASP0 | `BLOCKED_SOURCE_CAPABILITY`; no data from these TRs is accepted as VTS input; no retry/subscription attempt. |

Every path test must assert: broker-call count; source raw value and verified instant (or UNKNOWN); receive time; exact contract/leg identity; TR/endpoint/environment; evidence hash/reference; verdict/reason/policy version; RiskGate result; OMS state; order/fill/cancel reconciliation state.

## 4. Candidate numeric policy (not activated)

Existing candidate values to review after timestamp semantics are documented:
- WS source age ≤ 2,000 ms.
- REST source age ≤ 2,000 ms.
- Allowed future source-time skew ≤ 1,000 ms.
- Multi-leg source-time spread ≤ 1,000 ms.
- Receive-time spread ≤ 500 ms as diagnostic only.

These values are not a license to derive source age from HHMMSS. They remain **NOT IMPLEMENTABLE** until KIS confirms source-time semantics and the user approves the final policy/scope.

## 5. Approval and sequencing gates

1. Keep VTS option WS blocked according to official KIS capability. Only KIS written clarification or a newer official source may revise this.
2. Obtain authoritative REST timestamp semantics; if unavailable, source-age verdict remains UNKNOWN/BLOCKED.
3. Freeze exact shared admission seam and per-strategy source graph, including the multi-leg executor's internal route.
4. Review existing modified files/diffs; produce narrow patch plan with before/after behavior.
5. Obtain explicit user approval for this exact file scope and FRESH-01–14 test plan.
6. Only then implement approved changes and create new tests; run offline unit/contract tests and controlled replay tests.
7. Report actual commands, exit codes, evidence hashes, per-test status and remaining gaps. No KIS retries, account endpoints, LIVE orders, Manifest edits, Git stage/commit/push without applicable separate authorization.

## 6. Current status

- Evidence inventory and initial S1–S9 matrix: **PASS as documentation/read-only analysis**.
- KIS raw → all S1–S9 input/signal/plan/admission: **PARTIAL / NOT PROVEN**.
- VTS option WebSocket capability: **BLOCKED**.
- REST source timestamp semantics and final freshness enforcement: **BLOCKED / NOT PROVEN**.
- FRESH-01–14: **PLANNED / NOT RUN**.
- Implementation approval: **PENDING**.
