# Q25 A8 T18 — Synthetic OMS Order/Execution Lineage Reconciliation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: Virtual-only order/execution lifecycle edge cases and multi-leg group/leg/order lineage integrity.

## Decision reconciliation

- No.1534 is mandatory: reuse existing source evidence and preserve Raw/Canonical/accepted partitions/manifests. No new collection.
- No.1535/No.1538: provenance-preserving synthetic fixtures are accepted for validation; generated values remain distinguishable and do not claim to be observed KIS/account facts.
- No.1554/1555 and Current Baseline: validation-only execution fixtures do not establish broker/account authority, actual fee/tax/margin, production or Live readiness.
- Existing evidence paths and Notion decisions were checked before treating any mismatch as a code defect. The new test reproduced a concrete lineage mismatch acceptance defect, so a narrowly scoped guard was added rather than blocking the overall validation path.

## Finding and scoped code change

Before this change, `VirtualMultiLegExecutionBridge._apply_reconciled_execution` consumed an execution report without first checking that:
- report.client_order_id matched the broker command''s client_order_id;
- a supplied report.group_id matched the active plan.group_id;
- a supplied report.leg_id matched the active leg.leg_id.

A deterministic synthetic test reproduced all three mismatches being accepted far enough to mutate position/fee/provenance state (the client-order mismatch failed later in the position fill adapter, after earlier mutation). This exposed a partial-mutation risk.

Added pre-mutation lineage checks:
- `MULTI_LEG_EXECUTION_ORDER_LINEAGE_MISMATCH`
- `MULTI_LEG_EXECUTION_GROUP_LINEAGE_MISMATCH`
- `MULTI_LEG_EXECUTION_LEG_LINEAGE_MISMATCH`

Checks run before fill expansion, provenance writes, execution fingerprint writes, position-lot mutation or fee-ledger mutation. Optional group/leg metadata may remain absent for compatible legacy report shapes; if supplied, it must match the active plan/leg. Client order ID must always match the broker command.

Added parameterized regression coverage for wrong group, wrong leg and wrong client order. Each case asserts zero position lots, zero leg positions, zero execution/provenance maps and zero fee rows after rejection.

## Validation results

- Combined T17 + T18 focused regression suite: **149 passed, 0 failed**.
- Includes synthetic four-leg quote timestamp/no-lookahead/anchor lineage/freshness, source-capability fallback, Runtime/X2 latch, partial fills, duplicate execution idempotency, conflicting execution IDs, cancel/fill race, late fill, group/leg metadata propagation and U19 checkpoint reconciliation.
- Python compileall for changed source and tests: PASS.
- git diff --check: PASS.
- Ruff E/F/I scan on the existing lifecycle implementation surfaced pre-existing import ordering, unused import and undefined Sequence lint debt elsewhere in the same large file; these unrelated imports/type annotations were not mass-cleaned. T17''s new synthetic test file remains Ruff E/F/I clean.

## Interpretation and limits

- A report with mismatched group, leg or client-order lineage is rejected before any position/fee/provenance mutation.
- Existing partial fill, repeated cumulative report, conflicting execution ID, cancel-race and late-fill tests remain passing.
- This is deterministic Virtual/validation-only evidence. It does not certify KIS broker event ordering, real partial-fill/cancel semantics, actual execution fees, account position truth or Live behavior.
- Synthetic multiplier/fee values remain fixture values, not operating standards. Production risk limits remain unchanged.

## Git and preservation

- Changed code: `application/composition/virtual_multi_leg_execution.py`
- Changed tests: `tests/application/composition/test_s8_multi_partial_position_reconciliation.py`
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new data collection, collector restart, order submission, correction, cancellation, liquidation, flattening or Runtime stop were executed. All order/execution events in this stage were deterministic synthetic test objects.

## Next step

T19: extend validation-only reconciliation across multi-leg partial entry/exit groups, cancel-confirmed-but-late-fill sequences, broker/ledger quantity disagreement, duplicate event replay after process restart and persistent U19 checkpoint recovery. Preserve the no-blind-retry and no-real-order boundary.
