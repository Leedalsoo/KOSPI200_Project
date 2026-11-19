# Q25 A8 T13 — WS/REST Timestamp Provenance and Clock-Skew Audit

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: read-only source audit + future-normalizer metadata; no Raw/Canonical/accepted partition rewrite

## Mandatory decision references

- Notion No.1534 was reviewed first, together with No.1424 and No.1535/1538/1554/1555.
- Existing original WS/REST sources and accepted Runtime v2 partitions were inspected in place. No original Raw, Canonical, manifest or accepted data file was modified or regenerated.
- Missing or unresolved REST absolute source time is not treated as immediate project failure. Existing source lineage is retained and unresolved timestamps remain UNKNOWN until date/timezone/session semantics are independently verified.

## WS raw source audit

Source: original `data/kis_market_data_restart/<trading_date>/kis_vts_websocket_raw.jsonl`, six dates.

- H0IOCNT0 parsed records: 235,668 across 235,466 raw frames.
- H0IOCNT0 `BSOP_HOUR` is resolved using the file trading date and Asia/Seoul; raw `received_at` is UTC. Event time and receipt time are kept separate.
- Overall event-to-receipt lag: median 0.565s, p95 1.023s, p99 1.722s, maximum 8.439s; negative lags 0; lags above 5s: 2.
- Per-day median/p95/max seconds:
  - 2026-10-01: 0.612 / 1.021 / 8.439 (2,421 records)
  - 2026-10-06: 0.573 / 1.021 / 8.439 (7,952)
  - 2026-10-07: 0.566 / 1.024 / 8.439 (51,517)
  - 2026-10-08: 0.564 / 1.023 / 8.439 (171,706)
  - 2026-10-12: 0.495 / 1.024 / 2.649 (686)
  - 2026-10-13: 0.612 / 1.037 / 4.393 (1,386)
- No H0IOASP0 order-book WS frames were present in the six audited raw files. This remains a feed-coverage gap; it is not filled by relabeling H0IOCNT0 trade ticks as order-book events.

## Accepted Runtime v2 lineage

- 2026-10-12: 686 rows; source/receipt lag median 0.495s, p95 1.024s, max 2.649s; no negative or >5s lag.
- 2026-10-13: 1,386 rows; median 0.612s, p95 1.037s, max 4.393s; no negative or >5s lag.
- Every accepted row's `tick.timestamp` equals `scenario_metadata.source_observed_at`. Source observed timestamps are +09:00; source collected/receipt timestamps are +00:00 UTC.
- The accepted rows' `source_raw_sha256` matches the exact original raw-file SHA-256:
  - 2026-10-12: `17940636bdf18c0b5ab8d128c524fd8c7593fb3db66dc9d5c6a696873a98145f`
  - 2026-10-13: `3432d42ad0a90ad453a703bce9b0d08421db085e36f2bdc31aaad2b9002b4b30`
- This confirms source lineage and that source event time is not the same field as transport receipt time.

## REST raw timing audit

- 2026-10-13 `rest_request_timing.jsonl`: 13,916 requests. 2026-10-12 has no corresponding timing file.
- `FHMIF10000000` price endpoint: 7,020 rows; no source timestamp field was available in the recorded responses.
- `FHMIF10010000` order-book endpoint: 6,896 rows; `aspr_acpt_hour` was a valid HHMMSS time-only value in 6,647 rows, zero sentinel `000000` in 115, and missing in 134.
- The REST source time has no date or timezone metadata in this raw timing record. A provisional same-day KST calculation (not an authoritative absolute source age) gives median 54.759s, p95 476.366s, p99 859.323s, maximum 1,205.716s; 5,887 values exceed 5s and 3,180 exceed 60s. These values must not be used as a production freshness verdict until date/timezone/session semantics are verified.
- Transport request durations are separate from source age:
  - Price endpoint: median 175.694ms, p95 2,894.953ms, max 6,735.247ms.
  - Order-book endpoint: median 150.161ms, p95 2,921.912ms, max 7,307.051ms.
- `futures_underlying_rest.jsonl`: 12 rows on 10/12 and 14 on 10/13; receipt/collection timestamp exists but no independent source event timestamp.
- Therefore REST receipt time is never substituted for source event time. REST absolute source instant remains UNKNOWN unless a verified trading date, timezone and product-session context are provided.

## Code and validation changes

- WS normalizer now records source timestamp field/raw value/format/timezone/date-resolution, observed-at semantics, receipt timezone, and explicit source-to-receipt lag. H0IOCNT0 uses verified `BSOP_HOUR` + trading date + Asia/Seoul. H0IOASP0 candidate time remains UNVERIFIED and is marked as receipt-time fallback only.
- REST normalizer requires timezone-aware `collected_at`, preserves `aspr_acpt_hour` as TIME_OF_DAY_ONLY, sets `observed_at=None`, records receipt timezone separately, and does not promote `000000` or malformed values into source timestamps.
- Existing `candidate_source_instant` requires independently verified trading date and session context; pre-open `083000`, zero sentinel and post-cutoff `154500` remain UNKNOWN. A candidate is not a freshness PASS until absolute source-time semantics are verified.
- Synthetic tests cover timezone normalization, negative/future clock skew preservation, unverified date/session, unresolved time-only REST values, zero/missing timestamps, and receipt timestamps without timezone.
- Combined T5-T13 regression suite: 204 passed, 0 failed. compileall, REST normalizer Ruff, WS/test import + critical Ruff checks, and git diff --check PASS.

## Boundaries and next step

- The 5-second threshold remains a synthetic T7 validation threshold, not a real KIS SLA.
- No Live/REAL_VTS, account/order API, new data collection, collector restart, order, cancellation or liquidation.
- Original WS/REST Raw and accepted Runtime v2 partitions remain unchanged.
- Next T14: reconcile REST time-only source values against independently verified KIS field/date/session semantics and nearest WS source observations; until then, REST source time stays unresolved and cannot independently authorize freshness.
- Existing unrelated T2 invariant-checker working diff and Graphify outputs remain uncommitted and preserved.
