# Q25 A8 T17 — Market-Calibrated Synthetic Four-Leg Evidence Validation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only four-leg synthetic quote provenance, anchor chronology, timestamp scope and freshness boundary.

## Decision reconciliation

- No.1534 is mandatory: inspect and reuse existing Raw/REST/WS/Canonical/accepted/manifest/KIS Master/KRX evidence first; preserve original sources. Raw frames, parsed records and Canonical rows are distinct units.
- No.1535: existing collected data and provenance-tracked synthetic/complementary data are accepted for project verification. Missing fields or coverage do not invalidate an entire dataset; additional data collection remains stopped. Synthetic results are official project verification results only within their stated validation scope.
- No.1537: the actual four-leg quote coverage is insufficient for all target scenarios; do not represent synthetic quotes as actual simultaneous quotes.
- No.1538: market-calibrated synthetic quotes use only prior/equal-time source anchors, preserve anchor IDs/timestamps, generated values and transformation lineage, and remain explicitly synthetic.
- No.1554/1555 and Current Baseline: synthetic data can validate Virtual software behavior but cannot establish authoritative KIS/account identity, multiplier, fee/tax, margin, tradability, Production or Live readiness.
- When evidence is incomplete, reconcile Notion decisions and original source lineage first; use deterministic crosswalk, schema/contract assertions, independent replay and synthetic alternative before declaring BLOCKED/UNAVAILABLE.

## Work performed

Added three regression tests to:
`tests/application/composition/test_validation_only_s2_scenario_alternative_provider.py`

1. Four-leg quote provider returns exactly four synthetic quotes only at the scenario instant; later timestamps receive no quote extrapolation. The quotes retain SYNTHETIC namespace, validation_only flag and explicit non-KIS identity authority.
2. The built evidence retains deterministic rule ID, manifest SHA-256, anchor references and evidence references. Every IV/spread anchor timestamp is at or before the scenario timestamp; anchor observation ID counts match their timestamps.
3. The exact five-second synthetic freshness boundary remains FRESH. Existing six-second stale test remains in the same suite.

No runtime/provider implementation or original dataset was modified.

## Validation results

- Focused combined regression suite: **104 passed, 0 failed**.
  - S2 synthetic four-leg alternative provider
  - accepted-original/source-reconciliation/synthetic fallback
  - Runtime evidence supervisor and X2 durable latch
  - Virtual S2 session factory
  - source capability and REST timestamp provenance
  - market-calibrated quote scenario and Runtime replay
  - synthetic event scenario catalogue
- Python compileall for the changed test: PASS.
- Ruff E/F/I for the changed test: PASS.
- git diff --check: PASS.

## Interpretation

- Four-leg synthetic quote generation remains deterministic and scoped to the declared scenario timestamp.
- Anchor chronology and source-observation ID lineage are now explicitly asserted by regression tests; future anchors are rejected by the provider and independently checked by the test.
- Exact +5s freshness is FRESH; the existing +6s case is STALE. This is a validation profile boundary, not a production risk threshold.
- These tests validate the synthetic/Virtual evidence path only. They do not establish real simultaneous market quotes, official contract multiplier, KIS identity, actual fills, account state, strategy performance or Live readiness.
- Original source gaps continue to use the No.1534 reconciliation-first and No.1535/1538 synthetic-complement path; they do not cause an immediate X2 trip merely because original four-leg coverage is incomplete.

## Git and preservation

- Only the scoped test file was changed for code/test coverage.
- Existing unrelated dirty files were preserved and not staged: `application/composition/validation_only_runtime_invariant_checker.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`.
- Raw/Canonical/accepted partitions/manifests/synthetic source data, .env and credentials unchanged.
- Project200 unchanged.

## Safety boundary

No Live/REAL_VTS/real-account API calls, new market-data collection, collector restart, order submission, correction, cancellation, liquidation, flattening or Runtime stop were executed.

## Next step

Continue T18 validation-only scenarios for order/execution lifecycle edge cases (partial fills, duplicate/late fills, cancel-race, leg mismatch and idempotent replay) using synthetic evidence with explicit group/leg/order/execution lineage. Keep actual fee/tax/margin and account-authoritative fields unverified until the real-account investment API is separately connected and authorized.
