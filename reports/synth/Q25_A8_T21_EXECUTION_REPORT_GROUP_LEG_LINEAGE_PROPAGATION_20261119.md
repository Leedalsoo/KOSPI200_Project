# Q25 A8 T21 — Execution Report Group/Leg Lineage Propagation Audit

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: audit and repair of execution-report construction/normalization paths so group_id and leg_id survive VSSF, Virtual cancel/query and KIS REST recovery projections.

## Decision reconciliation

- No.1534 mandatory: preserve original source evidence and inspect existing decision/manifest/contract lineage before classifying missing metadata. No new data collection.
- No.1535/No.1538: deterministic synthetic fixtures are valid for validation-only behavior; synthetic identity and order lifecycle are not actual KIS/account facts.
- No.1554/1555 and Current Baseline: changes to Live normalization code are offline code/test work only. No Live/REAL_VTS/account API invocation or promotion of validation values to operating criteria.
- T18 lineage checks remain strict: supplied group/leg/order metadata must match the active plan/leg/command before mutation. Missing metadata may be carried from the already correlated client-order command/context; contradictory non-empty metadata is not overwritten.

## Audit findings

1. `VSSFOrderResult` did not persist group_id/leg_id. `VSSFExecutionAdapter` depended on an in-memory metadata cache, so adapter recreation could lose order lineage on query/cancel.
2. `VirtualExecutionEngine` fallback cancel and authoritative query/cancel projections could omit prior group/leg metadata, especially when the query result had no execution_id.
3. `KISExecutionRecoveryContext` and cumulative REST recovery reports did not carry group/leg metadata from the order correlation context.
4. The VSSF adapter''s `CanonicalExecutionReport` mapping omitted group/leg fields even though the canonical report carried them.

## Scoped changes

- Added optional `group_id` and `leg_id` fields to `VSSFOrderResult`.
- VSSF firm runtime now copies group/leg from the submitted/pending canonical command into NEW, partial/final lifecycle, query and cancel results.
- VSSF adapter maps group/leg from both CanonicalExecutionReport and VSSFOrderResult; its in-memory metadata remains a compatibility fallback, not the only source.
- VirtualExecutionEngine preserves prior group/leg on fallback cancel and authoritative query/cancel reports when those projections omit the fields. A non-empty conflicting report value is retained so T18''s mismatch guard can reject it rather than silently overwrite it.
- KIS recovery context now accepts optional group/leg; REST cumulative snapshot normalization carries them into each delta report. Legacy correlation providers without these optional attributes remain compatible through `getattr`.
- Added tests for VSSF adapter recreation, pending/terminal VSSF metadata, canonical report mapping, Virtual query/cancel with omitted metadata and KIS REST direct/normalized recovery lineage.

## Validation results

Separate focused regression runs after the changes:
- T21 changed-path + T18 lineage/cancel-race suite: **36 passed, 0 failed**.
- U19 recovery/checkpoint/account-snapshot suite: **106 passed, 0 failed**.
- OMS multi-leg/U16/group/replacement lifecycle suite: **80 passed, 0 failed**.
- S2 synthetic source/fallback/Runtime evidence suite: **104 passed, 0 failed**.
- Python compileall for changed modules/tests: PASS.
- Scoped Ruff F401/F821 on the new VSSF/Virtual lifecycle test modules: PASS.
- git diff --check: PASS.
- Broader Ruff scans surfaced pre-existing style debt in these older files (long lines/import placement and an existing unused CanonicalMarketTick import); no unrelated formatting/import cleanup was made.

## Interpretation

- Group/leg lineage now survives the audited VSSF and Virtual order lifecycle projections and KIS REST recovery normalization when the original command/correlation context contains it.
- Adapter recreation no longer relies solely on an ephemeral in-memory metadata cache for VSSF lifecycle results.
- Missing legacy metadata can be enriched only from an unambiguous existing client-order correlation; contradictory supplied metadata remains visible and is rejected by the T18 pre-mutation guard.
- These tests validate software lineage only. They do not establish authoritative KIS account/contract identity, actual broker event ordering, multiplier, fee/tax, margin, tradability or Live readiness.

## Git and preservation

- Changed source modules:
  - `environments/virtual/authoritative_vssf/canonical.py`
  - `environments/virtual/authoritative_vssf/firm_runtime.py`
  - `environments/virtual/execution/vssf_execution_adapter.py`
  - `environments/virtual/execution/virtual_execution.py`
  - `environments/live/execution/kis_futures_execution_recovery_adapter.py`
- Changed tests:
  - `tests/environments/virtual/test_vssf_execution_adapter_group_leg_metadata.py`
  - `tests/environments/virtual/test_validation_only_virtual_order_lifecycle.py`
  - `tests/environments/live/test_kis_execution_recovery_service.py`
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/REST/WS data, Canonical/accepted data partitions, manifests, synthetic source tree, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new data collection, collector restart, real order submission/correction/cancellation, liquidation, flattening or Runtime stop. All execution events were offline/Virtual test fixtures.

## Next step

T22: run a report-shape compatibility matrix for all ExecutionReport constructors and normalizers, including legacy reports with absent optional group/leg metadata, multi-fill expansion, cumulative REST recovery and query/cancel projections. Assert that every report either carries its correlated lineage or is rejected as ambiguous before any position/fee/provenance mutation.
