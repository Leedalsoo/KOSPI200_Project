# Q25 A8 Track 4 T3 — X2 validation-only automatic stop switch

- Date: 2026-11-19 (KST)
- Branch: `work/q25-a8-r10-order-lineage-u19-20261118`
- Base HEAD before T3: `574c9c428a3b5ee1db9088af76825fed4e9959d5`
- Decision references: No.1534 / No.1538 / No.1554 / No.1566 / No.1546 / Current Baseline v2

## Scope and existing boundaries

- Reused the existing `RiskGuard.engage/evaluate/snapshot` and `RiskEngine.trigger_kill_switch/is_kill_switch_active` APIs. No duplicate order-admission or kill-switch calculation was introduced.
- `RiskGate` remains the enforcement boundary: a latched RiskGuard status denies admission; the existing RiskEngine kill switch rejects orders after the guard check.
- `RuntimeController` lifecycle (`start/stop`) was inspected and left unchanged. X2 does not call `RuntimeController.stop()` and does not request runtime shutdown.
- X2 is validation-only. It does not cancel/replace orders, flatten positions, mutate position/fee/execution ledgers, enable Live/REAL_VTS, or call account/order APIs.

## Implementation

- Added `ValidationOnlyRuntimeAutoStopSwitch` with fail-closed triggers for unavailable/failed X1 report, U19 recovery not allowed or pending orders, unavailable/blocked RiskGuard state, non-FRESH or conflicting market data, and explicit manual stop.
- Latches both existing admission controls and records all trigger reasons.
- Added append-only SQLite stop-state storage. A persisted trip is reapplied after reconstruction; there is no automatic reset API.
- Added re-latch verification on each snapshot so an external reset of either existing gate cannot silently clear a previously tripped X2 state.
- Latch operations are attempted independently. If one gate fails, the other is still engaged; the snapshot reports each gate separately and reports `TRIP_LATCH_FAILED` only when neither gate confirms the block.
- Tested `RiskGate` against the same injected RiskGuard/RiskEngine instances to confirm a single surviving gate still denies new order admission.

## Verification

- Focused X2 + X1 + Track2 control regression: **54 passed**.
- RiskGate + X2 + X1 regression: **62 passed**.
- FRESH31 Bridge/VSSF/U19 integration + X2: **22 passed**.
- `py -m compileall -q application/composition/validation_only_runtime_auto_stop_switch.py`: PASS.
- `py -m ruff check application/composition/validation_only_runtime_auto_stop_switch.py tests/application/composition/test_validation_only_runtime_auto_stop_switch.py`: PASS.
- `git diff --check`: PASS.

## Limits and safety

- These are validation-only component and injected RiskGate tests. They do not certify that every Virtual Runtime composition or any Live runtime has X2 automatically wired as its global supervisor.
- RuntimeController was not stopped. No actual orders, cancels, liquidation, Live/REAL_VTS/account APIs, new collection, or raw/Canonical/Accepted data changes were performed.
- Existing Graphify outputs and unrelated dirty/untracked files were preserved and excluded from the T3 code change.
- T2 X1 checker and its existing report were preserved; the T2 checker has only a newline-formatting working-tree diff and is not part of the T3 commit.

## Files in T3 commit

- `application/composition/validation_only_runtime_auto_stop_switch.py`
- `tests/application/composition/test_validation_only_runtime_auto_stop_switch.py`