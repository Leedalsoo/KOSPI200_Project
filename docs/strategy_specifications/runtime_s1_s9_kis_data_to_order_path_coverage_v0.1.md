# Strategy 1–9 KIS Data-to-Order Path Coverage v0.1

- Date: 2026-10-15 KST
- Status: **Read-only audit and proposed implementation/test scope; NOT APPROVED for implementation**
- Authority: No.1274 integrated baseline; repository `AGENTS.md`; current `Project200` source tree.
- Worktree baseline: branch `Project200`, HEAD `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`. Existing worktree already has 130 status entries; preserve all existing changes/deletions/untracked files.
- Safety boundary: no strategy/source code changes, no test restoration, no KIS API or WebSocket retries, no order endpoint, no LIVE order, no Git stage/commit/push.

## 1. Executive finding

The repository contains a common **Virtual automated trading** path from `bootstrap.bundle.market.subscribe(loop.on_tick)` through `StandardRuntimeInputProvider`, strategy evaluation, `runtime_strategy_to_decision_adapter`, `ExecutionMultiLegResolverRegistry`, `AutomatedVirtualTradingLoop`, `route_from_runtime_authoritative_sources`, `RiskGate.admit_order`, `StandardOrderRouter.register_and_route`, Virtual broker report, execution FSM, and position-group/read models. This is static source-path evidence only, not proof that every S1–S9 is connected to a live KIS stream or that all routes are freshness-gated.

The KIS REST option normalizer currently leaves `MarketObservation.observed_at=None` and `raw_reference=None`; `aspr_acpt_hour` is time-only. The common runtime risk-router function does not require a typed freshness verdict/provenance object. Therefore the mandatory freshness gate across all S1–S9 final order admission paths is **BLOCKED / NOT_PROVEN**. No absolute source age may be inferred from receive time or a time-only field.

This document describes the existing Virtual composition and proposed freshness scope. It does not assert a KIS Live S1–S9 execution path exists. Existing separate Live futures composition is not evidence of S1–S9 option Live coverage.

## 2. Common path and proof boundaries

1. **Market tick entry:** `application/composition/automated_virtual_runtime_factory.py` subscribes `loop.on_tick` to `bootstrap.bundle.market`. The factory creates `StandardRuntimeInputProvider` with `bootstrap.bundle.market` and injects strategy-specific source ports.
2. **Input construction:** `application/composition/standard_runtime_input_provider.py` composes underlying market state, analytics snapshots, contract/expiry/order-book sources and strategy-specific payloads. KIS-backed and synthetic/virtual sources are conditionally wired by the factory; a source port's name alone is not proof of REAL_VTS evidence.
3. **Strategy evaluation and decision:** `core/strategy/standard_registry.py` registers the strategy plugins. `application/composition/runtime_strategy_to_decision_adapter.py` converts non-NON_EXECUTION signals, rejects duplicate signal IDs, requires an execution proposal, arbitrates candidates and resolves execution plans.
4. **Plan resolution:** `application/composition/automated_virtual_runtime_factory.py` registers S1–S9 resolver IDs in `ExecutionMultiLegResolverRegistry`; strategy-specific resolvers build single/multi-leg plans and resolve contract identities.
5. **Order/risk seam:** `application/composition/automated_virtual_trading_loop.py` constructs the broker command, snapshots account state and calls `application/composition/runtime_authoritative_risk_router_adapter.py::route_from_runtime_authoritative_sources`.
6. **Risk/OMS:** the adapter calls `RiskGate.admit_order`, requires an approval token, then calls `context.order_router.register_and_route`. The function does not currently require a typed source-freshness verdict.
7. **Virtual execution/position:** the loop consumes broker execution reports and applies partial/full fill states to the execution FSM; multi-leg execution uses `core/oms/position_group.py` registries/read models. This does not prove external KIS account/order/position reconciliation.
8. **Separate Live path:** `application/composition/live_runtime_authoritative_composition.py` wires a futures market provider and `LiveReconciler`. Its current graph is not proven to carry S1–S9 option observations to the same freshness gate. Do not treat it as the strategy path under review.

## 3. S1–S9 route matrix (source code inspection only)

All nine rows converge on the common Virtual decision/plan/risk/OMS path described above, through the standard runtime factory and loop when selected. This proves the common code structure, not per-strategy end-to-end coverage, not source freshness enforcement, and not REAL_VTS/LIVE operation. Where the exact KIS source-to-payload lineage is not explicit at the observed composition boundary, it is marked NOT_PROVEN.

| Strategy | Registered ID / strategy-specific input or resolver | Data dependencies visible in current composition | Missing proof / status |
|---|---|---|---|
| S1 | `TRACK1_TAIL_DEFENSE`; `Track1RuntimeInputProvider`; `resolve_track1` | Market state; option delta source; position-lot store; fence-type source; option/hedge identity resolver | KIS origin and timestamp/provenance carried into every S1 signal not proven; mandatory freshness before RiskGate not proven. **BLOCKED** |
| S2 | `track2_asymmetric_trap`; Track2 analytics and multi-leg resolver | KIS-backed `KISTrack2MarketMetricsSource`, `KISVolumeProfileSource`, `KISBasisSource`, option IV/order-book source and option master are wired in non-synthetic composition | End-to-end raw KIS payload → metrics/IV/orderbook → S2 signal/plan lineage and timestamp propagation not proven; WS option book remains blocked under No.1274. **BLOCKED** |
| S3 | `Strategy_3_StatArb`; `Track3RuntimeInputProvider` / `KISTrack3RuntimeInputSource` in non-synthetic composition; futures identity/hedge resolver | Market tick, observed futures identity, hedge identity, expiry source | Provenance/freshness propagation for both legs and synchronization at admission not proven; do not infer two-leg atomic fill. **BLOCKED** |
| S4 | `track4_gamma_scalping`; Track4 analytics and `Track4KisGreeksProvider` | Option position/contract, Greeks provider, futures rebalance/hedge plan | Verified KIS Greeks/IV source semantics and exact quote/position lineage to admission not proven. **BLOCKED** |
| S5 | `track5_gap_divergence`; Track5 analytics, `Track5OptionContractSource`, gap/market input and multi-leg resolver | KIS contract/master path plus underlying/option market and hedge inputs | Freshness/provenance on option and hedge inputs and explicit admission enforcement not proven. Do not substitute Mini Futures 5 contracts for options. **BLOCKED** |
| S6 | `track6_daily_tail_insurance`; Track6 analytics, `Track6OptionContractSource`, `KISTrack6ATMVolatilitySource` in non-synthetic composition | Exact-expiry option contract, volatility/IV, quotes and execution/position state | Absolute source timestamps, leg-to-leg time spread and admission enforcement not proven. **BLOCKED** |
| S7 | `track7_volatility_skew_weekly_insurance`; Track7 analytics, `Track7OptionContractSource`, order-timeout/support-resistance sources and multi-leg resolver | Weekly option identity/expiry, option liquidity/quotes, pending order and fill state | Real VTS WS option quote evidence is absent and user-directed H0IOASP0/H0IOCNT0 retries are prohibited; timestamp provenance and admission gate not proven. **BLOCKED** |
| S8 | `track8_macro_regime_monthly_strangle`; Track8 analytics, `Track8OptionContractSource` and multi-leg resolver | Monthly CALL/PUT identity, IV/quote/analytics and leg execution state | Source timestamp/quote freshness per leg and common gate coverage not proven. **BLOCKED** |
| S9 | `track9_event_overnight_insurance`; Track9 analytics, event/risk sources, IV event materializer, ATM IV source and position/execution read model | S1 short-PUT lot linkage, insurance PUT identity, event/IV/margin/position state | KIS authoritative actual short PUT position and source-time provenance through the signal and final admission not proven; S1 DTE4 vs S9 DTE7 conflict remains blocked pending user decision. **BLOCKED** |

## 4. Proposed exact file scope — requires separate approval

Do not edit these files until KIS source timestamp semantics are documented and the user explicitly approves this scope and test plan. Existing dirty files must be merged narrowly; no whole-file replacement.

### Required candidate files

1. `contracts/types.py` — typed source timestamp, receive timestamp, raw payload reference/hash and provenance fields; inspect and merge around existing uncommitted changes.
2. `contracts/market_data.py` **or** new `contracts/market_data_freshness.py` — exact shared verdict contract (`FRESH`, `STALE`, `UNKNOWN`, `IDENTITY_CONFLICT`, `BLOCKED_SOURCE_CAPABILITY`) with policy version/reason/evidence reference. Choosing existing vs new module is an architecture decision and remains unresolved until review.
3. `infrastructure/kis/kis_rest_market_observation_normalizer.py` — preserve raw REST source field; only parse absolute instant after official semantics are proven; retain unknown when ambiguous.
4. `infrastructure/kis/kis_rest_market_observation_collector.py` — ensure raw payload reference/hash, TR/environment and request/receive clocks survive the collector-to-observation boundary. Do not call the API as part of implementation validation unless separately allowed.
5. `application/composition/standard_runtime_input_provider.py` — carry source provenance/freshness metadata with the specific source-derived inputs; do not infer freshness from a provider name.
6. Strategy source/payload adapters, limited to the fields actually consumed by the strategy: `application/composition/track1_runtime_input_provider.py`, `application/composition/track3_runtime_input_provider.py`, `application/composition/track2_analytics_provider.py`, `track4_analytics_provider.py`, `track5_analytics_provider.py`, `track6_analytics_provider.py`, `track7_analytics_provider.py`, `track8_analytics_provider.py`, `track9_analytics_provider.py`. Prove which paths truly need edits before inclusion; preserve strategy intent and analytics formulas.
7. `application/composition/runtime_strategy_to_decision_adapter.py` — attach/check freshness evidence on the signal/plan path without losing strategy, signal, contract or leg identity.
8. `application/composition/automated_virtual_trading_loop.py` — ensure the selected strategy/leg's freshness evidence reaches the final admission seam and remains associated with each broker command.
9. `application/composition/runtime_authoritative_risk_router_adapter.py` — proposed common mandatory gate before `RiskGate.admit_order`/broker routing; exact ordering and reduction-only policy require architecture review. Current signature does not require freshness evidence.
10. `core/oms/order_router.py` — optional second defensive guard only if review confirms this does not bypass or weaken the existing risk approval-token contract. No broker call unless both gates pass.
11. `core/runtime/reference_execution_pipeline.py` — include only if caller tracing proves any S1–S9 route reaches it; do not assume it is the common seam merely because an earlier draft named it.
12. New tests (exact paths below) and sanitized evidence under `verification/evidence/` — create new files only after approval; do not restore deleted tests.

### Excluded from the current approval request

- Strategy rules, thresholds unrelated to the already approved freshness candidates, Manifest, strategy IDs, contract selection logic, KIS TR subscriptions, H0IOASP0/H0IOCNT0 retries, KIS account/order/modify/cancel calls, LIVE orders, Git index/history and unrelated dirty files.
- `environments/live/market/kis_futures_market_data.py` is a separate Live futures issue; include it only under a separate reviewed scope, not as a substitute for S1–S9 option coverage.

## 5. FRESH-01–14 test/evidence trace plan

Proposed new test files; none is claimed to exist or have run. `tests/` is currently absent and existing deleted tests must not be restored.

| ID | Proposed new test path | Required assertion and evidence |
|---|---|---|
| FRESH-01 | `tests/contracts/test_market_data_freshness_contract.py` | Missing/malformed/date-ambiguous/timezone-ambiguous source time → UNKNOWN; risk-increasing order blocked; broker call count 0. Record raw field, source/receive time, reason and evidence hash. |
| FRESH-02 | `tests/contracts/test_market_data_freshness_age_gate.py` | Source age above approved threshold → STALE and no risk-increasing order. Include policy version and threshold units. |
| FRESH-03 | `tests/contracts/test_market_data_freshness_age_gate.py` | Future skew above approved bound → UNKNOWN/blocked; never clamp negative age into fresh. |
| FRESH-04 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | REST price/book source timestamp mismatch → IDENTITY_CONFLICT or explicit timestamp conflict; no admission. |
| FRESH-05 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | Missing raw payload hash/reference or exact contract identity → blocked; no synthetic fallback. |
| FRESH-06 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Multi-leg source-time spread > 1,000 ms or any stale/unknown leg → entry blocked; per-leg order/fill state preserved. |
| FRESH-07 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | Receive-time spread > 500 ms logged as diagnostic only; never substitutes for source-time age. |
| FRESH-08 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Existing exposure + stale quote: no auto close/reduce/hedge without fresh executable-side quote and reconciled position/order/fill/cancel states; otherwise block/alert. |
| FRESH-09 | `tests/core/oms/test_order_router_freshness_guard.py` | Cancel-pending, cancel race, partial/late fill: no next/replacement leg before terminal order state and remaining exposure reconcile. |
| FRESH-10 | `tests/application/composition/test_freshness_restart_recovery.py` | Fresh quote after gap/restart remains blocked until timestamp, identity, source capability and account/order/position reconciliation pass. |
| FRESH-11 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Parametrize all nine active strategy IDs/resolvers; prove mandatory gate before `RiskGate.admit_order` and broker call. Any unproven/uncovered route must deny by default. |
| FRESH-12 | `tests/core/oms/test_order_router_freshness_guard.py` | Risk gate rejection or missing/invalid approval token → no broker call even when quote is fresh. |
| FRESH-13 | `tests/application/composition/test_freshness_restart_recovery.py` | Deterministic replay/restart with identical input and policy yields same verdict; evidence references survive restart. |
| FRESH-14 | `tests/infrastructure/kis/test_market_data_source_capability_gate.py` | Unsupported/unverified source capability → BLOCKED_SOURCE_CAPABILITY; no relabeling of fixture/replay as REAL_VTS or LIVE. No H0IOASP0/H0IOCNT0 retries. |

Each test must record/verify: strategy ID, signal/plan/order/leg IDs, exact contract identity, source raw timestamp, resolved source instant or UNKNOWN, receive timestamp, source endpoint/TR and environment, payload hash/reference, policy version, verdict/reason, risk decision/token result, broker-call count, execution/fill/cancel state, position reconciliation result, and evidence file hash. Synthetic/replay tests are unit/path evidence only, not REAL_VTS or LIVE proof.

## 6. Timestamp semantics and thresholds

- `aspr_acpt_hour` currently appears as time-only text (example `154500`); absolute date/time, timezone, and event-time semantics are not proven.
- WebSocket `bsop_hour` semantics are also not proven; existing KIS sample evidence marks H0IOASP0/H0IOCNT0 LIVE-only/VTS unsupported. Do not retry those TRs under the current instruction.
- The previously approved numeric candidates (WS age 2,000 ms; REST age 2,000 ms; future skew 1,000 ms; multi-leg source-time spread 1,000 ms; receive-time spread diagnostic 500 ms) remain unapplied until source semantics are documented.
- Risk policy: block new/add/risk-increasing orders for missing/stale/unknown required data. Close/reduce/hedge only if a fresh executable-side quote for the exact contract and reconciled actual position/order/fill/cancel state are all proven; otherwise block and alert/manual intervention.

## 7. Evidence and approval gates

1. Obtain official KIS documentation/support evidence for source field date association, timezone, event/acceptance-time semantics, precision, rollover and environment/TR capability. If not obtainable, absolute source age remains UNKNOWN/BLOCKED.
2. Finish read-only S1–S9 per-strategy input-source/caller mapping, including source class, provider construction, raw payload hash and path to signal/plan. Mark every missing edge NOT_PROVEN.
3. Review existing dirty diffs before selecting final file list; the exact common admission contract module and whether `core/oms/order_router.py` needs a second guard are architecture choices, not decided here.
4. User approval required for the final file list and test plan before any implementation. Approval of this document alone is not implied by writing it.
5. After approval: implement narrowly; run new offline tests with `py`; then static path coverage and controlled replay. Separate approval for any real KIS read-only validation outside existing permitted evidence. No LIVE orders or Git stage/commit/push without applicable approval.

## 8. Current result

- Common Virtual route static trace: **PARTIAL PASS** (common route located; per-strategy runtime coverage not fully proven).
- Per-strategy KIS provenance to final admission: **BLOCKED / NOT_PROVEN**.
- Absolute KIS timestamp semantics: **BLOCKED / NOT_PROVEN**.
- FRESH-01–14: **PLANNED / NOT RUN**.
- Implementation authorization: **NOT GRANTED**.
- Git stage/commit/push and Live orders: **NOT PERFORMED**.

## Freshness trace follow-up — approval packet evidence (2026-10-15 KST)

This is a read-only supplement. It does not supersede approved strategy requirements or authorize code changes.

### Common execution route verified statically
`automated_virtual_runtime_factory.py` → `AutomatedVirtualTradingLoop.on_tick()` → `StandardRuntimeInputProvider` / strategy input providers → `StrategyHub` / `StrategyOrchestrator` → `RuntimeStrategyToDecisionAdapter.arbitrate()` → `ExecutionMultiLegResolverRegistry` → single-order command path or `VirtualMultiLegExecutionBridge.execute()` → `route_from_runtime_authoritative_sources()` → `RiskGate.admit_order()` + approval-token check → `StandardOrderRouter.register_and_route()` → Virtual broker/OMS → execution reports and position reconciliation.

Static route presence is not proof that the KIS saved raw frames feed each strategy. The common admission seam has no mandatory typed source-freshness verdict. Result: source-to-input-to-final-admission freshness enforcement remains **NOT PROVEN**.

### Per-strategy source/input gap (all require a fail-closed result until proven)
- **S1 / TRACK1_TAIL_DEFENSE** — `track1_runtime_input_provider.py`; option delta, position lots, fence and hedge identity. KIS source hash/time lineage into every input/signal not proven.
- **S2 / track2_asymmetric_trap** — `track2_analytics_provider.py`; KIS-backed metrics/volume profile/basis/IV/orderbook/master sources are wired in some non-synthetic composition, but raw-to-analytics-to-plan lineage and timestamp propagation are not proven. Conflicted VTS option WS capability cannot be promoted to an authoritative strategy input.
- **S3 / Strategy_3_StatArb** — `track3_runtime_input_provider.py`; both futures identities/hedge legs and synchronized source-time evidence not proven.
- **S4 / track4_gamma_scalping** — `track4_analytics_provider.py`; KIS Greeks/IV and exact option/hedge input lineage to admission not proven.
- **S5 / track5_gap_divergence** — `track5_analytics_provider.py`; option and hedge input freshness/provenance not proven.
- **S6 / track6_daily_tail_insurance** — `track6_analytics_provider.py`; exact-expiry contract, IV/quote time and leg coherence not proven.
- **S7 / track7_volatility_skew_weekly_insurance** — `track7_analytics_provider.py`; weekly identity and executable quote source remain blocked; saved WS receipt does not establish supported strategy-consumer path.
- **S8 / track8_macro_regime_monthly_strangle** — `track8_analytics_provider.py`; per-leg source provenance and common admission enforcement not proven.
- **S9 / track9_event_overnight_insurance** — `track9_analytics_provider.py`; event/IV/position lineage to admission not proven. Existing S1/S9 DTE/priority conflict remains outside this freshness change and must not be resolved implicitly.

### Timestamp candidate applicability boundary
- The 47,174-record replay supports deterministic same-KST-date joining against stored receive-date context only. The saved REST sample does not prove overnight/session rollover semantics, authoritative trading-date semantics across a year, or absolute event-time semantics.
- Therefore only a **candidate source datetime** may be derived for normal trading-date + valid nonzero HHMMSS records. Do not expose it as verified absolute event time or use it to calculate an order-allowing age verdict until source semantics are resolved/approved.
- `000000`, invalid/missing values, unknown calendar date, date conflict, timezone ambiguity, or ambiguous session/rollover remain `UNKNOWN`. Do not replace with receive time.

### FRESH-01–14 readiness
The v0.3 test table defines the proposed test IDs, paths and expected outcomes. All are **PLANNED / NOT RUN** because `tests/` is absent and existing deletions must remain untouched. Before implementation, create only new tests under the listed paths after scope approval; do not restore deleted tests.

## Session-boundary and timestamp-construction edges (2026-10-15 KST)
- Saved-data replay found 931 valid nonzero REST `aspr_acpt_hour` values before the KIS rolling-calendar start `08:45`, 2,369 after 15:20 through 15:45, and 203 zero values. The pre-session group and zero group remain UNKNOWN under the conservative candidate rule; after-15:20 behavior requires contract/session-specific evidence. No overnight rollover sample exists.
- Within 312 (date, requested-symbol) groups, source time was nondecreasing (0 regressions). This does not prove absolute timestamp semantics.
- Source inspection found date construction from time-only fields in `infrastructure/kis/basis_source.py` (`session_date` + `observed_hour`) and `infrastructure/kis/track2_option_iv_source.py` (`session_date` + `observed_hour`). `infrastructure/kis/historical_observation_sources.py` falls back from `observed_at` to `collected_at`; its replay-only boundary must be verified before classifying it as a production bypass. These are specific source-to-time construction edges to include in FRESH-01/04/07/11 evidence mapping.
- Exact source-to-input lineage and freshness enforcement for all S1–S9 remain NOT PROVEN. No runtime code, tests, Manifest, raw data, or Git index/history were changed by this read-only follow-up.

## Runtime/replay boundary verification (2026-10-15 KST)
- `HistoricalObservationOptionSource` is created by `application/run_hub/virtual_session_factory.py` only when a historical observations store is explicitly supplied. Its `observed_at or collected_at` fallback is replay-time ordering in the inspected path; it is not authoritative source time and must not satisfy runtime freshness.
- `KISTrack2MarketObservationSink` is subscribed to futures/index observations in the historical replay setup when a raw replay file exists; the session date comes from the partition directory. This does not prove live KIS stream delivery to the common S1–S9 runtime.
- `KISTrack2OptionIVObservationSink` call sites found are in `infrastructure/kis/option_historical_capture.py`; no direct runtime-factory hookup was found. Runtime delivery of H0IOCNT0 observations into the instantiated `KISTrack2OptionIVSource` remains NOT PROVEN, affecting S2/S6 input evidence.
- Distinguish historical/replay date construction from a verified live source timestamp contract. No code changed.
