# Q25 A8 T22 — ExecutionReport Shape and Legacy Lineage Compatibility Matrix

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: compatibility audit for ExecutionReport construction/normalization, optional group/leg metadata, multi-fill expansion, cumulative REST recovery and Virtual query/cancel projections.

## Decision reconciliation

- No.1534 mandatory: preserve and reuse original data/accepted/Canonical/manifests; no new collection.
- No.1535/No.1538: deterministic synthetic fixtures are acceptable for validation-only tests; synthetic values are not actual KIS/account facts.
- No.1554/1555 and Current Baseline: report-shape compatibility does not establish Live or account-authoritative semantics.
- T18''s pre-mutation order/group/leg guard and T21''s metadata propagation remain the governing rules: infer absent optional group/leg only from an unambiguous active plan/leg or client-order correlation; never overwrite conflicting non-empty metadata.

## Constructor inventory and compatibility paths

A read-only source scan identified 19 `ExecutionReport(...)` construction sites across application composition, Virtual execution, Live KIS futures execution/recovery and high-speed validation ingestion, plus CanonicalExecutionReport/VSSFOrderResult mapping paths.

Compatibility tests added:
1. Legacy execution report with absent group_id/leg_id is accepted only under the active unambiguous plan/leg; resulting position lots inherit that plan/leg lineage.
2. Multi-fill expansion preserves outer report group_id/leg_id and client_order_id on every expanded execution report while preserving total filled quantity.
3. Legacy KIS recovery correlation context without optional group/leg attributes remains compatible and produces absent optional metadata rather than fabricated identifiers.

Previously added T21 tests continue to cover:
- VSSFOrderResult legacy and metadata-bearing forms;
- CanonicalExecutionReport mapping;
- VSSF adapter recreation/query/cancel;
- Virtual query/cancel projections;
- KIS recovery direct and cumulative normalization;
- conflicting metadata rejected by the T18 pre-mutation guard.

## Validation results

- T22 report-shape compatibility + T18/T21 focused suite: **39 passed, 0 failed**.
- Python compileall for changed test modules: PASS.
- Scoped Ruff F401/F821 on S8/VSSF/Virtual test modules: PASS.
- git diff --check: PASS.
- No runtime implementation change was required in T22; only compatibility tests and this report were added.

## Interpretation

- Missing group/leg metadata remains backward-compatible only where an active execution plan/leg or client-order context unambiguously supplies it.
- Ambiguous or contradictory non-empty metadata is not silently rewritten; the T18 guard rejects it before position, fee or provenance mutation.
- Multi-fill expansion preserves the outer order lineage for each individual execution fill.
- KIS cumulative REST snapshots remain reconciliation evidence, not individual authoritative fill events; tests do not bypass the existing inbox/U19 reconciliation gates.
- All results are offline/Virtual or deterministic synthetic tests. No real KIS order, account, fee, margin or Live behavior is certified.

## Git and preservation

- T22 changes tests only:
  - `tests/application/composition/test_s8_multi_partial_position_reconciliation.py`
  - `tests/environments/live/test_kis_execution_recovery_service.py`
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS/Canonical/accepted partitions/manifests/synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new data collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop.

## Next step

T23: run an end-to-end validation-only Virtual replay that creates a four-leg order group, produces partial multi-fill reports, reconciles one late fill and one cancel-race result, persists/reopens U19 state, and verifies the same group/leg/order/execution lineage and exactly-once position/fee effects after restart. Keep all broker/fee/margin/account assumptions synthetic and explicitly marked.
