# Runtime Timestamp/Calendar and VTS WebSocket Evidence Reconciliation v0.2

- Date: 2026-10-15 KST
- Status: Read-only forensic reconciliation; supersedes v0.1.
- Worktree: branch `Project200`, HEAD `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`.
- Safety: only existing local records and manifests were read. No API/WS calls, subscription retries, account/order requests, source/test/Manifest edits, test execution, Git stage/commit/push, or restoration/deletion.

## 1. Scope and authoritative local artifacts

This pass expands the prior single-partition review to every date partition currently containing REST or WebSocket raw files under `data/kis_market_data_restart/`.

### REST raw partitions

12 partition dates: 2026-09-22, 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-01, 2026-10-02, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-12, 2026-10-13, 2026-10-14. Each record's `collected_at` converted to KST matches its directory date.

Aggregate REST SHA-256 hashes (calculated from actual file bytes with Get-FileHash):

| KST partition | Records | SHA-256 |
|---|---:|---|
| 2026-09-22 | 929 | `6ED8623CE7DC5B7D4164995C2956B76151017EC30AC2DDC96518BE26C6DDE323` |
| 2026-09-28 | 3,805 | `B2855F8011EF3F4194EDBF854E7CB8C501256DAC48A07224161326D6FAB03987` |
| 2026-09-29 | 3,503 | `22BD1BD42114A4F4D3DE802B8C1CF0E3FBDC3A44FB859C0B52CA4AB57EFBE5DB` |
| 2026-09-30 | 3,556 | `5ACE55AB6C9B7DCD4394AB6BB745ED4BF8E268C857857C7EE4E74A1554D047B8` |
| 2026-10-01 | 3,945 | `1C0EB48FFCA3E065D789BBEE334540E9512C1A55989185712A7BE5BD7F348C5B` |
| 2026-10-02 | 4,113 | `5685719B58D55D79A37BE808C10CAD163283DC0681F60329838A2877F159A324` |
| 2026-10-06 | 2,584 | `83B3FE0FB1254D21F3527A859E0066DA113FB20283EAA68B2E7EF79B89A7104B` |
| 2026-10-07 | 4,543 | `41D3EBD52A9842D5D0EADAE4A1D67396788F915F1087B5522AF9433B9832ACE9` |
| 2026-10-08 | 3,229 | `3DDD22E37C7B628773D234D03E32967FCB9DFDB7C7D36AB296F7CEB9C7E5D079` |
| 2026-10-12 | 4,661 | `5704E805F8B8C62771408F2B315D6EE9F324BEE515E3BE7677B33FAC9B98DA27` |
| 2026-10-13 | 5,894 | `B62611FE485DB101EA370B8585B3E44CCC3A4C1BD7EA5DA61F575925ADDC2AC9` |
| 2026-10-14 | 6,412 | `E448302D14AA1A4CC4B0BC9D013495301283E1ACC81B324DB1F7A3F6F4153D4A` |

### WebSocket raw partitions

Eight dates: 2026-10-01, 10-02, 10-06, 10-07, 10-08, 10-12, 10-13, 10-14. All file hashes were compared against actual file bytes; for 2026-10-02, the raw-file SHA-256 is `FBF4F362E24D28AE80D182C830E15CB567D7AC1F994D20E752F08E290BC1AB99`, matching that partition's `kis_vts_websocket_raw.jsonl.manifest.json`.

## 2. REST `aspr_acpt_hour`: full cross-date classification

The full 12-partition REST inventory contains 47,174 observations. Every record's inspected `payload.order_book.output2.aspr_acpt_hour` field was either a six-digit nonzero value or `000000`; no missing/empty value was found in that path.

| Result | Count |
|---|---:|
| Six-digit nonzero value | 46,971 |
| `000000` | 203 |
| Missing/empty field | 0 |
| Total | 47,174 |

The 203 `000000` observations occur only on these dates: 2026-09-29 (22), 09-30 (14), 10-01 (23), 10-02 (25), 10-07 (26), 10-08 (18), 10-12 (24), 10-13 (26), 10-14 (25). Their KST collection times span 08:29:02.491 through 08:30:15.438. All 203 have cumulative volume zero, best ask and best bid both zero, and best ask/bid quantities both zero. On days whose REST collection began later (e.g. 09-22, 09-28, 10-06), no zero timestamp appears.

For all 46,971 nonzero time strings, compared to the KST receive clock:
- 42,708 are earlier than the receive second; 4,263 match the same second; none is later.
- Difference range: 0 to 2,067 seconds earlier; median: 27 seconds earlier.
- 31,485 are within 60 seconds, 16,553 within 10 seconds, and 9,666 within 2 seconds.

### Date / holiday / session interpretation

- These records are not holiday-only observations: the 12 raw-data dates are weekdays and do not coincide with the known closure dates within this interval (including Sep 24–25, Oct 5 and Oct 9); the zero-time records are clustered at the start of collection on otherwise active dates.
- The saved KIS rolling-calendar response `HHMCM000002C0` directly identifies `today=20261014`, includes 20261014 in the rolling date set, and reports `s_time=084500` / `e_time=154500`. It is from the existing capability probe, HTTP 200, raw response SHA-256 `30cde7844830f40fbfc3b6ca8f26ae53f531eb735b6f5f9070d1d1c9579c6787`; no new API request was made. This directly confirms the date context for the Oct 14 partition only; do not pretend the one rolling response proves a full historical annual calendar.
- Across the nine dates with `000000`, the combination of start-of-collection timing and zero volume/top-of-book fields is consistent with an initial/pre-session/not-yet-populated quote context, not a holiday explanation. Exact semantics of that field remain unproven.
- The nonzero time field is often earlier than receipt, sometimes by over 30 minutes. Thus it cannot be treated as receive time. The observed association narrows the hypothesis but does not prove the absolute source date, timezone, event-vs-acceptance-time meaning, or session rollover.
- Revised REST status: **holiday explanation rejected for the 203 observed zero records; startup/pre-session context supported by the data pattern; absolute source-instant semantics still NOT PROVEN**. Never replace the source field with receive time or treat a nonzero timestamp alone as proof of executable liquidity.

## 3. WebSocket actual receipt across saved partitions

Across the eight raw files, total frames by TR are:
- `H0IOCNT0`: 239,197 frames over eight dates (Oct 1, 2, 6, 7, 8, 12, 13, 14), with 136 distinct symbols across all partitions.
- `H0IOASP0`: 178 frames, all in the 2026-10-02 partition, all for symbol `B01610A32`.
- Other totals: `H0IFCNT0` 649,301; `H0UPCNT0` 146,804.

Daily `H0IOCNT0` counts: Oct 1 2,421; Oct 2 2,935; Oct 6 7,952; Oct 7 51,517; Oct 8 171,706; Oct 12 636; Oct 13 1,234; Oct 14 796.

### H0IOCNT0 time-field relationship

Across 239,197 frames, the payload `bsop_hour` matches the KST receive clock to within one second in 239,055 records; 142 differ by more than one second. This is repeated observed behavior across multiple daily partitions, not merely a single frame. It supports a close second-level relationship in these saved runs but does not by itself define official field semantics or establish the full strategy input path.

### H0IOASP0 actual saved frames (important correction)

- The 2026-10-02 raw manifest explicitly names source `KIS_VTS_WEBSOCKET_RAW`, endpoint `ws://ops.koreainvestment.com:31000`, TR list including `H0IOASP0`, `trading_date=2026-10-02`, `record_count=87741`, and the same SHA-256 as the raw file.
- The raw file contains 178 H0IOASP0 frames for `B01610A32`, from 2026-10-02 13:53:18.272 KST through 15:45:00.465 KST. All 178 payload time strings match the KST receive clock to within one second.
- No control-event/ACK log exists in that partition, so this proves saved raw receipt in the VTS-labelled run, not the subscribe-ACK sequence.
- The same day's `daily_status.json` says `session_status=UNKNOWN`; `manifest.json` says `collectors.websocket.status=NOT_STARTED`, despite the 87,741-frame raw file and raw manifest existing. This is a **collector lifecycle/manifest consistency defect**. Do not use the daily status alone to negate the raw receipt, and do not edit the manifest as part of this read-only pass.
- Revised H0IOASP0 status: **actual saved raw receipt observed (178 frames, one symbol, timestamp-correlated); subscription acknowledgement, sustained multi-day delivery and strategy/order consumption remain NOT PROVEN**. The previous statement “no H0IOASP0 raw frame in the inventory” is superseded; it was only true for the Oct 14 partition.

### H0IOCNT0 subscription ACK correlation where control logs exist

- Oct 13: 1,234 raw frames over 53 symbols; each of the 53 raw symbols has a prior successful `OPSP0000 / SUBSCRIBE SUCCESS` control frame with the same TR/symbol.
- Oct 14: 796 raw frames over 44 symbols; each of the 44 raw symbols has a prior successful matching ACK.
- Oct 13–14 control events show session errors (15 on Oct 13, 11 on Oct 14), so ACK + receipt does not prove uninterrupted/stable delivery.
- Earlier raw partitions have no saved control logs, so their ACK chain is unknown, not failed.

## 4. Capability reconciliation: actual behavior vs official sample

The official KIS sample labels `H0IOCNT0` and `H0IOASP0` as LIVE-only / VTS unsupported. Saved VTS-labelled raw evidence contradicts that statement: H0IOCNT0 has 239,197 frames across eight dates, and H0IOASP0 has 178 frames on Oct 2. The correct response is **evidence reconciliation**, not discarding raw records solely because the sample says unsupported, and not treating the records as proof of unrestricted official support.

Evidence-level verdicts:
1. REST cross-date field/date analysis: PASS for the inspected 47,174 records.
2. REST absolute source timestamp semantics: NOT PROVEN.
3. H0IOCNT0 saved raw receipt across multiple dates: PASS for the narrow receipt claim.
4. H0IOCNT0 same-symbol prior subscribe ACK: PASS for Oct 13–14 saved control logs only.
5. H0IOASP0 saved raw receipt: PASS for the narrow receipt claim (178 frames, Oct 2); ACK evidence absent.
6. Stable/official VTS capability for option WS: **CONFLICTING EVIDENCE / NOT RESOLVED**. Do not block the observed receipt fact merely because of documentation, and do not promote the feed to a proven stable strategy source without additional lineage/capability evidence.
7. KIS raw → S1–S9 provider/input → signal → plan → single/multi-leg final admission: NOT PROVEN.
8. Collector manifest/lifecycle for Oct 2: INCONSISTENT with raw inventory; follow up separately without altering manifest in this pass.
9. FRESH-01–14: PLANNED / NOT RUN.

## 5. Current caller-chain recheck

Static source inspection confirms:
- The Virtual factory subscribes `loop.on_tick` to `bootstrap.bundle.market`; the loop constructs a `MarketState` from the Virtual market tick. This is not proof that saved KIS WS raw frames feed S1–S9 runtime ticks.
- Historical KIS observation sources may be injected into the standard provider, but the end-to-end raw collector → strategy input lineage remains NOT PROVEN.
- `KISRestMarketObservationNormalizer` retains source-time strings in provenance but returns `observed_at=None` and `raw_reference=None`.
- `route_from_runtime_authoritative_sources()` has no required source-freshness verdict parameter and calls `RiskGate.admit_order()` before routing.
- `VirtualMultiLegExecutionBridge.execute()` validates per-leg identity/quote presence and runs RiskGate preflight, but it does not receive a typed KIS source-freshness verdict. `ExecutionReport.source_freshness` is copied from an execution report after the broker boundary; it is not a pre-admission source-data gate.
- Thus single/multi-leg freshness enforcement remains NOT PROVEN. This is static inspection only; no runtime code or tests changed or ran.

## 6. Next plan gate

1. Keep these evidence-level statuses in No.1275 and summarize them in No.1274.
2. Produce an updated file-scope and FRESH-01–14 traceability plan that treats saved H0IOCNT0/H0IOASP0 receipt as real evidence while preserving the capability conflict and the manifest defect.
3. Preserve all pre-existing modified/deleted/untracked files. Do not edit runtime code, tests, Manifest, credentials, or raw evidence before separate implementation approval.
4. No KIS retries, account/order endpoints, LIVE orders, Git stage/commit/push, or deleted-test restoration.

## Payload-level integrity check (2026-10-15; read-only follow-up)
- Recomputed SHA-256 from the decoded UTF-8 payload string for every stored H0IOCNT0/H0IOASP0 frame and compared it with each frame's recorded `payload_sha256`.
- H0IOCNT0: 239,197/239,197 payload hashes matched; 0 mismatches. H0IOASP0: 178/178 payload hashes matched; 0 mismatches.
- Source-time relationship repeated: H0IOCNT0 239,055/239,197 within one second of KST receive clock; H0IOASP0 178/178 within one second.
- H0IOASP0 payload shape is consistent across all 178 frames (38 caret-separated fields in the inspected body), with changing payload hashes and source-time values from `135318` to `154500`; this is stronger evidence than a filename/count alone. It still does not provide the missing Oct 2 subscription ACK log or establish the consumer/order path.
- This follow-up validates payload integrity against the per-frame recorded hashes, not the authenticity of the original transport beyond the saved manifest/collector metadata. No API/WS call or file mutation outside this documentation appendix occurred.
## Source-field schema cross-check (2026-10-15)
- A public KIS API wrapper/schema cross-check describes `aspr_acpt_hour` as `호가 접수 시간 (HHMMSS)` (quote-acceptance time, time-only). This is corroborating schema context, not an authoritative KIS support statement and not a date/timezone definition. The official KIS GitHub sample shows `bsop_hour` among the option/futures realtime fields but does not, in the inspected sample, establish an absolute date/timezone contract for that field.
- Combined with the multi-day raw evidence, this supports treating the field as a time-of-day acceptance/observation marker rather than assuming it is a complete timestamp. Date association, timezone contract, event-versus-acceptance semantics at the exact REST TR, and session rollover still need authoritative confirmation or a separately approved empirical rule before age thresholds are activated.

## Empirical date-linking candidate — user-approved for next validation (2026-10-15 KST)

- Decision: the user approved the empirical date-linking rule as a **candidate for validation**, not as authorization to activate freshness checks or change runtime code.
- Candidate rule: when the KST trading date is independently established as a normal trading date and the source field is a valid nonzero six-digit `HHMMSS`, combine that KST trading date with the source time to form a candidate source datetime. Preserve the raw time and its evidence lineage. For `000000`, missing/malformed time, unverified/non-trading date, date conflict, or ambiguous session-boundary/rollover context, return `UNKNOWN`; do not substitute receive time.
- Date source for this dataset: `collected_at` is timezone-aware UTC and converts to KST; its KST calendar date matched the containing partition date for all 47,174 records (0 mismatches). This establishes internal date consistency for these files, not an official KIS timestamp contract or an annual exchange calendar.
- Read-only replay of the candidate over the 12 existing REST partitions: 47,174 total; 46,971 valid nonzero HHMMSS values joined to the KST date; 203 `000000` values left UNKNOWN; malformed/missing values 0 in the inspected field path; candidate source datetime later than receive time 0; lag 0.01859–2,067.470727 seconds, median 27.429956 seconds.
- Interpretation: this replay validates deterministic parsing/date association against saved receive-date context only. It does **not** prove that KIS defines `aspr_acpt_hour` as an absolute event timestamp, confirm timezone/session rollover semantics, or authorize freshness-age thresholds. The 203 zero-valued records remain UNKNOWN despite their plausible pre-session context.
- Gate: retain the candidate as an explicit, versioned empirical rule for further validation. Keep source age and final admission BLOCKED/NOT PROVEN until source semantics and exact implementation scope/test plan are separately approved. No runtime code, tests, Manifest, raw evidence, or Git index/history changed; no API calls, LIVE orders, test execution, stage/commit/push, or deleted-test restoration.

## Session-boundary and per-symbol monotonicity follow-up (2026-10-15 KST)

Read-only replay of the same 12 REST partitions, using the saved KIS rolling-calendar evidence (`s_time=084500`, `e_time=154500`; no new API request):
- 46,971 records contain a valid nonzero six-digit `aspr_acpt_hour`; 203 contain `000000` and remain UNKNOWN.
- Of the 46,971 valid values, 931 source times are earlier than 08:45 KST (all within the observed 08:30–08:44:59 pre-session interval), 43,671 fall from 08:45 through 15:20, and 2,369 fall after 15:20 through 15:45. None is later than 15:45.
- Under the current conservative candidate rule, the 931 pre-08:45 records are session-boundary ambiguous and must remain UNKNOWN unless a contract-specific authoritative source establishes that pre-session timestamp meaning. They must not be counted as freshness-eligible merely because the string is valid.
- The 2,369 records after 15:20 cannot be universally classified without the exact instrument/session cutoff; 2026-10-08 data ends at 15:20, but this alone does not prove a product-specific close. Require authoritative contract/session metadata rather than infer it.
- Source `HHMMSS` is nondecreasing within each of 312 observed (partition date, requested symbol) groups (0 regressions). Aggregating different symbols produces many apparent time decreases, so global cross-symbol monotonicity is not a valid invariant. This is internal consistency evidence only, not proof of absolute event time, timezone, or rollover semantics.
- Updated conservative candidate classification for this dataset: 46,040 values fall inside the general 08:45–15:45 KIS rolling window; 931 pre-session values + 203 zero values = 1,134 UNKNOWN pending session/source semantics. The 46,040 are still candidate joins, not verified absolute instants and not active freshness verdicts.
- Overnight/session rollover observations are absent. The empirical date-linking rule remains a validation candidate only; runtime freshness and order admission remain BLOCKED / NOT PROVEN.

## Runtime-vs-replay source-lineage clarification (2026-10-15 KST)
- `HistoricalObservationOptionSource` is instantiated by `application/run_hub/virtual_session_factory.py` only when a historical observations store is explicitly supplied. Its `observed_at or collected_at` choice is therefore a historical replay timestamp fallback in the inspected caller, not proof of live source time. It must never satisfy a runtime source-freshness verdict or be relabeled as source time.
- `KISTrack2MarketObservationSink` is attached in `automated_virtual_runtime_factory.py`, but the inspected subscription to futures/index observation streams occurs in `virtual_session_factory.py` when replay raw data is found. The replay session date is derived from the partition folder. This confirms a replay date-join edge, not a live KIS feed connection.
- `KISTrack2OptionIVObservationSink` call sites found by repository search are in `infrastructure/kis/option_historical_capture.py`; no direct runtime-factory hookup was found. The runtime factory instantiates `KISTrack2OptionIVSource`, but runtime delivery of H0IOCNT0 observations into it is NOT PROVEN. S2/S6 IV source availability and timestamp lineage must remain blocked until an actual consumer edge is demonstrated.
