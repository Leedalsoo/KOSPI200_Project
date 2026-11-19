# Q25 A8 T24 — Four-Leg, Partial-Fill, Cancel-Race and U19 Cross-Scenario Regression

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: post-T23 validation-only cross-scenario regression for four-leg Virtual group, multi-fill partial entry/close, cancel-race late fill and U19 durable checkpoint recovery.

## Decision reconciliation

- No.1534 mandatory: use existing accepted/derived scenario anchors and preserve Raw/REST/WS/Canonical/accepted/manifests; no new collection.
- No.1535/No.1538: synthetic contracts, quote/execution/account snapshots are validation-only; no generated value is claimed as an observed KIS or real-account fact.
- No.1554/1555 and Current Baseline: Virtual regression does not set real multiplier, fee/tax, margin, account or Live operating criteria.
- T18/T21/T22 lineage rules remain in force: reject conflicting non-empty group/leg/order metadata before mutation; enrich absent optional metadata only from unambiguous plan/leg/client-order context.

## Executed scenario matrix

1. Four-leg Virtual group:
   - Two synthetic CALL and two synthetic PUT contracts, distinct identities, common group.
   - 4/4 routed/filled; report/position/fee group-leg lineage verified.
   - U19 SQLite checkpoint persisted/reopened; duplicate execution event replay deduplicated to four unique events; no duplicate position/fee mutation.
2. Multi-fill partial entry and exit:
   - Existing FRESH31 test verifies partial fills, later completion, partial/full close and independent VSSF/position/fee/U19 comparison.
3. Cancel/fill race:
   - Existing FRESH32 test verifies late fill during cancel, pending/reconciliation gate, duplicate replay idempotency and conflicting execution-ID rejection.
4. S8 multi-partial position reconciliation:
   - Position-lot, fee and group/leg reconciliation regression retained.

Important scope distinction: the four-leg restart scenario, FRESH31 partial-fill scenario and FRESH32 cancel-race scenario are separate tests. This stage does not claim all event types occurred on the same four-leg group.

## Validation results

- Four-leg + FRESH31/FRESH32 + S8 suite: **16 passed, 0 failed**.
- U19 broker/ledger/checkpoint/account reconciliation suite: **106 passed, 0 failed**.
- Python compileall: PASS.
- Scoped Ruff F401/F821 for the four-leg test module: PASS.
- git diff --check: PASS.
- No code or test implementation change required in T24; this is a regression consolidation and versioned report only.

## Interpretation

- Four-leg group/leg lineage and U19 duplicate replay survive a SQLite checkpoint reopen in the tested Virtual scenario.
- Partial-fill/close and cancel-race/late-fill behavior remain passing in their dedicated end-to-end scenarios.
- U19 independently compares broker-position and execution-ledger snapshots; incomplete, unverified or conflicting evidence remains gated rather than auto-restored.
- All event and account data are synthetic/Virtual fixtures. No real broker timing, account state, contract multiplier, fees/tax, margin, tradability or Live readiness is established.

## Git and preservation

- T24 adds this report only; no source/test implementation changes.
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop.

## Next step

T25: consolidate the separate partial-fill and cancel-race cases with the four-leg group into one controlled Virtual group scenario. If the existing replay source lacks aligned per-leg evidence, compare No.1534 sources and No.1535/1538 synthetic calibration rules, then create deterministic validation-only derived quotes with explicit anchor lineage rather than forcing the source data or blocking the scenario.
