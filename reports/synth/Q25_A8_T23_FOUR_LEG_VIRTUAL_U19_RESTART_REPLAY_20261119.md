# Q25 A8 T23 — Four-Leg Virtual Group and U19 Restart Replay

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: end-to-end validation-only four-leg VSSF/Virtual group, execution lineage, position/fee effects and SQLite U19 checkpoint reopen with duplicate event replay.

## Decision reconciliation

- No.1534 mandatory: existing accepted/source data was used only as a source anchor; no original Raw/Canonical/accepted/manifest data was changed and no new data was collected.
- No.1535/No.1538: contract identity, quotes and all execution/account snapshots in this test are explicitly synthetic/derived validation fixtures. They do not claim authoritative KIS contract/account facts or observed simultaneous production quotes.
- No.1554/1555 and Current Baseline: this is Virtual-only evidence; real multiplier, fees/tax, margin, tradability and Live readiness remain unverified.
- T18/T21/T22 lineage rules remain active: group/leg/client-order metadata is checked, propagated and preserved through report, lot, fee and recovery paths.

## New four-leg end-to-end scenario

Added `test_t23_four_leg_virtual_group_reconciles_and_persists_u19_after_restart` to `tests/application/composition/test_r4_positive_multileg_runtime_lifecycle.py`.

- Selects two CALL and two PUT contracts at the same synthetic replay timestamp and expiry from the existing derived scenario source.
- Uses four distinct synthetic contract identities and one common order group.
- Runs all four legs through the actual Virtual MultiLeg bridge and VSSF runtime.
- Verifies 4/4 routed and filled; every report, position lot and fee record retains the same group and its corresponding leg; four distinct execution IDs.
- Builds independent synthetic broker-position and execution-ledger snapshots with four execution fingerprints.
- Persists U19 state in SQLite, reopens a new store/coordinator, replays duplicate copies of the same execution events and verifies U19 deduplicates them to four unique events.
- Confirms recovery does not mutate the Virtual position-lot history or fee ledger: four lots and four fee records remain exactly once.

## Combined adjacent scenario coverage

The T23 combined scenario suite also reruns existing tests for:
- multi-fill partial entry, later completion, partial/full close and independent VSSF/position/fee/U19 comparison (FRESH31);
- cancel/fill race with one late fill, pending gate, duplicate replay idempotency and conflicting execution ID rejection (FRESH32);
- multi-leg group lifecycle and S8 partial-position reconciliation.

These partial-fill and late-fill scenarios are separate tests from the new four-leg restart scenario; no claim is made that one single order group exercised every event type.

## Validation results

- Four-leg + FRESH31/FRESH32 + S8 integrated suite: **16 passed, 0 failed**.
- U19 broker/ledger/checkpoint/account-reconciliation suite: **106 passed, 0 failed**.
- New four-leg restart/duplicate replay scenario independently: **1 passed**.
- Python compileall: PASS.
- Scoped Ruff F401/F821 for the changed test module: PASS.
- git diff --check: PASS.
- T23 adds test coverage only; no runtime implementation changes.

## Interpretation

- Four-leg group/leg/order/execution identity is retained across VSSF reports, position lots, fees and U19 execution events in the synthetic Virtual replay.
- U19 SQLite checkpoint state can be reopened and duplicate event replay remains idempotent without duplicating position/fee effects.
- FRESH31/FRESH32 separately validate partial fills, late fill after cancel begins, cancel race, pending/restore gate and conflicting execution-ID protection.
- These are software-behavior results under deterministic synthetic assumptions, not evidence of actual KIS broker timing or account state.

## Git and preservation

- Changed test: `tests/application/composition/test_r4_positive_multileg_runtime_lifecycle.py`
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source data, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop. All four-leg orders and recovery snapshots are synthetic/Virtual test objects.

## Next step

T24: extend the same four-leg synthetic scenario to partial fills across multiple legs, cancel-race/late-fill on one leg, process/adapter recreation, U19 checkpoint reopen and exact-once position/fee reconciliation. Preserve T18 mismatch rejection and T21 report lineage propagation.
