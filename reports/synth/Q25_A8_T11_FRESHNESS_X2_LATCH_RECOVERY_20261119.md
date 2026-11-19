# Q25 A8 T11 — Freshness Expiry, Durable X2 Latch and New-Run Recovery

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: isolated S2 evidence-only Virtual replay; order execution disabled

## Implementation

- ValidationOnlyS2CandidateTick carries the explicit S2 candidate_id so later ticks in the same candidate scope are still evaluated instead of being treated as unrelated ticks.
- T5 supervisor retains the latest X1 report, U19 decision and freshness verdict when a candidate is rejected. X2 receives the actual stale verdict rather than generic unavailable evidence, and provider attempts include FRESHNESS_NOT_FRESH:STALE.
- X2 remains append-only with no reset API. No automatic reset, broker cancellation, liquidation, flattening, or RuntimeController stop was added.
- Recovery is a separate new validation run ID with a fresh per-run X2/U19 state store after evidence revalidation. The prior run's TRIPPED latch remains unchanged.

## Actual multi-tick Virtual replay

Old run: SYNTHETIC:S2_T11_FRESHNESS_20261119C
- Tick 1 at 09:26:00 KST: EVIDENCE_VALIDATED_NO_EXECUTION; X1 PASS; U19 FLAT_CONFIRMED; X2 ARMED.
- Tick 2 at 09:26:06 KST: source age exceeds the approved 5-second scenario freshness threshold; event BLOCKED.
- X2 reason: MARKET_DATA_FRESHNESS_NOT_FRESH:STALE.
- Durable state after trip: persistence_confirmed=true; latch_confirmed=true; reset_supported=false.
- Reopening a new X2 instance against the same SQLite state store returns TRIPPED with persistence and latch confirmed.
- Side-effect flags remain false: cancel_orders_requested, flatten_positions_requested, runtime_stop_requested.

New recovery run: SYNTHETIC:S2_T11_RECOVERY_20261119C
- Fresh candidate revalidation succeeds: U19 FLAT_CONFIRMED, X1 PASS, X2 ARMED.
- Event EVIDENCE_VALIDATED_NO_EXECUTION; order_routing NOT_INVOKED.
- The old run remains TRIPPED; the new run does not clear or overwrite the old latch.

## Validation

- Combined T5-T11/X1/X2/U19/FRESH31/freshness regression suite: 178 passed, 0 failed.
- Actual two-tick freshness-expiry + same-store reopen + new-run recovery: PASS.
- compileall: PASS.
- Ruff on changed provider/test files: PASS.
- Ruff critical syntax/undefined-name checks on modified runtime/session files: PASS.
- git diff --check: PASS.

## Boundaries and next step

- This verifies a single candidate's 0-second and 6-second freshness behavior; exact 5-second boundary and repeated/out-of-order tick cases remain for T12.
- Recovery is intentionally a new run with new evidence and new state store. There is no API to clear an old X2 latch.
- No strategy, decision, order, cancellation, liquidation, Live/REAL_VTS, account/order API, new collection, or collector restart.
- No.1534 and No.1535/1538/1554/1555 references remain mandatory. Synthetic quote and broker evidence remain validation-only until real account API standards are connected and mapped field-by-field.
- Existing unrelated T2 invariant-checker working diff and Graphify outputs remain uncommitted and preserved.
