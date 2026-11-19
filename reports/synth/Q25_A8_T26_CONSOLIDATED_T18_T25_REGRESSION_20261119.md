# Q25 A8 T26 — Consolidated T18–T25 Validation-Only Regression

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: consolidated regression of source-capability fallback, synthetic four-leg quote provenance, OMS order/execution lineage, VSSF/Virtual/KIS report mapping, U19 checkpoint recovery and X2 latch persistence.

## Mandatory decision reconciliation

- No.1534 remains mandatory: reuse existing source artifacts first, distinguish Raw frames/records/Canonical rows, preserve original WS/REST Raw, Canonical, accepted partitions and manifests.
- No.1535/No.1538: use provenance-preserving deterministic synthetic/derived evidence for missing coverage; preserve source anchors, timestamps, IDs, generated fields and manifest/hash; no future-anchor lookahead; do not claim synthetic evidence as observed KIS/real-account facts.
- No.1554/1555 and Current Baseline: all current execution/account/fee/margin validation remains Virtual-only. Real account API definitions and authoritative operating criteria are not inferred before connection and explicit authorization.
- Data mismatch or shortage is reconciled against Notion decisions and original source lineage first; alternative schema/contract checks, deterministic synthetic fixtures and independent replay are used before any BLOCKED/UNAVAILABLE classification.

## Consolidated regression batches

- S2 source capability, accepted-original rejection, Notion/raw reconciliation, synthetic fallback, freshness and X2 latch: **104 passed**.
- OMS partial fill, cancel/fill race, late fill, execution ID conflict, group/leg/client-order mismatch, KIS recovery and VSSF metadata: **44 passed**.
- R4 Virtual multi-leg positive runtime and four-leg E2E: **7 passed**.
- Strategy/group/PnL/U16 runtime lifecycle and order-plan adapter: **67 passed**.
- U19 broker/ledger/account snapshot, durable checkpoint, restart and dedup recovery: **106 passed**.
- Total across the separate, non-overlapping batches: **328 passed, 0 failed**.

## Additional static checks

- Python compileall for source capability, evidence supervisor, multi-leg execution, VSSF, Virtual/KIS recovery, U19 and focused tests: PASS.
- Scoped Ruff F401/F821 for the consolidated four-leg E2E test module: PASS.
- git diff --check: PASS.
- No code or test implementation change was required in T26; this stage is a consolidated regression and versioned report only.

## Confirmed invariants

- Unverified VTS/REAL source capability or timestamp semantics cannot be promoted to authoritative original evidence; the supervisor falls through to provenance-preserving synthetic alternatives without automatically tripping X2 solely for missing original coverage.
- Synthetic four-leg quotes are timestamp-scoped and anchored only to observations at or before the scenario time.
- Execution report group/leg/client-order mismatch is rejected before position/fee/provenance mutation; missing optional metadata is enriched only from unambiguous active plan/leg/client-order context.
- VSSF, Virtual query/cancel and KIS REST recovery projections preserve group/leg lineage when available.
- Partial fills, duplicate/out-of-order execution, cancel/late-fill races, adapter recreation and U19 checkpoint reopen remain idempotent in the tested synthetic scope.
- X2 latch remains durable and does not expose a reset or real broker cancel/liquidation side effect.

## Git and preservation

- T26 adds this report only; no source/test implementation changes.
- R10 local/origin HEAD: `99243da8f46a631415558668c46d3f8617c0b721` (matched).
- Project200 remote HEAD remains `4ef1c3b76c657843c6acdb814be98f593252854c` (unchanged).
- Existing unrelated dirty files preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new market-data collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop. All lifecycle events and account snapshots are synthetic/Virtual test fixtures.

## Next step

T27: review the remaining pre-existing dirty runtime invariant checker and Graphify outputs without overwriting user work; compare them to the current committed baseline and No.1534 decisions, then determine whether any validation-only invariants remain untested. Do not stage or commit those pre-existing dirty files without explicit scope approval.
