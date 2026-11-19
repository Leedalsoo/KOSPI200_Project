# Q25 A8 T5 — X1/U19/Freshness Evidence Supervisor

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only Virtual Runtime

## Decision and evidence policy

- Mandatory Notion No.1534 was reviewed before implementation. Existing accepted inputs and scenario assets were inventoried; no Raw, Canonical, Manifest, accepted dataset, or source file was copied, overwritten, or regenerated.
- No.1535 and No.1555 policy was applied: existing observations are preferred; discrepancies are reconciled against Notion decisions and original-source lineage before deterministic, provenance-preserving alternatives are considered.
- Provider order is mandatory: (1) accepted/original evidence, (2) Notion + source-lineage reconciliation, (3) provenance-preserving alternative evidence, normally deterministic synthetic data.
- Synthetic candidates must pass X1 provenance checks: SYNTHETIC: / SYNTHETIC_CONTRACT: namespace, deterministic rule ID, source manifest SHA-256, source-anchor refs, evidence refs, timezone-aware anchor/scenario timestamps, and no future source anchor. Synthetic facts are not promoted to KIS/account/Production/Live facts.
- U19 must return RESTORE_ALLOWED or FLAT_CONFIRMED, with no pending orders and all validation-only side-effect flags false. Freshness must be FRESH; RiskGuard evidence is checked in the same evaluation.
- X2 is evaluated only after a candidate passes X1/U19/freshness, or after every evidence path is exhausted. Only then does unresolved evidence trip the durable X2 latch. A mismatch does not immediately stop the run while reconciliation/alternative providers remain.
- If all candidates fail, X2 records the exhausted-attempt details and blocks new order admission. No order cancellation, liquidation, flattening, RuntimeController stop, Live control, or account/order API is added.

## Implementation

- Added ValidationOnlyRuntimeEvidenceSupervisor and immutable candidate/result contracts.
- Added the per-tick hook at the beginning of AutomatedVirtualTradingLoop.on_tick, before pending multi-leg processing or order admission.
- Added optional dependency injection through attach_standard_automated_loop and create_virtual_run_session.
- Factory validation requires the supervisor and runtime to share the exact same X2 stop-switch instance.
- Existing X1 invariant checker, U19 recovery coordinator, freshness verdict, RiskGuard, and X2 durable latch are reused; no duplicate risk decision engine was introduced.
- Evidence providers are intentionally injected. The current default Virtual session does not fabricate a provider or claim an authoritative quote/account source when none is connected.

## Reusable input inventory

- Worktree contains accepted Runtime v2 partitions for 2026-10-12/13 and their manifest under data/accepted_market_data/runtime_v2.
- Worktree contains the recovered four-leg market-calibrated scenario sidecar and manifests under data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115.
- No.1534 records the broader original WS/REST/KIS Master/KRX inventory. Those source files remain at their original locations and were not modified or recopied by T5.
- Actual contract multiplier, actual account/broker snapshot capability, fee/tax/margin operating values, and official source-time/freshness thresholds remain unverified. The real-account investment API is not connected.

## Validation

- Focused regression suite: 145 passed, 0 failed.
- py -m compileall -q on all five changed Python modules/tests: PASS.
- Ruff on new supervisor and test: PASS.
- Ruff critical syntax/undefined-name rules on modified runtime/factory modules: PASS.
- git diff --check: PASS.
- Tests exercise primary evidence absence, reconciliation-first fallback, synthetic alternative fallback, exhausted reconciliation with durable X2 trip, and per-tick hook invocation.

## Boundary and next work

T5 establishes the evidence-supervision seam and per-tick hook. It does not yet connect a concrete per-run adapter to the existing VSSF settlement store, accepted market-data manifests, and source-backed freshness records. That adapter is the next implementation task. Until then, the supervisor is activated only when explicitly injected with all three evidence providers. No Live/REAL_VTS/account/order API or new collector activity occurred.
