# Market Data Freshness — File Scope and FRESH-01–14 Test Plan v0.3

- Date: 2026-10-15 KST
- Status: **Approval-ready proposal / implementation not authorized**
- Supersedes: v0.2 for current evidence/capability status; v0.2 remains historical.
- Branch/HEAD: `Project200` / `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`.
- Evidence basis: No.1274, No.1275, `runtime_timestamp_calendar_and_vts_ws_reconciliation_v0.2.md`, `runtime_s1_s9_kis_data_to_order_path_coverage_v0.1.md`, `runtime_order_admission_path_coverage_v0.2.md`, and current source inspection.
- Safety: no runtime code, tests, Manifest, account config, raw data or Git index/history changed by this plan. No API/WS/account/order calls, no LIVE orders, no test execution, no deleted-test restoration, no stage/commit/push.

## 1. Corrected evidence that this plan must respect

### REST timestamp/context
- Across 12 REST raw partitions, 47,174 observations were read: 46,971 nonzero `aspr_acpt_hour`, 203 `000000`, zero missing/empty in the inspected payload path.
- All 203 zero values occurred on weekday collection runs at KST 08:29–08:30 and all had zero cumulative volume, best bid/ask and top-level quantities. They are not holiday-only data. The data supports an initial/pre-session/not-yet-populated context, while exact source-time semantics remain unproven.
- For nonzero fields, 42,708 were earlier than the receive second and 4,263 matched it; none was later. Lag ranged 0–2,067 seconds, median 27 seconds. Do not substitute receive time, and do not declare a nonzero timestamp to be fresh or executable without the remaining checks.

### WebSocket capability conflict
- Existing VTS-labelled raw files contain 239,197 `H0IOCNT0` frames across eight partitions, and 178 `H0IOASP0` frames in the 2026-10-02 partition (one symbol). `bsop_hour` matches the KST receive clock within one second for 239,055/239,197 H0IOCNT0 frames and 178/178 H0IOASP0 frames.
- On 2026-10-13 and 2026-10-14, all raw H0IOCNT0 symbols in each day's raw file have a preceding same-TR/same-symbol successful subscribe ACK in the saved control log (53/53 and 44/44 respectively). Earlier raw partitions do not contain control logs; their ACK status is unknown.
- The 2026-10-02 raw manifest identifies `KIS_VTS_WEBSOCKET_RAW`, VTS endpoint `ws://ops.koreainvestment.com:31000`, and `H0IOASP0` in the TR list. Its daily `manifest.json` nevertheless says `collectors.websocket.status=NOT_STARTED` and `daily_status.json` says `session_status=UNKNOWN`. This is a lifecycle/manifest inconsistency; the state record must not be used to erase the raw-frame evidence.
- Official KIS sample documentation labels both TRs LIVE-only/VTS unsupported. Actual saved receipt contradicts that label. Preserve the evidence and mark the capability **CONFLICTING EVIDENCE / NOT RESOLVED**; do not classify raw receipt as nonexistent just because of the docs, and do not claim unrestricted/stable official support or strategy/order use solely from raw receipt. No retries are permitted.

## 2. Current source-path findings

1. `KISRestMarketObservationNormalizer.normalize()` retains time strings in `provenance.source_timestamps` but returns `observed_at=None` and `raw_reference=None`. `MarketObservation` already has optional `raw_reference` and provenance fields, but the current normalizer does not populate a durable raw hash/reference.
2. `automated_virtual_runtime_factory.py` subscribes `loop.on_tick` to `bootstrap.bundle.market`; the loop builds market state from the Virtual market tick. This does not prove saved KIS raw frames are the live input to S1–S9.
3. Historical observation sources can be injected, but the complete KIS raw collector → source → per-strategy input → signal/plan lineage is NOT PROVEN.
4. `route_from_runtime_authoritative_sources()` has no required typed source-freshness verdict; it calls `RiskGate.admit_order()` before routing. The loop's single-order path uses this seam.
5. `VirtualMultiLegExecutionBridge.execute()` validates identity/quote presence and performs per-leg RiskGate preflight, then routes each leg through the same adapter; it does not receive a typed KIS source-freshness verdict. `ExecutionReport.source_freshness` is downstream execution-report metadata, not a pre-admission source-data gate.
6. Common single/multi-leg final-admission freshness enforcement is NOT PROVEN. No runtime test was run in this pass.

## 3. Proposed exact implementation scope (requires separate approval)

### Required shared path
1. **New** `contracts/market_data_freshness.py` — typed freshness/capability evidence contract. Proposed verdicts: `FRESH`, `STALE`, `UNKNOWN`, `IDENTITY_CONFLICT`, `CAPABILITY_CONFLICT`, `BLOCKED_SOURCE_CAPABILITY`. Each verdict must carry reason, policy version, source/TR/environment, exact contract/leg identity and evidence reference/hash. Do not infer source time from receipt time.
2. `contracts/types.py` — narrowly add the typed source-evidence/freshness reference to the existing `MarketObservation` only if needed for propagation; preserve the existing `MarketObservation`, `RawMarketDataReference` and all current dirty changes. Do not repurpose `ExecutionReport.source_freshness` as the market-input verdict.
3. `infrastructure/kis/kis_rest_market_observation_collector.py` — retain source field, endpoint/TR, VTS environment, request/receive clocks, raw ID and exact payload hash through the observation boundary.
4. `infrastructure/kis/kis_rest_market_observation_normalizer.py` — preserve raw source-time values; only parse an absolute source instant if the date/timezone/event semantics are established. Zero/missing fields remain explicit unknown evidence; do not fill with `collected_at`.
5. `infrastructure/kis/historical_observation_sources.py` and `infrastructure/kis/track2_option_iv_source.py` — carry source evidence only along the sources actually consumed by runtime; distinguish raw stored evidence from production subscription/provider state.
6. `core/strategy/contracts.py` and `application/composition/standard_runtime_input_provider.py` — propagate per-input evidence to each StrategyContext without mixing unrelated inputs or treating the VMS tick timestamp as the KIS source time.
7. `application/composition/automated_virtual_runtime_factory.py` — make source construction/injection explicit and verifiable; no silent switch from VMS to KIS, no API/WS call as part of implementation, and no claim that stored frames are connected unless the connection is implemented and tested.
8. `application/composition/runtime_strategy_to_decision_adapter.py` — preserve evidence and exact contract/leg identity through signal and execution-plan resolution.
9. `application/composition/automated_virtual_trading_loop.py` — require the verdict on the single-order path before the shared admission call; missing evidence must fail closed.
10. `application/composition/virtual_multi_leg_execution.py` — require a verdict for every required leg and a group-level coherence result before any leg submission; retain existing risk preflight, partial-fill and reconciliation behavior.
11. `application/composition/runtime_authoritative_risk_router_adapter.py` — require/validate the typed verdict before `RiskGate.admit_order()` and before broker routing for all paths that use this seam. Do not weaken the approval-token contract.
12. Strategy-specific adapter candidates to trace individually: `application/composition/track1_runtime_input_provider.py`, `application/composition/track2_analytics_provider.py`, `application/composition/track3_runtime_input_provider.py`, `application/composition/track4_analytics_provider.py`, `application/composition/track5_analytics_provider.py`, `application/composition/track6_analytics_provider.py`, `application/composition/track7_analytics_provider.py`, `application/composition/track8_analytics_provider.py`, and `application/composition/track9_analytics_provider.py`. These nine files are explicitly in the candidate review list, not automatic edits: include a file in the final patch only when its source-to-input edge requires provenance propagation and its current diff has been reviewed. Do not edit analytics formulas or strategy rules.
13. **New tests only** under `tests/` and sanitized results under `verification/evidence/`. `tests/` is currently absent; existing deleted tests remain deleted.
14. `core/oms/order_router.py` is **not in the initial required scope** because the proposed shared gate is before the common RiskGate/router seam. Reconsider it only if caller coverage proves a bypass or a second guard is needed; do not add it speculatively.

### Existing dirty-file preservation
Already modified among likely boundaries include `contracts/types.py`, REST normalizer/collector, `infrastructure/kis/historical_observation_sources.py`, and `application/composition/virtual_multi_leg_execution.py`; many other repository files are also modified/deleted/untracked. Review their diffs before any future implementation and merge narrowly. No whole-file replacement, test restoration, Manifest edit, or unrelated-file changes.

## 4. New test files and FRESH-01–14 traceability

Initially proposed test paths; this statement is superseded by the 2026-10-15 execution-status correction below.

| ID | New test path | Scenario / expected outcome |
|---|---|---|
| FRESH-01 | `tests/contracts/test_market_data_freshness_contract.py` | Missing, malformed, zero, date-ambiguous or timezone-ambiguous source time → explicit `UNKNOWN`; preserve raw value and market/session context; risk-increasing order denied; broker call count 0. |
| FRESH-02 | `tests/contracts/test_market_data_freshness_age_gate.py` | Once an approved absolute instant and threshold exist, excessive age → `STALE`; no risk-increasing order. |
| FRESH-03 | `tests/contracts/test_market_data_freshness_age_gate.py` | Future source-time skew beyond approved bound → `UNKNOWN`/blocked; never clamp or substitute receive time. |
| FRESH-04 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | REST price/book timestamp mismatch → explicit timestamp conflict; retain both source values and block admission. |
| FRESH-05 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | Missing raw hash/reference, endpoint/TR/environment, or exact contract identity → blocked; no synthetic/local fallback. |
| FRESH-06 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Any stale/unknown/conflicted multi-leg source or spread above approved bound → whole new group blocked before first leg submission. |
| FRESH-07 | `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py` | Receive-time spread is diagnostic only and never substitutes for source-time age/coherence. |
| FRESH-08 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Existing exposure plus stale/missing quote → no auto close/reduce/hedge without fresh executable-side quote for the exact contract and reconciled position/orders/fills/cancels; otherwise block/alert. |
| FRESH-09 | `tests/core/oms/test_order_router_freshness_guard.py` | Cancel pending, partial fill, late fill and replacement race → no duplicate/next leg until terminal state and exposure reconcile. |
| FRESH-10 | `tests/application/composition/test_freshness_restart_recovery.py` | Restart/reconnect after gap → remain blocked until source capability, timestamp, identity and required order/position/fill/cancel state reconcile. |
| FRESH-11 | `tests/application/composition/test_s1_s9_freshness_admission_coverage.py` | Parametrize active S1–S9 IDs/resolvers; prove verdict is mandatory before final admission on single and multi-leg paths; any bypass denies. |
| FRESH-12 | `tests/core/oms/test_order_router_freshness_guard.py` | RiskGate rejection or missing/invalid approval token → no broker call even when data is fresh. |
| FRESH-13 | `tests/application/composition/test_freshness_restart_recovery.py` | Identical evidence + policy version produces deterministic verdict/reason; evidence references survive replay/restart. Fixture/replay is not REAL_VTS/LIVE proof. |
| FRESH-14 | `tests/infrastructure/kis/test_market_data_source_capability_evidence.py` | Preserve raw receipt evidence when same-TR/symbol ACK+frame exists; surface the official-document/runtime-evidence discrepancy as `CAPABILITY_CONFLICT`; detect Oct 2 manifest-vs-raw inconsistency; do not discard frames solely due docs, do not promote to proven stable strategy source without lineage/capability resolution, and never retry H0IOCNT0/H0IOASP0. |

Every test must assert broker-call count, source raw value and verified instant (or UNKNOWN), receive time, exact contract/leg identity, TR/endpoint/environment, payload hash/reference, policy version, verdict/reason, RiskGate/token result, OMS/order/fill/cancel state, and position reconciliation. Source-time age thresholds must not be applied to time-only fields before their absolute semantics are established.

## 5. Numeric candidates and risk policy remain unchanged

- Candidate WS age ≤ 2,000 ms; REST age ≤ 2,000 ms; future skew ≤ 1,000 ms; multi-leg source-time spread ≤ 1,000 ms; receive-time spread ≤ 500 ms diagnostic only.
- These candidates were accepted in principle by the user on 2026-10-14, but that is not runtime implementation approval. They remain inactive until source timestamp semantics are established and the exact file scope/test plan receives separate approval. The REST field's empirical correlation is now better characterized, but absolute source date/timezone/event semantics are not yet proven; second-resolution time strings cannot substantiate sub-second coherence.
- Block new/add/risk-increasing orders when required evidence is stale, unknown, conflicted or wrong-contract. Close/reduce/hedge only with a fresh executable-side quote for the exact contract and reconciled actual position/open orders/fills/cancels. Otherwise block and alert/manual intervention.

## 6. Explicit approval gate

Before implementation, user approval is required for:
1. The exact contract design and verdict states in Section 3.
2. The exact file list, including which strategy-specific adapters need to change after current-diff review.
3. The FRESH-01–14 new test paths and expected outcomes.
4. Confirm that the principle-approved numeric candidates remain applicable once source semantics are established; principle approval does not authorize runtime implementation or expand the file scope.
5. Whether the observed but conflicting VTS option WS capability can be used as a strategy input only after additional repeated-run/field-lineage evidence, or remains blocked from that consumer pending authoritative clarification.

Until approval: no runtime code, tests, Manifest, credentials/account configuration or raw evidence changes; no API/WS retries, account/order requests, LIVE orders, Git stage/commit/push, or deleted-test restoration.

## 7. Current state

- REST calendar/session context across saved records: **PASS for forensic classification**; full annual KIS calendar is not proven by the single rolling response.
- REST absolute source timestamp semantics: **NOT PROVEN**.
- H0IOCNT0 saved receipt across multiple dates: **PASS for receipt**; ACK correlation PASS on Oct 13–14 only.
- H0IOASP0 saved receipt on Oct 2: **PASS for receipt**; ACK evidence absent.
- Official/stable VTS option WS capability: **CONFLICTING EVIDENCE / NOT RESOLVED**.
- Oct 2 collector lifecycle/manifest consistency: **INCONSISTENT**.
- KIS raw → S1–S9 input/signal/plan/final admission: **NOT PROVEN**.
- Overall FRESH-01~14 validation: **PARTIAL / NOT COMPLETE**. The five existing selected test files passed 34 tests; this is not full FRESH-01~14 completion. See the 2026-10-15 status correction below.
- Implementation authorization: **NOT GRANTED**.

## Additional source-field definition evidence (2026-10-15)
- External KIS API schema wrapper labels `aspr_acpt_hour` as quote-acceptance time `HHMMSS`. Treat this as corroborating field-label context only, not an authoritative date/timezone contract. Official KIS realtime samples expose `bsop_hour` but the inspected sample does not define an absolute date/timezone for it.
- Implementation must preserve the raw field and the market/session context. Do not turn a time-only field into an absolute source instant until its date association, timezone and rollover semantics are proven or separately approved as an explicit empirical policy.

## Empirical date-linking candidate — user-approved for next validation (2026-10-15 KST)

- Decision: the user approved the empirical date-linking rule as a **candidate for validation**, not as authorization to activate freshness checks or change runtime code.
- Candidate rule: when the KST trading date is independently established as a normal trading date and the source field is a valid nonzero six-digit `HHMMSS`, combine that KST trading date with the source time to form a candidate source datetime. Preserve the raw time and its evidence lineage. For `000000`, missing/malformed time, unverified/non-trading date, date conflict, or ambiguous session-boundary/rollover context, return `UNKNOWN`; do not substitute receive time.
- Date source for this dataset: `collected_at` is timezone-aware UTC and converts to KST; its KST calendar date matched the containing partition date for all 47,174 records (0 mismatches). This establishes internal date consistency for these files, not an official KIS timestamp contract or an annual exchange calendar.
- Read-only replay of the candidate over the 12 existing REST partitions: 47,174 total; 46,971 valid nonzero HHMMSS values joined to the KST date; 203 `000000` values left UNKNOWN; malformed/missing values 0 in the inspected field path; candidate source datetime later than receive time 0; lag 0.01859–2,067.470727 seconds, median 27.429956 seconds.
- Interpretation: this replay validates deterministic parsing/date association against saved receive-date context only. It does **not** prove that KIS defines `aspr_acpt_hour` as an absolute event timestamp, confirm timezone/session rollover semantics, or authorize freshness-age thresholds. The 203 zero-valued records remain UNKNOWN despite their plausible pre-session context.
- Gate: retain the candidate as an explicit, versioned empirical rule for further validation. Keep source age and final admission BLOCKED/NOT PROVEN until source semantics and exact implementation scope/test plan are separately approved. No runtime code, tests, Manifest, raw evidence, or Git index/history changed; no API calls, LIVE orders, test execution, stage/commit/push, or deleted-test restoration.

## Next validation sequence
1. Validate the candidate date-linking rule against additional saved contexts and any available authoritative KIS/market-calendar evidence without API retries.
2. Trace S1–S9 source-to-input-to-signal-to-plan-to-final-admission edges and map each edge to FRESH-01–14.
3. Submit the exact implementation file list, minimal diff plan, and test matrix for separate user approval. Until then, do not edit runtime code/tests/Manifest.


## Approval-packet clarification — exact boundaries and per-strategy disposition (2026-10-15 KST)

- The existing static coverage documents were re-read alongside the current source files. The common Virtual route exists structurally; it does not prove saved KIS raw-to-S1–S9 runtime lineage.
- The REST normalizer still preserves the source time as a string and returns `observed_at=None` and `raw_reference=None`. The shared admission adapter does not require a typed market-data freshness verdict. Thus all S1–S9 final admission freshness enforcement remains NOT PROVEN.
- Strategy-specific adapters to include only where source-to-input review proves a propagation edge is missing: `track1_runtime_input_provider.py`, `track2_analytics_provider.py`, `track3_runtime_input_provider.py`, `track4_analytics_provider.py`, `track5_analytics_provider.py`, `track6_analytics_provider.py`, `track7_analytics_provider.py`, `track8_analytics_provider.py`, `track9_analytics_provider.py`. No formula/strategy-rule edits are in scope.
- Exact shared candidate boundaries remain as in Section 3: new `contracts/market_data_freshness.py`; narrowly scoped `contracts/types.py`; KIS REST collector/normalizer and consumed historical/Track2 source adapters; `core/strategy/contracts.py`; `application/composition/standard_runtime_input_provider.py`; `automated_virtual_runtime_factory.py`; `runtime_strategy_to_decision_adapter.py`; `automated_virtual_trading_loop.py`; `virtual_multi_leg_execution.py`; `runtime_authoritative_risk_router_adapter.py`. Every pre-existing dirty file requires diff review and minimal merge. `core/oms/order_router.py` is excluded unless call-graph evidence identifies a bypass.
- The initial per-ID status is superseded by the execution-status correction below. Reuse the existing selected test files; do not restore deleted tests.
- Candidate time join is **not** an executable freshness verdict. Current evidence does not include overnight/rollover cases or authoritative KIS source-time contract; source age and admission must stay blocked/unknown until resolved.
- No runtime code/tests/Manifest/raw data were changed, no tests/API/WS/account/order calls were run, and no Git stage/commit/push was performed.

## Session-boundary evidence and candidate-rule tightening (2026-10-15 KST)

- Read-only replay against saved KIS rolling-calendar evidence (`s_time=084500`, `e_time=154500`) found 931/46,971 nonzero `aspr_acpt_hour` values before 08:45 KST. These are not eligible for an unconditional date join: FRESH-01 must expect `UNKNOWN` for pre-session or otherwise ambiguous session-boundary observations unless the exact product/TR has authoritative pre-session semantics. Never replace the source time with `collected_at`.
- 43,671 nonzero values are in 08:45–15:20; 2,369 are after 15:20 through 15:45; 203 values are `000000`. The after-15:20 group requires contract/session-specific boundary evidence and must not be generalized from one date's observed last record. There is no overnight/rollover evidence in the saved partitions.
- Per-symbol consistency check: 312 (partition date, requested symbol) groups, zero within-group `HHMMSS` regressions. Cross-symbol global ordering is not a valid invariant. This does not establish absolute timestamp semantics.
- Revised dataset classification for validation only: 46,040 in the general KIS window remain candidate date joins; 931 pre-session + 203 zero = 1,134 UNKNOWN. The 46,040 are not verified absolute instants and cannot activate age thresholds.

### Exact source-file names found in the current worktree (approval candidates, not an approved patch)
- Freshness contract location is an unresolved architecture choice: either a new `contracts/market_data_freshness.py` or a minimal extension of `contracts/market_data.py`; choose only after explicit approval.
- Shared observation/runtime candidates: `contracts/types.py`, `core/strategy/contracts.py`, `application/composition/standard_runtime_input_provider.py`, `application/composition/automated_virtual_runtime_factory.py`, `application/composition/runtime_strategy_to_decision_adapter.py`, `application/composition/automated_virtual_trading_loop.py`, `application/composition/virtual_multi_leg_execution.py`, `application/composition/runtime_authoritative_risk_router_adapter.py`.
- KIS timestamp/provenance candidates: `infrastructure/kis/kis_rest_market_observation_collector.py`, `infrastructure/kis/kis_rest_market_observation_normalizer.py`, `infrastructure/kis/kis_websocket_market_observation_normalizer.py`, `infrastructure/kis/historical_observation_sources.py`, `infrastructure/kis/basis_source.py`, `infrastructure/kis/track2_option_iv_source.py`, `infrastructure/kis/track2_market_observation_sink.py`, `infrastructure/kis/track2_option_iv_observation_sink.py`, and `infrastructure/kis/track2_market_metrics_source.py` only where a proven consumer edge requires verdict propagation.
- Actual code inspection found two time-only-to-datetime joins taking an injected `session_date`: `KISBasisSource.update_futures_observation()` in `infrastructure/kis/basis_source.py` and `KISTrack2OptionIVSource._observed_at()` in `infrastructure/kis/track2_option_iv_source.py`. This establishes where date association occurs, not that the supplied date is authoritative or that rollover is handled.
- `HistoricalObservationOptionSource` currently uses `observation.observed_at or observation.collected_at`; this is a receive-time fallback candidate that must be scoped and tested before any change. Its replay-only consumer boundary must be verified before treating it as a runtime bypass.
- FRESH-01 must cover pre-session `UNKNOWN` and `000000` `UNKNOWN`; FRESH-02/03 may run only after a verified/approved absolute-time policy exists. Remaining per-ID status is specified in the 2026-10-15 correction below.
- Existing dirty files `contracts/types.py`, `infrastructure/kis/kis_rest_market_observation_collector.py`, and `application/composition/virtual_multi_leg_execution.py` have pre-existing diffs and must be reviewed/merged minimally; do not overwrite them. `core/oms/order_router.py` remains excluded unless caller tracing proves a bypass.

## Runtime/replay boundary correction (2026-10-15 KST)
- `HistoricalObservationOptionSource` is constructed in `application/run_hub/virtual_session_factory.py` only for an explicitly supplied historical observations store. Its `observed_at or collected_at` fallback is replay-time ordering only in the inspected caller; it must not satisfy a runtime source-freshness verdict or be relabeled as source time.
- `KISTrack2MarketObservationSink` receives futures/index observations through subscriptions in the historical replay setup when a raw replay file is present; `session_date` is taken from the partition folder. This is not evidence of a live KIS source-to-runtime edge.
- `KISTrack2OptionIVObservationSink` repository call sites were found in `infrastructure/kis/option_historical_capture.py`, but no direct hookup was found in the runtime factory. Although `KISTrack2OptionIVSource` is instantiated there, runtime H0IOCNT0 delivery to it is NOT PROVEN. S2/S6 IV availability and timestamp lineage stay BLOCKED until the actual consumer edge is shown.
- Update the approval packet to distinguish replay-time ordering from source-time freshness. FRESH-01/04/11 must prevent replay/receive timestamps from being accepted as authoritative source timestamps; FRESH-13 must preserve provenance and label replay evidence as replay-only.

## Execution-status correction and remaining validation scope (2026-10-15 KST)

### Reusable PASS baseline — do not rerun
- Command already executed: `py -m pytest -q tests/contracts/test_market_data_freshness_contract.py tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py tests/application/composition/test_s1_s9_freshness_admission_coverage.py tests/core/oms/test_order_router_freshness_guard.py tests/application/composition/test_freshness_restart_recovery.py`.
- Result: **34 passed in 0.17s**. Reuse this as the current selected-test baseline; this instruction does not authorize or require rerunning it.
- Existing PASS test files: `tests/contracts/test_market_data_freshness_contract.py`; `tests/infrastructure/kis/test_rest_market_observation_timestamp_provenance.py`; `tests/application/composition/test_s1_s9_freshness_admission_coverage.py`; `tests/core/oms/test_order_router_freshness_guard.py`; `tests/application/composition/test_freshness_restart_recovery.py`.
- Scope limit: the selected tests prove only the assertions they execute. They do not establish full FRESH-01~14 completion, REAL_VTS/LIVE E2E, absolute REST source-time semantics, or complete KIS raw-to-S1~S9 final-admission lineage.

### Remaining unverified scenarios
- **FRESH-06 — multi-leg first-submit guard.** (a) Exercise the real multi-leg execution entry and every pre-submit admission edge, not only the helper. (b) Supply stale/missing/conflicted per-leg freshness verdicts, invalid source-time spread, and a broker spy recording submit calls. (c) PASS only if the entire group is rejected before the first submit and broker submit count remains zero for every invalid case.
- **FRESH-09 — fill/cancel/replacement race and reconciliation.** (a) Exercise stateful OMS/execution flows for partial fill, late fill after cancel request, terminal cancel, replacement order, duplicate/reordered events, and restart/reconciliation. (b) Supply deterministic event sequences plus order IDs, fill/cancel acknowledgements, and authoritative position snapshots/ledger evidence. (c) PASS only if no duplicate/replacement/next leg or reset occurs before terminal order state and actual exposure reconcile; late fills are included and final position matches the event ledger.
- **FRESH-11 — all S1~S9 call paths and multi-leg bypasses.** (a) Trace and execute every active S1~S9 provider/resolver through signal, plan, single/multi-leg execution, final admission, RiskGate and broker seam. (b) Supply a path inventory tied to concrete caller edges and missing/UNKNOWN/STALE/CONFLICTED verdict fixtures. (c) PASS only if every path requires the typed freshness verdict before final admission and all deliberate bypass attempts result in zero broker submissions.
- **FRESH-14 — capability conflict and Manifest mismatch reproduction.** (a) Add a dedicated isolated test for the documented-vs-raw VTS WS capability conflict and 2026-10-02 manifest/raw lifecycle inconsistency. (b) Use preserved raw receipt/frame hashes, the relevant ACK/control-log evidence (including explicit absence where applicable), official-sample evidence, and the exact historical Manifest/config snapshot; do not reconnect or retry H0IOCNT0/H0IOASP0. (c) PASS only if the conflict and mismatch are reproducibly detected, raw evidence is retained, the source is not promoted to stable strategy capability, and no live retry/subscription action is triggered.
- **Conditional FRESH-01~05, 07~08, 10, 12~13 reconciliation.** (a) Compare each stated assertion with the actual test body and production call path, adding coverage only where a requirement is not actually asserted. (b) Reuse the five-file PASS baseline and inspect assertion-level evidence without rerunning it; additional inputs include raw/source timestamp ambiguity, exact contract identity/provenance, receive-vs-source-time distinction, stale quote with existing exposure, restart state, RiskGate/token failures, and replay provenance as applicable. (c) PASS per ID only when every planned assertion is demonstrated by an existing test or a separately approved additional test; do not mark an entire ID PASS based on file existence or unrelated passing assertions.
- **Explicit dependencies remain BLOCKED / NOT PROVEN:** REST absolute source timestamp/date/timezone/session-rollover semantics; complete KIS raw→S1~S9 input→signal→plan→final admission provenance; official/stable VTS option WebSocket capability. These must not be inferred from the 34-test baseline.

### Scope and approval gate
- This is a plan/documentation-only correction. No source, test, or Manifest file was changed; no tests were executed during this correction; no API/WS/account/order calls, collector stop/restart, or Git stage/commit/push occurred.
- **Overall status: PARTIAL / NOT COMPLETE.** The five-file 34-pass baseline is reusable evidence, not blanket PASS for FRESH-01~14. Implementation authorization remains NOT GRANTED.
- **Approval question:** May I proceed with test design/addition for the above unverified scenarios?