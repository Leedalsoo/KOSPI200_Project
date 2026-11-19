# Q25 A8 T25 — Four-Leg Partial-Fill, Cancel-Race and U19 Restart E2E

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: one four-leg synthetic Virtual group combining multi-leg partial fills, cancel/late-fill race, adapter recreation, duplicate report replay and U19 SQLite checkpoint reopen.

## Decision reconciliation

- No.1534 mandatory: existing derived scenario data was reused as the synthetic source anchor; Raw/REST/WS/Canonical/accepted partitions/manifests were not changed and no collection was performed.
- No.1535/No.1538: four contracts, quotes, execution events and account/ledger snapshots are explicitly synthetic/derived validation evidence. The generated group does not claim to be actual simultaneous KIS quotes or real account state.
- No.1554/1555 and Current Baseline: no real multiplier, fee/tax, margin, account, tradability or Live operating standard is inferred.
- T18/T21/T22 rules remain active: group/leg/order lineage is checked before mutation; report metadata is retained through VSSF/Virtual lifecycle and recovery; duplicate execution IDs are idempotent.

## One-group four-leg scenario

Added `test_t25_four_leg_partial_fill_cancel_race_exactly_once` to `tests/application/composition/test_r4_positive_multileg_runtime_lifecycle.py`.

- Uses two CALL and two PUT contracts with distinct synthetic identities, one shared group and quantity 2 per leg.
- All four orders first receive one partial fill; the bridge reconciles four partial reports and creates four position lots/fee records.
- A cancel request is initiated for one leg while a second/late fill is injected before the cancel response. The late fill completes that leg; the terminal result is FILLED, not falsely treated as cancelled.
- The other three legs receive their remaining fills. Final state has 4 completed legs, 8 unique execution fills, 8 position lots and 8 fee records.
- Replaying each final report through the bridge produces no additional position, fee or VSSF account-position mutation.
- A new VSSF adapter instance queries all four orders and recovers group/leg metadata without the prior adapter''s in-memory cache.
- Independent synthetic VSSF account positions and position-lot ledger quantities reconcile exactly.
- U19 SQLite checkpoint is saved, reopened through a new store/coordinator, and the same eight execution events are replayed twice. U19 retains eight unique events and the eight position/fee effects remain unchanged.

## Validation results

- T23 four-leg restart + T25 one-group partial/cancel-race + FRESH31/FRESH32 + S8 suite: **17 passed, 0 failed**.
- U19 broker/ledger/checkpoint/account reconciliation suite: **106 passed, 0 failed**.
- Python compileall: PASS.
- Scoped Ruff F401/F821 for the changed test module: PASS.
- git diff --check: PASS.

## Interpretation

- This is the first combined test in this sequence where multi-leg partial fills, one-leg cancel/late-fill race, adapter recreation, duplicate report replay and U19 checkpoint reopen all occur within the same four-leg group.
- A cancel request does not override a fill that wins the race; the resulting report is reconciled as FILLED.
- Group/leg/order/execution lineage is consistent across reports, VSSF account positions, position lots, fees and U19 events.
- Exactly-once behavior is verified by unchanged 8-lot/8-fee state after duplicate report replay and duplicate U19 event replay.
- All values and events are synthetic/Virtual fixtures. This does not establish actual KIS cancel/fill ordering, account truth, contract multiplier, fee/tax, margin or Live readiness.

## Git and preservation

- Changed test: `tests/application/composition/test_r4_positive_multileg_runtime_lifecycle.py`
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new data collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop. The cancel race is simulated entirely inside the Virtual VSSF test runtime.

## Next step

T26: run a wider integrated regression of T18-T25 after the new same-group E2E test, including source-capability fallback, four-leg quote provenance, execution lineage propagation, U19 restart and X2 latch persistence. Any unrelated lint or baseline issue remains out of scope unless it directly affects these validated invariants.
