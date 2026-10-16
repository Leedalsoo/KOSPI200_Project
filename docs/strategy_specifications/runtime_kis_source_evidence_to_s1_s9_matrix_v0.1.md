# KIS Source Evidence → Strategy 1–9 Mapping v0.1

- Date: 2026-10-15 KST
- Status: **Read-only evidence matrix; NOT an approved strategy specification or implementation authorization**
- Worktree: `Project200`, HEAD `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`
- Scope: Existing 2026-10-14 KIS VTS evidence, source-to-provider wiring, and S1–S9 admission-path proof.
- Safety: No KIS/API/WS calls, no account/order endpoints, no source/test/Manifest changes, no Git stage/commit/push.

## 1. Actual saved-source inventory

| Existing evidence file | Observed count / status | SHA-256 | What it proves / limitation |
|---|---:|---|---|
| `data/kis_market_data_restart/20261014/kis_vts_websocket_raw.jsonl` | 150,023 raw frames: H0IFCNT0 125,906; H0UPCNT0 23,321; H0IOCNT0 796 | `C8F0DB829DBB5E7D9882B81BB80DD74454D5AEDC987082221F16AC7179EDC812` | Stored raw frames exist. 796 frames are labeled H0IOCNT0 and include B/C option symbols. This does not prove stable VTS capability or complete order-book coverage. |
| `.../kis_vts_websocket_timing.jsonl` | 150,023 timing rows; time-only `source_timestamp_raw` | `EE83389F5996F1189A22D1428C5EF07AEE733F12A54AE3BCD43DE4CA380776E6` | Records source-time strings and collector timing; absolute source instant semantics remain unproven. |
| `.../rest_request_timing.jsonl` | 14,930 rows: HTTP 200 = 14,719; HTTP 500 = 209; TR FHMIF10000000 = 7,514, FHMIF10010000 = 7,416 | `5EA219D9C6FBB4A6A54E80BC233B8A9B516200C5613669380A026CF34C2C6078` | Actual VTS REST request/response evidence and raw response hashes. HTTP 200 alone does not mean usable quote/book or valid source time. |
| `.../historical_market_observations.jsonl.raw.jsonl` | 6,412 records, HTTP 200, TR pair FHMIF10000000+FHMIF10010000 | `E448302D14AA1A4CC4B0BC9D013495301283E1ACC81B324DB1F7A3F6F4153D4A` | Preserved REST raw observations; does not prove strategy consumption. |
| `.../futures_underlying_rest.jsonl` | 289 records, TR FHPIF05030200 | `04F575954F695B91487D1FCA9D815E14BAF9A97800C607D7AF4E363F72F43D28` | Futures board REST data exists in the VTS partition. |
| `.../rest_blocked_diagnostics.jsonl` | 211 diagnostic records | `A7D2E9727A05B207799CAB8F62A1D0448037DE6E1E725A3727ABF896ADD8241F` | Failure/blocked evidence exists; not successful market-data coverage. |
| `verification/evidence/kis_api_capability_probe_20261014.json` | VTS, read-only; order endpoints not called | `6B715779876B26DB4E696BDF4E8729D930960CBD0A7620629036C094676DECEC` | Includes option REST price/order-book field keys and raw response hashes; not timestamp semantics proof. |
| `data/kis_market_data_restart/20261014/manifest.json` | Collector status includes WS evidence count 300,676 | `EAB342154B49CB9602E0D4FF0567C79455186CCE990AEE6275CDC437ACC1DEEF` | Manifest is a collector claim and must be reconciled to underlying evidence files; it is not strategy-path proof. |

## 2. Key source-level findings

1. REST TRs: `FHMIF10000000` (/uapi/domestic-futureoption/v1/quotations/inquire-price) supplies option last price, daily/expiry-related fields, Greeks (`delta_val`, `gama`, `theta`, `vega`) and IV-like fields (`hts_ints_vltl`, `hist_vltl`) in captured responses. `FHMIF10010000` (/uapi/domestic-futureoption/v1/quotations/inquire-asking-price) carries order-book fields and `aspr_acpt_hour`. In sampled saved responses, `aspr_acpt_hour` includes `000000`; price responses can have no source timestamp, and book levels can be all zero. These are not safe executable quotes without further validation.
2. REST normalizer source code: compares price/book timestamp strings, but sets `MarketObservation.observed_at=None` and `raw_reference=None`; preserves the time string in provenance. It does not produce an absolute timezone-aware source instant.
3. REST collector source code: records request start, response receive time, raw response, SHA-256, TR, endpoint, and `source_timestamp_raw`. This capture does not resolve field semantics.
4. WS raw frames: 796 H0IOCNT0 records with option symbols exist in the saved file, but **no H0IOASP0 option order-book raw file is present**. Subscription events record `broker_acknowledgement_status=NOT_VERIFIED_CONTROL_FRAMES_ARE_NOT_CORRELATED_TO_ROTATION`. The official sample/capability notes describe H0IOCNT0/H0IOASP0 as LIVE-only / VTS unsupported, which conflicts with the stored H0IOCNT0 frames labeled in a VTS raw manifest. Treat this as a provenance/capability conflict, not as proof that the TR is supported. Do not retry either TR.
5. The REST and WS time fields are time-only strings. The outer `trading_date`/receive timestamp is collector metadata and does not by itself prove the source field's date, timezone, or event-time meaning.
6. The common runtime risk-router signature accepts command, risk gate, context, sensor snapshot and reduction flag; it has no required typed freshness/provenance verdict. The observed REST normalizer is not proven to feed the common S1–S9 final admission path.
7. The worktree has extensive pre-existing modifications, deletions and untracked files. No runtime implementation or tests were changed in this audit.

## 3. S1–S9 data-to-runtime evidence matrix

| Strategy | Relevant KIS data actually evidenced in saved material | Required route/input boundary visible in source | Result and missing proof |
|---|---|---|---|
| S1 — Track1 tail defense | Option REST last price/Greeks fields and option master identity are present in the broader VTS evidence set; the current-day evidence does not prove a complete S1 quote/position bundle. | Track1RuntimeInputProvider; option delta source; position-lot store; fence type; option/hedge identity → signal/plan → common risk router. | **BLOCKED / NOT_PROVEN**: exact contract/quote provenance and source time are not shown through signal to admission; actual position reconciliation not proven by market-data files. |
| S2 — Asymmetric trap | Option REST price/IV/Greeks and order-book endpoint responses exist; H0IOCNT0 option frames exist, but no H0IOASP0 order-book frames. REST order-book sample includes zero prices/quantities and `aspr_acpt_hour=000000`. | Track2 metrics, volume profile, basis, option IV/order-book, master → S2 analytics/signal/resolver. | **BLOCKED / NOT_PROVEN**: usable executable-side book, authoritative basis/volume lineage, source-time propagation, and common admission gate are not proven. |
| S3 — Statistical arbitrage | Futures WS H0IFCNT0 frames (125,906), underlying H0UPCNT0 frames (23,321), and futures REST FHPIF05030200 (289) are present. | Track3RuntimeInputProvider / KISTrack3RuntimeInputSource; observed futures identity, hedge identity and expiry → multi-leg plan. | **PARTIAL / NOT_PROVEN**: futures data exists, but standard/mini identity, both-leg synchronized provenance and admission freshness are not proven end to end. |
| S4 — Gamma scalping | Option REST Greek/IV fields and futures WS frames exist. | Track4 analytics and Track4KisGreeksProvider; option position/contract plus futures rebalance/unwind. | **BLOCKED / NOT_PROVEN**: KIS Greeks source lineage, exact option position/quote identity and timestamp alignment through admission are not proven. |
| S5 — Gap divergence | Option REST price/Greeks evidence exists; current-day file set does not by itself prove the complete daily open/previous-close input used by S5. | Track5 analytics and Track5OptionContractSource; KOSPI200 daily source, option contract and risk/hedge plan. | **BLOCKED / NOT_PROVEN**: daily reference input provenance and option source freshness to admission need separate exact evidence. Do not substitute Mini Futures for options. |
| S6 — Daily tail insurance | Option REST price/IV/Greeks and master-derived contracts are represented in saved material. | Track6 analytics, Track6OptionContractSource and KISTrack6ATMVolatilitySource. | **BLOCKED / NOT_PROVEN**: exact source field meaning, usable quote/book, leg-to-leg timestamp spread and admission gate remain unproven. |
| S7 — Weekly volatility skew insurance | Weekly option symbols appear in REST evidence; H0IOCNT0 option frames exist. No H0IOASP0 order-book raw file. | Track7 analytics, Track7OptionContractSource, timeout/support-resistance and multi-leg resolver. | **BLOCKED / NOT_PROVEN**: official capability conflict, absent WS order book, executable-side quote validity and final freshness enforcement remain unresolved. |
| S8 — Monthly strangle | Monthly CALL/PUT REST price/IV/Greeks data exists in the saved REST set. | Track8 analytics and Track8OptionContractSource; per-leg contract/quote → grouped plan. | **BLOCKED / NOT_PROVEN**: each leg's source timestamp, quote usability, cross-leg synchronization and admission enforcement are not proven. |
| S9 — Event overnight insurance | Option REST IV/Greeks/price fields exist; these do not establish an authoritative current short-PUT position. | Track9 event/risk inputs, IV event materializer, ATM IV source and position/execution read model. | **BLOCKED / NOT_PROVEN**: actual short PUT position, event-source authority, per-leg freshness and DTE conflict resolution are not proven by these market-data files. |

## 4. Existing file modification status at audit time

- Branch: `Project200`
- HEAD: `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`
- Existing modified: `contracts/types.py`, `infrastructure/kis/kis_rest_market_observation_normalizer.py`, `infrastructure/kis/kis_rest_market_observation_collector.py`, `core/runtime/reference_execution_pipeline.py`, among many other files.
- No modification marker at this check: `application/composition/standard_runtime_input_provider.py`, `application/composition/runtime_strategy_to_decision_adapter.py`, `application/composition/runtime_authoritative_risk_router_adapter.py`, `core/oms/order_router.py`. This is not proof that their behavior is complete; the risk-router code inspected has no required freshness verdict argument.
- `tests/` is absent while Git shows many existing test files deleted. No tests were restored or run in this read-only evidence pass.
- `git diff --check` was previously reported PASS; that does not establish functional correctness.

## 5. Next work and gates

1. Reconcile the stored H0IOCNT0 frame evidence against the official KIS capability statement without retrying H0IOCNT0/H0IOASP0; request written KIS clarification when permitted.
2. Continue read-only source-to-provider tracing for each strategy using exact constructor injection/caller references and separate KIS data availability from strategy-path connectivity.
3. Preserve source-time as UNKNOWN/BLOCKED until official semantics prove date association, timezone, event/acceptance-time meaning, precision and rollover.
4. Prepare a precise file/diff and FRESH-01–14 test plan. No runtime code, tests, Manifest, credentials, API calls or orders are authorized by this report.
5. Update No.1275 with actual results and No.1274 with the current status/pointer. Shrimp state is not claimed updated unless independently verified.



## 6. Official KIS capability evidence (checked 2026-10-15)

Official KIS sample:
https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py

- `index_option_realtime_conclusion` uses `H0IOCNT0`, exposes `bsop_hour`, option price/volume and Greeks/IV-related fields, and explicitly states that only live accounts are supported; simulated trading is unsupported (official sample lines 2984–3005, TR assignment around 3036).
- `index_option_realtime_quote` uses `H0IOASP0`, exposes `bsop_hour`, option ask/bid levels and quantities, and explicitly states that only live accounts are supported; simulated trading is unsupported (official sample lines 3170–3184, TR assignment around 3212).
- This official capability statement is authoritative for the current planning decision unless KIS provides a newer written clarification. The saved VTS-labeled H0IOCNT0 frames conflict with it and must not be promoted to supported VTS input. No H0IOCNT0/H0IOASP0 retry was made.
