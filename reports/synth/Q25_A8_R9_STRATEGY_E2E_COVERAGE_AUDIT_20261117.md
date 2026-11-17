# Q25 A8 R9 — Strategy 1–9 E2E coverage audit

- Date: 2026-11-17
- Status: COVERAGE AUDIT / VALIDATION ONLY; integrated 1–9 E2E is NOT COMPLETE
- Worktree: `C:\Users\white\Desktop\MovingProject\Q25_A8_R9`
- Branch: `work/q25-a8-r9-integrated-e2e-20261117`
- Base: `9f17b828884494cb31988ff5d0a9d92d9d55ff19`

## 1. User priority applied

The immediate objective is full pre-investment E2E correctness across Strategy 1–9 and the shared runtime, not numerical optimization. Threshold tuning is deferred unless a value is required to construct a clearly labelled deterministic validation scenario. Synthetic data remains validation-only and cannot certify real market execution, account profitability, or Live readiness.

## 2. Existing evidence coverage

| Strategy | Existing evidence found | Current E2E assessment |
|---|---|---|
| S1 | Validation-only natural signal/runtime-input tests; R2 integrated strategy evidence | PARTIAL — revalidate full current-baseline entry/exit and common account reconciliation |
| S2 | Market-calibrated synthetic 4-leg entry; 4/4 virtual fills; U18 stop/trailing components | PARTIAL — Runtime exit lifecycle remains NOT_CERTIFIED due policy denominator/entry-direction mismatch |
| S3 | Spec/guard tests; enabled/capital/authoritative spread identity gates | GAP — no positive full Runtime entry-to-flat E2E evidence |
| S4 | Spec/guard tests; disabled without explicit capital and aggregate risk gate | GAP — no positive full Runtime entry-to-flat E2E evidence |
| S5 | Existing-position seed/close path and StrategyHub close E2E; current new-entry gate remains fail-closed | GAP — latest user policy (Option BUY 1, then opposite Option BUY 1 on adverse reversal) is not implemented end-to-end; current code/manifest still retain legacy Futures-5 behavior and Futures-first close logic |
| S6 | Validation-only execution and R5 rank/matrix/flat-state evidence | PARTIAL — re-run against one common all-strategy integration build and account/portfolio reconciliation |
| S7 | Validation-only contract/expiry adapter and prior sequential-entry, cancel/reconcile, fee-aware Runtime evidence | PARTIAL — revalidate complete current-baseline entry/exit and exact expiry handling in integrated suite |
| S8 | Natural Runtime entry, multi-contract partial fills, PositionGroup/PositionLot reconciliation, fees and terminal-close tests | PARTIAL — include in cross-strategy shared-capital and conflict scenarios |
| S9 | Independent overnight policy, process-restart retry restore, one-leg reject/partial-fill recovery and next-session close | PARTIAL — include in cross-strategy shared-capital and restart/reconciliation scenarios |

Prior PASS records are retained as component evidence only; they are not added together to claim 9/9 integrated E2E PASS.

## 3. R9 baseline test results

The following suites were run on this isolated worktree. Counts overlap and must not be summed as unique tests.

- Common registry/caller-edge/freshness/order/partial-fill/position/close/S9 lifecycle suite: **61 passed**.
- Strategy 1–9 core specification and Track3/4/5/7/9 application guard/source suite: **94 passed**.
- Selected strategy validation-only runtime/adapter/E2E modules (S1/S2/S5/S6/S7/S8/S9): **39 passed**.
- `git diff --check`: PASS.

A broader directory-wide pytest attempt exceeded the 30-second command window and showed one failure before timeout; it is not counted as a completed run and no suite-wide PASS is claimed.

## 4. Validation data reuse

The R9 worktree lacked several ignored synthetic datasets required by existing tests. Existing datasets were copied from the original working folder into R9 only:

- `p5_run_20261026_trend_up_seed20261026`: 65 files, 136,779,904 bytes
- `q25_s05_3_s7_concurrent`: 2 files, 323,410 bytes
- `q25_s8_v3`: 4 files, 633,928 bytes

All **71 files** were SHA-256 compared source-to-copy: **0 mismatches**. Copied files were marked read-only. Original working-folder data was not modified. This resolves the missing-fixture errors for the selected tests; it does not add new market observations.

## 5. Key integration gaps

1. No single current-baseline runner yet proves S1–S9 signal → decision → Risk → OMS/Router → VirtualExecution → PositionLot/Group → fee/PnL → exit → terminal reconciliation.
2. No concurrent strategy test yet proves capital reservation, aggregate exposure, duplicate suppression, strategy isolation, and cross-strategy order/close conflict handling.
3. S3/S4 lack positive validation-only lifecycle E2E. Their production gates must remain fail-closed while synthetic test-only gates exercise the common pipeline.
4. S2 entry has synthetic 4/4 fills, but its Runtime exit lifecycle remains NOT_CERTIFIED.
5. S5 is the largest policy/code mismatch: current policy is fail-closed; class/manifest and resolver retain legacy Mini Futures compatibility and futures-first lifecycle. The approved replacement must test initial Option 1 plus conditional opposite Option 1, while preserving close-only handling for any already-open legacy Futures lots. No Futures may be opened by the new S5 path.
6. Existing S7/S8/S9 evidence must be replayed or revalidated through the same integration build rather than assumed current from historical reports.

## 6. Required integrated acceptance suite

- Per-strategy scenario: natural strategy evaluation or an explicitly named validation-only scenario driver; exact strategy identity and source lineage; entry approval and route; fills; position state; exit; flat/terminal reconciliation.
- Multi-strategy scenario: sequential and simultaneous signals through one StrategyHub, one capital/risk account, one OMS/router and one VirtualExecution broker; assert strategy-scoped group/leg/order/execution identity and no cross-strategy position leakage.
- Fault matrix: stale/missing/crossed quote, identity/expiry mismatch, partial fill, rejection, delayed fill, cancel race, retry, process restart, unavailable mark, fee unknown, risk denial, and terminal-close rejection.
- Determinism: fixed seed and manifest; identical FAST/DETAILED final state and order/execution/position trace; reproducible report hashes.
- Safety: synthetic namespace and provenance preserved; production/Live/account/order API disabled; no original Raw/Canonical/manifest mutation; all outstanding orders/positions reconciled or explicitly retained by a strategy rule such as S9 overnight hold.

## 7. Execution boundary

No strategy code, manifest, adapter, Runtime, Risk/OMS, production config, Raw/Canonical source, collector, credential, Live/REAL_VTS/account/order API was modified or called in this audit. No commit or push. The next implementation step is the isolated R9 all-strategy E2E harness and closure of the S3/S4/S5/S2 lifecycle gaps.

## 8. Isolated shared-Runtime integration harness update (2026-11-17)

Added `tests/application/composition/test_q25_a8_r9_strategyhub_shared_runtime_e2e.py`.

- 9/9 standard strategy registry entries are parameterized through one validation-only shared Runtime path: StrategyHub dispatch, Risk approval, OMS/Router, VSSF virtual execution, PositionLot accounting, fee ledger, and terminal close.
- S5 test scenario: one initial option BUY, one conditional opposite-option BUY, then terminal close of both lots. The scenario driver is explicitly test-only; it does not claim the current S5 production strategy implementation has been changed or approved. Legacy Futures close-only behavior is not covered by this scenario.
- S2 test scenario: four-leg entry, sequential progression/position checks, and terminal close. This is a pipeline fixture, not evidence that the production S2 Runtime exit lifecycle is certified.
- Two-strategy shared-account test: concurrent S1/S8 signals, shared capital/account/Runtime, independent strategy-scoped close, and no cross-strategy lot leakage.
- Result: **10 passed** for the new harness.
- Focused combined regression across the new harness, R4 order/multi-leg lifecycle, S9 partial-reject lifecycle, S2 sequential progression, S15B replay equivalence, caller-edge matrix, and S3/S4/S5 spec/provider guards: **99 passed in 22.23s**.
- `git diff --check`: PASS.

### Interpretation and remaining gaps

This is stronger common-pipeline integration evidence, but it is **not yet a claim of complete natural-signal E2E certification for all nine production strategies**. The harness uses a deterministic test-only strategy signal driver for repeatable routing and lifecycle coverage. Natural strategy evaluation, strategy-specific entry/exit policy, restart recovery, capital contention/risk aggregation under broader combinations, and fault-matrix scenarios still require separate evidence. S3/S4 positive validation-only entry/exit scenarios remain to be built. S5 production code still requires a separately reviewed implementation change for Option 1 + conditional opposite Option 1, while preserving close-only handling for already-open legacy Futures positions. No production code or strategy manifest was changed by this test harness.

### Execution boundary

Validation-only synthetic data, deterministic test scenarios, virtual fills only. No Live/REAL_VTS, credentials, account APIs, broker order APIs, real order placement, or new market data collection. Original Raw/Canonical data was not modified. No commit or push performed in this update.

## 9. Decision-first discrepancy handling and next validation pass (2026-11-17)

### Mandatory decision/source reconciliation applied

- Read Notion No.1534 before classifying any source/data mismatch. Its inventory distinguishes WS Raw frames, parsed execution records, Canonical observations, REST snapshots, KIS Master snapshots, expiry-cache evidence, and synthetic datasets; counts and authority are not interchangeable.
- Read confirmed decision No.1554: use existing accepted data first; keep synthetic contract identity and complementary observations in explicit `SYNTHETIC_CONTRACT:` / `SYNTHETIC:DERIVED_SCENARIO` namespaces with source anchors, deterministic generation, manifest and SHA-256. Synthetic evidence validates software/Virtual Runtime only and cannot establish real KIS identity, account/broker facts, Production or Live readiness.
- Read No.1538: market-calibrated synthetic construction must use observed anchors where available, no future observations, preserve anchor age/substitution/depth-proxy provenance, and keep generated quote time distinct from source-observation time. Its prior S2 entry PASS does not certify the unresolved U18 Runtime exit lifecycle.
- Therefore a discrepancy is first classified and cross-checked against Notion decisions and original Raw/Canonical/REST/Master/expiry/manifest lineage. Only unresolved critical identity, event-time, provenance, or validation requirements justify BLOCKED/UNAVAILABLE. Do not treat a missing file/path or one incomplete snapshot as proof that the underlying data does not exist.

### S3/S4 strategy evidence review

- S3 v0.3 remains DRAFT / UNVERIFIED / UNAPPROVED. Its calendar-spread proposal does not supersede the historical Futures-index basis decision; tradable near/far leg identity, payoff, units, costs, account risk, and recovery are unresolved. The current multi-leg adapter correctly rejects undefined spread legs and same-identity opposite-side pseudo-spreads. No production guard was bypassed to force a positive test.
- S4 v0.3 remains DRAFT / UNVERIFIED / UNAPPROVED and disabled by default. A configured hedge quantity alone does not establish option-lot ownership, authoritative Greeks/multiplier, capital/margin/max-loss, or aggregate-risk approval. Tests retain disabled/null and missing-cap gates; no synthetic values were promoted to production config.
- Positive S3/S4 runtime scenarios remain a separate validation-only implementation task. They may exercise the common pipeline only through an explicit test-only scenario/profile boundary, while preserving production activation, identity, capital and aggregate-risk guards.

### Additional focused regression

Command: `py -m pytest -q tests/application/composition/test_q25_a8_r9_strategyhub_shared_runtime_e2e.py tests/application/test_track3_spread_leg_definition_block.py tests/application/test_track4_configured_hedge_cap.py tests/core/test_track3_spec_alignment.py tests/core/test_track4_spec_alignment.py tests/application/composition/test_freshness_restart_recovery.py tests/application/composition/test_authoritative_option_quote_freshness_provider.py tests/application/composition/test_track2_sequential_runtime_progression.py tests/application/composition/test_s9_partial_reject_runtime_e2e.py tests/verification/test_q25_a5_s15b_option_runtime_e2e.py tests/application/composition/test_fresh11_caller_edge_matrix_e2e.py`

- Result: **80 passed in 5.39s**.
- Includes S3/S4 spec and production-guard checks, authoritative quote freshness, restart-after-gap recovery, shared Runtime 9-strategy harness, S2 sequential progression, S9 partial-reject recovery, S15B replay parity and caller-edge matrix.
- The separate new shared-Runtime harness was also independently rerun: **10 passed in 5.17s**.
- Earlier focused combined regression result remains **99 passed in 22.23s**; test counts across suites overlap and must not be summed as unique tests.

### Next implementation boundary

1. Build S3/S4 validation-only scenario adapters only after source/spec inventory; keep production strategy gates unchanged and label all synthetic identity/quotes.
2. Extend the common shared-account harness with risk-denial, stale/mismatched-identity and restart/reconciliation fault cases, reusing existing authoritative freshness/recovery contracts rather than duplicating or weakening them.
3. Revalidate S2 exit lifecycle and S5 option-only production policy separately; retain S5 legacy Futures close-only compatibility.
4. When a real-account investment API is separately connected and authorized, perform field-by-field full-codebase reconciliation for contract identity/expiry/multiplier/tick/tradability, quote source/time, order/cancel/fill, fees/tax, balance/margin and account risk. Until then use observed + provenance-preserving synthetic validation inputs only.

### Execution boundary

Validation-only and virtual execution only. No KIS Live/REAL_VTS/real-account/order API calls, no collector/new data collection, and no Raw/Canonical/accepted source mutation. This report does not certify all nine production strategies as natural-signal E2E complete or approve investment/live operation.

## 10. No.1534 source-anchor discrepancy reconciliation (2026-11-17)

- The R9 isolated worktree contained the existing `DERIVED_SCENARIO` dataset manifest, but its declared KRX source anchor `data/historical/krx_raw/20261008_options_daily.json` was absent from that worktree. This was not treated as immediate data failure.
- Checked the original working folder `C:\Users\white\Desktop\MovingProject\KOSPI200_Project` before classifying the gap. The source anchor existed there and its SHA-256 exactly matched the manifest declaration: `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`.
- Copied that exact source anchor into the isolated R9 worktree only, marked the copy read-only, and verified source-to-copy SHA-256 equality. Size: 5,324,345 bytes. Original source file was not changed.
- Strengthened the shared Runtime harness fixture to validate the dataset manifest's `DERIVED_SCENARIO` provenance, dataset identity, declared source-anchor presence and SHA-256 before replay. If the dataset or anchor is absent in another checkout, the fixture reports an explicit pytest skip requesting original-source reconciliation rather than falsely treating the missing local copy as proof of invalid source data.
- Re-run after the change: shared Runtime harness **10 passed in 4.61s**.
- The source anchor copy is ignored validation data and is not committed. Only test code and the audit report are eligible for the isolated branch commit.
