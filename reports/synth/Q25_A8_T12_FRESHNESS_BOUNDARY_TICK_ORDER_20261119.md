# Q25 A8 T12 — Freshness Boundary, Duplicate and Time-Order Integrity

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: S2 evidence-only Virtual replay; order execution disabled

## Implementation

- T7 candidate scope now checks the exact underlying anchor when a tick shares the candidate timestamp. A same-time underlying mismatch is rejected with T7_TICK_UNDERLYING_ANCHOR_MISMATCH.
- A candidate tick earlier than the synthetic scenario anchor is rejected with T7_TICK_PRECEDES_SYNTHETIC_SCENARIO.
- Provider-specific diagnostics are retained by the T5 supervisor rather than reduced to a generic exception type.
- Exact duplicate tick snapshots remain idempotent in the append-only U19 SQLite recovery store. Duplicate events do not reset or trip an otherwise healthy X2 latch.
- A tick at exactly 5 seconds remains FRESH under the configured <=5s acceptance boundary; a tick at 6 seconds is STALE and trips X2.
- Repeated stale ticks keep X2 TRIPPED and do not add duplicate reasons or side effects.

## Actual isolated Virtual sequence

Run ID: SYNTHETIC:S2_T12_BOUNDARY_20261119

Sequence:
1. 09:26:00 — EVIDENCE_VALIDATED_NO_EXECUTION
2. Exact duplicate 09:26:00 — EVIDENCE_VALIDATED_NO_EXECUTION (idempotent)
3. 09:26:05 — EVIDENCE_VALIDATED_NO_EXECUTION (exact 5-second boundary accepted)
4. 09:26:06 — BLOCKED; X2 TRIPPED with MARKET_DATA_FRESHNESS_NOT_FRESH:STALE
5. Repeated 09:26:06 — BLOCKED; same X2 reasons and persistent state

All events report order_routing=NOT_INVOKED. X2 side-effect flags for cancel, flatten and runtime stop remain false.

## Additional deterministic checks

- Same timestamp + changed underlying anchor: X2 trips with T7_TICK_UNDERLYING_ANCHOR_MISMATCH.
- Tick timestamp one second before the scenario anchor: X2 trips with T7_TICK_PRECEDES_SYNTHETIC_SCENARIO.
- Repeated stale event: X2 remains TRIPPED; SQLite persistence and latch confirmation remain true.

## Validation

- Combined T5-T12/X1/X2/U19/FRESH31/freshness regression suite: 181 passed, 0 failed.
- Actual five-event Virtual sequence: PASS.
- compileall: PASS.
- Ruff on changed provider/test files: PASS.
- Ruff critical syntax/undefined-name checks on modified runtime/session files: PASS.
- git diff --check: PASS.

## Boundaries and next step

- The 5-second boundary is the configured synthetic validation threshold, not an asserted real KIS production SLA. Actual source freshness limits will be field-matched after the real account/market API is connected.
- No strategy, decision, order, cancel, liquidation, Live/REAL_VTS, account/order API, new collection or collector restart.
- No.1534 and No.1535/1538/1554/1555 reconciliation/provenance rules remain mandatory. Synthetic contract/quote data remains validation-only.
- Next T13: verify source timestamp versus receipt timestamp provenance and timezone/clock-skew handling across accepted WS/REST partitions, without enabling order execution.
- Existing unrelated T2 invariant-checker working diff and Graphify outputs remain uncommitted and preserved.
