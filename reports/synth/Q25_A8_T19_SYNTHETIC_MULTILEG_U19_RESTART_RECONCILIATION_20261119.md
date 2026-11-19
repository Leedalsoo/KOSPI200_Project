# Q25 A8 T19 — Synthetic Multi-Leg Lifecycle and U19 Restart Reconciliation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only regression of multi-leg partial entry/exit, cancel/late-fill, broker-ledger disagreement, duplicate execution replay and persistent U19 checkpoint recovery.

## Decision reconciliation

- No.1534 mandatory: reuse existing source and validation artifacts; preserve Raw/Canonical/accepted partitions/manifests; no new collection.
- No.1535/No.1538: use provenance-preserving synthetic evidence for software validation where actual event/contract coverage is incomplete. Do not relabel synthetic events as observed KIS/account events.
- No.1554/1555 and Current Baseline: Virtual recovery PASS does not establish actual broker/account truth or Live readiness. Real account API/official definitions remain pending.
- Existing Notion decisions and prior lifecycle/recovery tests were reconciled before determining this stage''s scope. The available synthetic evidence was sufficient to validate the listed software behaviors; no immediate BLOCKED verdict or source-data modification was needed.

## Validation matrix executed

- Core U19 broker-vs-ledger reconciliation and snapshot authority.
- Missing/unverified broker or ledger snapshots, timestamp skew, pending/unknown orders, fractional quantities, duplicate/conflicting execution IDs and group identity mismatch.
- Durable checkpoint recreation, append-only checkpoint behavior, payload tamper detection, idempotent checkpoint save and persisted execution dedup state.
- Four-leg open group → restart checkpoint → flat close recovery.
- Four-leg late fill pending gate → reconcile → restore.
- Out-of-order execution delivery and duplicate replay deduplication.
- Cancel/fill race remains pending until terminal state and position reconciliation.
- Multi-leg partial entry fills and partial/full close reconciliation against VSSF and U19.
- Cancel-race late-fill replay, conflicting replay and U19 checkpoint integration.
- Multi-group account snapshot netting, cross-group identity, late-fill ownership and checkpoint reopen.
- OMS partial fill, late fill after cancellation, duplicate/reordered execution, Virtual cancel/fill race and group/leg metadata propagation.

## Results

- Focused combined regression: **128 passed, 0 failed**.
- Python compileall for relevant U19/OMS/runtime/recovery modules and tests: PASS.
- git diff --check: PASS.
- No code implementation change was required in T19; existing coverage was executed as an integrated regression and this report was added.

## Interpretation

- Existing validation-only tests cover the requested lifecycle and recovery cases with synthetic/deterministic event objects.
- U19 requires independent broker-position and execution-ledger evidence; mismatch, unknown/pending order, late fill, timestamp skew or conflicting execution identity does not permit blind restore or automatic quantity adjustment.
- Durable checkpoint state survives store/coordinator recreation and retains unresolved gates/conflict evidence. Duplicate identical execution events are idempotent; conflicting reuse remains gated.
- Multi-leg partial fills and close flows reconcile group/leg/order/execution provenance, position lots, fees and checkpoint evidence in the tested Virtual scope.
- These results do not certify actual KIS broker sequencing, real account positions, official contract multiplier, fees/tax, margin or Live operations.

## Git and preservation

- T19 adds this versioned report only; no runtime/test source code changes.
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new data collection, collector restart, real order submission, correction, cancellation, liquidation, flattening or Runtime stop were executed. All lifecycle evidence came from offline/Virtual test fixtures.

## Next step

T20: perform a consolidated validation-only audit of the order lifecycle lineage invariants after T18 and T19: cross-leg shared group, per-leg order chain, replacement/cancel linkage, execution-to-position/fee mapping, restart replay and no-duplicate side effects. Keep all unresolved operating/account fields validation-only until the real-account API is connected and separately authorized.
