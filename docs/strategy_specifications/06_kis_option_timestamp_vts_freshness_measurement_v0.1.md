# KIS Option Timestamp / REAL_VTS Freshness Measurement Report v0.1

- Date: 2026-10-12
- Status: **BLOCKED for numerical threshold approval; documentation/source inspection and retrospective archive measurement completed**.
- Scope: read-only inspection and documentation only. No strategy/runtime code changed; no REST/WS subscriptions were started or restarted; no KIS order endpoint called.
- Repository: `Project200`, inspected HEAD `7eb9945e29774fb61fd2d07801762871b2506b98`.

## 1. Timestamp field findings

### REST snapshot endpoints

- Existing adapter calls `/uapi/domestic-futureoption/v1/quotations/inquire-price` (`FHMIF10000000`) and `/uapi/domestic-futureoption/v1/quotations/inquire-asking-price` (`FHMIF10010000`).
- Existing normalizer reads `aspr_acpt_hour` from the price row and asking-price `output2`; if both are non-empty, it rejects a mismatch (`KIS_REST_SOURCE_TIMESTAMP_MISMATCH`). It stores the field as an opaque source timestamp string; it does not parse it into a dated timezone-aware timestamp or calculate quote age. REST `collected_at` is a separate client-side timestamp.
- KIS official sample maps `aspr_acpt_hour` to “호가 접수 시간” (quote acceptance time). This supports the field label, but does not by itself prove that the field is an exchange-origin event timestamp, define timezone/date, or establish its precision. Those semantics remain unconfirmed.
- REST price and order-book calls are separate snapshots. Matching timestamp strings is a consistency check, not proof of zero delay or freshness. A REST capture needs request-start, response-received, both payloads, exact contract identity, raw response hash and client clock-health evidence.

### WebSocket frames

- Local adapter supports `H0IOCNT0` (option trade) and `H0IOASP0` (option order book). The official KIS sample names the first two fields `optn_shrn_iscd` and `bsop_hour`; for `H0IOASP0`, `bsop_hour` is followed by five ask prices and five bid prices, then quantities/counts.
- Archived payloads encode `bsop_hour` as `HHMMSS` with no date or timezone. Raw collector records `received_at` as an ISO-8601 UTC timestamp. The source time must be combined with the authoritative session date and interpreted in the KRX/Korea market timezone only after KIS confirms that interpretation. Do not assign UTC to the payload field.
- Current normalizer sets canonical `observed_at` to local frame `received_at`; it preserves `bsop_hour` only as an opaque provenance string. Therefore canonical `observed_at` currently means client receive/collection time, not independently verified exchange event time. Do not calculate source quote age from `observed_at` alone.
- KIS official sample explicitly says index-option WebSocket quote `H0IOASP0` supports live accounts only and does not support simulated trading. This conflicts with a small number of frames labeled as VTS in the local archive. Treat this as a provenance/availability conflict; do not assume those frames prove that VTS option quote streaming is supported.

Official references:
- KIS sample, index-option realtime quote (`H0IOASP0`): https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_futureoption/index_option_realtime_quote/index_option_realtime_quote.py
- KIS sample, REST option/futures asking price and `aspr_acpt_hour` label: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_futureoption/inquire_asking_price/chk_inquire_asking_price.py
- KIS sample, REST inquiry endpoint: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_futureoption/inquire_asking_price/inquire_asking_price.py

## 2. Retrospective archive measurements (descriptive only)

Files inspected: `data/kis_market_data_restart/YYYYMMDD/kis_vts_websocket_raw.jsonl` and corresponding manifests. Raw JSONL parsed without JSON errors on all six dates below. `H0IOASP0` is the option order-book stream; `H0IOCNT0` is the option trade stream.

| Trading date | Raw frame count | H0IOASP0 quote frames | H0IOCNT0 trade frames | Finding |
|---|---:|---:|---:|---|
| 2026-10-01 | 2,537 | 0 | 2,421 | No option order-book frames |
| 2026-10-02 | 87,741 | 178 | 2,935 | All 178 quote frames concern only `B01610A32` |
| 2026-10-06 | 81,717 | 0 | 7,952 | No option order-book frames |
| 2026-10-07 | 174,806 | 0 | 51,517 | No option order-book frames |
| 2026-10-08 | 269,916 | 0 | 171,706 | No option order-book frames |
| 2026-10-12 | 77,310 | 0 | 636 | No option order-book frames |

For the 178 archived `H0IOASP0` records on 2026-10-02, receive-time gaps computed for the same symbol were: minimum 0.147 s, median 4.619 s, p95 238.805 s, maximum 576.946 s. First observed frame was 13:53:18 KST; last was 15:45:00 KST. Comparing payload `bsop_hour` (seconds resolution) with `received_at` converted from UTC to KST gave receive-minus-payload-time: minimum 0.183 s, median 0.656 s, p95 1.224 s, maximum 1.447 s.

These numbers are **not an approved freshness threshold** and do not prove VTS quote availability or a stable feed distribution: one symbol, one date, only 178 frames, large coverage gaps, no verified subscription ACK/provenance, and a conflict with the official sample's “live only / no simulated trading” note. Receive-minus-payload-time combines transport/publication delay, timestamp rounding and local clock offset; it is not a direct measurement of exchange-to-client network latency or host clock skew. The large per-symbol gaps may include quiet markets and missing subscription periods, and cannot be classified without subscription/heartbeat/market-activity evidence.

### Existing editable risk config is not an approved/enforced freshness limit

- The existing untracked `config/risk/option-hedge-risk.v1.json` currently contains `max_quote_age_seconds: 5`. The loader validates this integer, but the same file sets `activation_mode` to `DISABLED_UNTIL_RUNTIME_INTEGRATION`.
- Static search across `core`, `application`, `environments`, `contracts`, `tests` and `config` found no consumer of `max_quote_age_seconds` beyond the config dataclass/loader and the JSON field. Therefore this value is **not proven to be enforced by the quote preflight/runtime path**.
- Do not treat the current 5-second value as a measured or user-approved production threshold. Preserve the existing untracked config untouched; effective operational quote-age policy remains `UNSET/BLOCKING` until measurement, explicit approval, and a separate runtime-enforcement test.

## 3. Required measurement method before selecting limits

1. **Resolve capability/provenance first:** confirm from KIS Developers support/docs whether VTS provides REST option quote snapshots and whether any option WebSocket quote TR is supported in VTS. Record environment base URL, account environment label (never credentials), TR ID, subscription request/ACK, contract symbol and manifest/hash. If only live `H0IOASP0` is supported, do not use live data or credentials without separate explicit user authorization; use VTS REST snapshots if officially supported.
2. **Collect separate clocks:** capture `request_started_at`, `response_received_at` or WS `received_at` using a UTC-aware wall clock plus monotonic clock; preserve raw payload and SHA-256. Record Windows Time/NTP synchronization status and measured local clock offset independently. Never infer clock offset from market event timestamps alone.
3. **Normalize source time:** confirm `aspr_acpt_hour` and `bsop_hour` semantics, date rollover, timezone and precision with KIS documentation or support. Combine source HHMMSS with the exact exchange session date; preserve raw string. Reject missing/invalid time, unresolvable date rollover, future source time beyond the approved clock-skew bound, or conflicting timestamps.
4. **Measure REST and WS separately:** across multiple full trading sessions and multiple listed option contracts, including active/quiet intervals, no-trade periods, reconnects, subscription rotation, market open/close and expiry day. For REST, calculate response duration and source-time age at response; for WS, calculate source-time-to-receive difference, per-contract update intervals, maximum silent gap, reconnect recovery and subscription coverage. Distinguish no market update from a broken feed using independent connection/heartbeat/subscription evidence.
5. **Predeclare threshold acceptance:** report sample count, coverage, per-contract distributions (median/p95/p99/max), gap and disconnect counts, clock-offset distribution, and holdout-session results. Propose separate REST and WS bounds from measured evidence and strategy decision cadence; document false-block rate and stale-data escape cases. Numerical values remain `UNSET/BLOCKING` until user approval.

## 4. Fail-closed test matrix (definition only; tests not run)

| ID | Fixture / fault | Required result |
|---|---|---|
| TS-01 | `max_quote_age_ms` unset/null/invalid | `BLOCKED_CONFIG`; no order adapter call |
| TS-02 | Valid fresh REST snapshot within approved bound | Continue only if all other preflight gates pass |
| TS-03 | REST `aspr_acpt_hour` missing/invalid or REST price/book timestamps conflict | `BLOCKED_TIMESTAMP`; no order adapter call |
| TS-04 | REST request/response timestamps absent or clock health unknown | `BLOCKED_CLOCK_OR_CAPTURE`; no order adapter call |
| TS-05 | WS `bsop_hour` missing/invalid or session date cannot be established | `BLOCKED_TIMESTAMP`; no order adapter call |
| TS-06 | WS source-time age exceeds approved bound | `BLOCKED_STALE_QUOTE`; no new entry/rebuy/roll order |
| TS-07 | WS disconnect, missed heartbeat, reconnect or subscription rotation gap | `BLOCKED_FEED_GAP` until a fresh valid quote and subscription/position reconciliation are confirmed |
| TS-08 | Local clock offset exceeds approved bound or clock sync is unhealthy | `BLOCKED_CLOCK_SKEW`; no order adapter call |
| TS-09 | Future source timestamp outside approved skew, wrong symbol/expiry, crossed or invalid book | `BLOCKED_MARKET_DATA`; no order adapter call |
| TS-10 | No-trade interval with valid connection but no quote refresh | Do not reset age or treat receive time of unrelated frames as quote freshness; block once quote-age bound is exceeded |
| TS-11 | Source capability/provenance says VTS quote stream unsupported or is unresolved | `BLOCKED_SOURCE_CAPABILITY`; do not relabel a live/unknown source as REAL_VTS |
| TS-12 | Fresh quote returns after outage | Require validated source timestamp, exact contract identity, market quality and state/position reconciliation before re-enable |

No executable tests were run in this phase. The matrix is a test specification, not a runtime enforcement claim.

## 5. Current disposition and next gate

- REST field label `aspr_acpt_hour`: **partially confirmed** (“호가 접수 시간”); full source-clock semantics/timezone/precision: **UNRESOLVED**.
- WebSocket `bsop_hour`: field position/name confirmed by official sample; exact source timestamp semantics and VTS quote capability: **UNRESOLVED / CONFLICTING EVIDENCE**.
- Actual VTS option quote update interval/latency: **BLOCKED for acceptance**; only the small retrospective archive sample above can be described.
- `max_quote_age_ms`, `max_receive_source_skew_ms`, separate REST/WS thresholds: **UNSET / BLOCKING**.
- Runtime stale quote/disconnect order-block behavior: **NOT_TESTED**; no code changed.
- No KIS Live orders, no staging/commit/push.

Next step is to resolve VTS option quote capability/provenance and obtain a sufficient, continuous VTS REST quote-snapshot capture (or other officially supported VTS option quote source). Only then measure, propose numeric thresholds and request user approval. Do not proceed to S9 runtime activation based on these retrospective statistics.
