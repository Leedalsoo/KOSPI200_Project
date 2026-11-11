# Q25 A5 S30 — S2 U17/U20 validation-only implementation (2026-11-10)

## Verdict

**PARTIAL_IMPLEMENTATION_PASS / PSB_UNVERIFIED**

User approval No.1510 authorized S2 validation-only code, tests and Virtual Runtime/OMS wiring. This task implemented the parts that can be safely completed without inventing unresolved policy values or authoritative market data. It does not establish S2 Runtime E2E or PSB PASS.

## Worktree and baseline

- Isolated worktree: `Q25_A5_S22_S5_GROUP_CLOSE_20261109`
- Branch: `cleanup/p2-quarantine-20261026`
- HEAD at start/end: `1ea0129131370109344548827780a1e15b2ab414`
- Current Baseline v2 SHA-256: `3FDC91266DE43EAB12EDAC50EB35200F824BC352024D21374F1DB93CD3880CB4`
- AGENTS.md SHA-256: `BC74B5940AC67AC834B563755E5673EC9B8F7F3020392EA478CF738801A20341`
- No commit or push. All implementation changes remain in the isolated worktree.
- Original working folder dirty count remains 224; it was not modified.

## Implemented

### U17 — exact monthly contract identity binding

- `Track2OptionContractSource.nearest_expiry()` now considers only `STANDARD/MONTHLY` identities.
- `select()` excludes weekly and mini series.
- `resolve_identity()` requires exactly one matching monthly standard identity for each expiry/type/strike and a positive multiplier.
- Runtime factory binds all four S2 legs to exact Option Master identities before returning the plan.
- Virtual multi-leg bridge independently rechecks the stored S2 identity against the Option Master, including monthly series, expiry, type, strike and multiplier.
- Missing, duplicate, weekly/mini or multiplier-mismatched contracts fail closed.
- ATM tie-break remains the lower listed strike.
- Actual authoritative KIS master snapshot/tradability evidence was not loaded or called in this task; strike/tick rounding and volatility boundary remain unresolved.

### U20 — sequential entry progression

- S2 group entry plans are retained by the Virtual multi-leg bridge.
- Runtime tick processing invokes S2 progression after pending-order reconciliation.
- Initial and subsequent steps preflight the complete remaining group; only the next progression-approved leg is routed.
- A leg advances after full fill reconciliation.
- A zero-fill cancelled leg advances only after terminal cancellation, no pending order, no group lot and a flat VSSF account position are confirmed.
- The PositionGroup leg remains `CANCELLED`; a final zero-fill leg returns `ZERO_FILL_REPAIR_REQUIRED`, never group-complete.
- Partial fill, reject, cancel-requested, unknown or reconciliation-required states block progression.
- U16 repair/retry/flatten is not inferred or automatically submitted.

## Tests and validation

- S2-focused suite: **44 passed**.
- Adjacent S6/S7/S8/S9/bridge regression suite: **37 passed**.
- Total across the two disjoint selected suites: **81 passed**.
- `py_compile`: PASS for modified runtime, source and test modules.
- `git diff --check`: PASS.
- Graphify code graph updated: 7,710 nodes, 21,591 edges, 399 communities.
- Graphify reported a pre-existing syntax warning in `application/composition/virtual_composition_root.py`; it was not modified.
- No full Runtime E2E, Replay, pytest full-suite, market-data collection or synthetic market data generation was run.

## S25 catalog and manifest

The 30-scenario catalog remains a design inventory: all scenario `execution_status` values remain `NOT_RUN`, and market data remains `NOT_GENERATED`. Guard-only unit-test evidence was added separately; it is not represented as Runtime scenario PASS.

- Catalog SHA-256: `2F3530D42C4CE2115EA8C0E8B2328920EAC3299B558B92C1B0F1A7BB5B65947B`
- Manifest SHA-256: `5E9818AB7AB38449AA8FEB22155BA4485A4F641208D4B20A36213838BCDFFBED`

## Still blocking PSB PASS

1. **U16:** repair/hedge orchestration, pre-retry cancel/fill/position reconciliation, three-retry/120-second enforcement, retry interval and repricing timing, final failure virtual flatten and group block.
2. **U17:** actual authoritative master snapshot and tradability evidence; strike/tick rounding and volatility boundaries.
3. **U18:** MID freshness contract, initial net premium calculation, cumulative fees/slippage accounting, approved stop/trailing ratios, max-profit persistence and group-wide close plan wiring.
4. **U19:** durable restart recovery and broker-position/ledger mismatch adjustment/stop/resume procedure.
5. **U21:** maximum quote age, maximum spread and units, conservative fallback formula/priority and tick rounding.
6. **Integration:** natural-signal four-leg validation-only Runtime E2E, all U16–U21 positive/negative/boundary scenarios, restart/terminal close/flat reconciliation and FAST/DETAILED Replay parity.

## Safety boundary

- KIS API, REAL_VTS, Live, account APIs and actual order submission were not called.
- No real order, cancel or modify operation occurred.
- Runtime validation remains validation-only; no production readiness claim.
- No files outside the isolated worktree were changed.\n