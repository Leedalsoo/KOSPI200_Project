# Q25 A8 T16 — Post-T15 Synthetic Fallback Regression Revalidation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only regression of source capability gate, synthetic fallback, Virtual Runtime safety and timestamp provenance.

## Mandatory decision reconciliation

- No.1534 remains mandatory: reuse-first inventory, distinguish raw frames/records/Canonical rows, preserve Raw/Canonical/manifests and source lineage.
- No.1535 accepts provenance-tracked synthetic/complementary data for project verification; generated values do not claim to be directly observed market facts or Live performance.
- No.1538 requires market-calibrated synthetic quotes anchored only to observations at or before the candidate time, with anchor age and generated fields recorded; synchronized synthetic quotes do not imply simultaneous original observations.
- No.1554/1555 preserve the validation-only boundary: synthetic contract identity and market data may validate software behavior but cannot establish authoritative KIS identity, account facts, production readiness, fees, margin or tradability.
- No.1547 discrepancy policy: compare Notion decisions and original Raw/Canonical/manifest/Master/REST lineage first; use crosswalk, deterministic fixture, schema/contract checks and independent replay before BLOCKED/UNAVAILABLE.

## Scope and preservation

- Reused the committed T15 source capability gate and existing synthetic alternative; no new market-data collection.
- Confirmed the R10 branch and origin tracking state before validation.
- Original WS/REST Raw, Canonical, accepted partitions, manifests, synthetic source trees, .env and credentials were not changed.
- Project200 was not modified.
- Existing unrelated dirty files were preserved and excluded: validation_only_runtime_invariant_checker.py, graphify-out/GRAPH_REPORT.md, graphify-out/graph.json.

## Validation results

- Focused regression suite: 89 passed, 0 failed.
  - S2 accepted-original/source-reconciliation/synthetic provider chain
  - Runtime evidence supervisor and X2 durable latch
  - Virtual S2 session factory
  - WS source capability and REST timestamp provenance
- Python compileall for the relevant runtime/provider/normalizer modules: PASS.
- Scoped Ruff import/unused-import checks (I,F401) on T15 provider/normalizer and provider-test files: PASS.
- git diff --check: PASS.
- A broader Ruff E/F/I scan was also attempted but reported existing style debt (long lines and import issues) across pre-existing files, including virtual_session_factory and previously committed validation modules. No unrelated lint cleanup was made.

## Interpretation

- T15 source-capability gate remains in force: original evidence is not authoritative unless environment, absolute source time, timezone, date resolution and capability are explicitly verified.
- Raw SHA/anchor lineage reconciliation remains useful diagnostic evidence but does not prove source capability or source-time semantics.
- Unverified original evidence must fall through to the provenance-preserving synthetic alternative; lack of original four-leg coverage alone is not an immediate X2 trip.
- Synthetic validation PASS is limited to the tested software/Virtual scope. It does not certify actual KIS/REAL_VTS behavior, account/contract identity, operating thresholds or strategy performance.
- No code change was required in this T16 revalidation; only this versioned validation report was added.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new REST/WS collection, collector restart, strategy order submission, broker cancellation, liquidation, flattening or Runtime stop were executed.

## Next step

Continue validation-only scenario coverage with provenance-preserving synthetic data. Reconcile authoritative contract, account, source-clock, quote, order/fill, fee/tax, margin, tick and tradability fields across the full codebase only after the user connects and separately authorizes the real-account investment API.
