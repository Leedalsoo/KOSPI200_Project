# Runtime Timestamp/Calendar and VTS WebSocket Evidence Reconciliation v0.1

- Date: 2026-10-15 KST
- Status: Read-only evidence reconciliation; no runtime implementation authorization.
- Worktree: `Project200`, HEAD `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`.
- Safety: used only existing files. No KIS API/WS calls, subscription retries, account calls, order calls, code/test/Manifest edits, test execution, Git stage/commit/push, or deleted-file restoration.

## 1. Input artifacts and integrity

| Artifact | Existing evidence |
|---|---|
| REST raw | `data/kis_market_data_restart/20261014/historical_market_observations.jsonl.raw.jsonl`, 6,412 records, SHA-256 `E448302D14AA1A4CC4B0BC9D013495301283E1ACC81B324DB1F7A3F6F4153D4A` |
| WebSocket raw | `data/kis_market_data_restart/20261014/kis_vts_websocket_raw.jsonl`, 150,023 records, SHA-256 `C8F0DB829DBB5E7D9882B81BB80DD74454D5AEDC987082221F16AC7179EDC812` |
| WebSocket control events | `data/kis_market_data_restart/20261014/kis_vts_websocket_control_events.jsonl` |
| Subscription rotation events | `data/kis_market_data_restart/20261014/kis_vts_subscription_events.jsonl` |
| Existing KIS capability/calendar probe | `verification/evidence/kis_api_capability_probe_20261014.json`, SHA-256 `6B715779876B26DB4E696BDF4E8729D930960CBD0A7620629036C094676DECEC` |
| KIS rolling calendar response inside probe | TR `HHMCM000002C0`, HTTP 200, response hash `30cde7844830f40fbfc3b6ca8f26ae53f531eb735b6f5f9070d1d1c9579c6787`; `today=20261014`, rolling dates include 20261014, `s_time=084500`, `e_time=154500`. No new API call was made. |

## 2. REST `aspr_acpt_hour` classification

The complete 6,412-record REST raw file was parsed, not sampled. All `collected_at` timestamps convert from UTC to the same KST date, 2026-10-14 (Wednesday). This date is also the `today` value in the already-saved successful KIS rolling-calendar response. It is not appropriate to classify these records as holiday observations.

| Check | Result |
|---|---:|
| Total raw REST observations | 6,412 |
| TR | `FHMIF10000000+FHMIF10010000` for all 6,412 |
| `aspr_acpt_hour` populated six-digit nonzero value | 6,387 |
| `aspr_acpt_hour=000000` | 25 |
| Field missing/empty in the inspected order-book payload path | 0 |
| `000000` record collection interval (KST) | 08:29:25.435–08:30:15.438 |
| `000000` records with cumulative volume 0 and best bid/ask both 0 | 25 / 25 |
| Populated time-of-day field compared with KST receive clock | 6,387 values were at or before the receive second; median difference -34 seconds; 4,129 within 60 seconds; 832 within 2 seconds |

### Interpretation

- The prior claim that the observed `000000` values might be explained by a holiday is **not supported for this dataset**: the records are all KST 2026-10-14, a Wednesday that the saved KIS rolling calendar identifies as `today`.
- The 25 zero-time records are tightly clustered at the beginning of collection and have no volume or best bid/ask values. This is consistent with an initial/pre-session or not-yet-populated market-data context; it is not evidence of a holiday. The saved KIS calendar reports `s_time=084500`, while collection begins around 08:29 KST. The fact that some subsequent records already contain populated time strings before 08:45 means the exact market-time field semantics/session interpretation still must not be overclaimed.
- The field is not simply identical to receive time: 6,387 populated values range from equal to the receive second to as much as 1,115 seconds earlier, with a median 34 seconds earlier. This supports an observed time-of-day association with the data/receive timeline, but does not independently prove the field's documented meaning, absolute date association, timezone, event-vs-acceptance-time semantics, or rollover behavior.
- Revised status: **holiday explanation ruled out for these 25 records; initial/pre-session context is plausible from timing and zero-book fields; absolute REST source-instant semantics remain NOT PROVEN**. Do not replace source time with `collected_at`, and do not treat populated timestamp alone as proof of an executable quote.

## 3. VTS WebSocket H0IOCNT0 reconciliation

The existing raw/control/rotation files were correlated by exact `(tr_id, symbol)`; no subscription was retried.

| Check | Result |
|---|---:|
| Total WS raw frames | 150,023 |
| `H0IOCNT0` raw frames | 796 |
| Distinct option symbols with an `H0IOCNT0` raw frame | 44 |
| Successful `OPSP0000 / SUBSCRIBE SUCCESS` control frames for H0IOCNT0 | 356 |
| Distinct H0IOCNT0 symbols with successful ACK and later raw frame | 44 / 44 |
| Symbols with raw frames but no prior matching success ACK in stored control log | 0 / 44 |
| All WS control events | 608 CONTROL_FRAME, 10 SESSION_CONNECTED, 11 SESSION_ERROR, 1 SESSION_ENDED |
| Option frame time vs KST receive time | 731 / 796 same second; remaining 65 / 796 within 1 second |

### Interpretation

- The previous blanket statement that the stored option trade frames had no correlated subscription ACK is superseded by this correlation: the saved control log contains successful subscription acknowledgements, and each of the 44 symbols with a raw frame has a prior successful ACK for the same TR and symbol.
- For these saved records, evidence supports **actual VTS-labeled H0IOCNT0 frame receipt following a successful per-symbol subscription acknowledgement**. The `bsop_hour` field in all 796 frames also matches the KST receive clock to within one second at second precision in this dataset.
- This does not establish unrestricted or contractually supported VTS capability: the official sample's LIVE-only/VTS-unsupported statement remains conflicting evidence. It also does not establish stable continuous delivery: 11 session errors occurred, and the per-symbol frame counts are sparse/uneven. Rotation-event records themselves previously mark their control-frame-to-rotation correlation as unverified; do not claim every rotation operation is fully reconciled.
- It does not establish that these frames feed the S1–S9 production provider, signal, execution plan, or final admission. That separate caller-chain remains NOT PROVEN.
- Revised status: **RECEIPT_OBSERVED_AND_PER_SYMBOL_ACK_CORRELATED in the saved VTS run; sustained capability / official support / strategy-order lineage remain PARTIAL or NOT PROVEN**. H0IOCNT0/H0IOASP0 retry prohibition remains unchanged. H0IOASP0 still has no raw orderbook frames in the saved inventory.

## 4. Updated evidence-level verdicts

1. **REST date/holiday context:** PASS for classification of the examined 6,412 records to KST 2026-10-14 and identification of the 25 early zero-time records; this is not a general annual holiday-calendar validation.
2. **REST absolute source timestamp semantics:** NOT PROVEN. The observed temporal correlation narrows the question but does not define date/timezone/event-time semantics.
3. **H0IOCNT0 actual saved receipt:** PASS for the narrow claim that 796 raw frames exist with valid raw hashes and per-symbol prior successful subscription ACKs for all 44 symbols.
4. **H0IOCNT0 stable/official VTS support:** PARTIAL / CONFLICTING EVIDENCE because the saved run shows ACK+frames, while the official KIS sample labels the feed LIVE-only/VTS unsupported and the run has 11 session errors.
5. **H0IOASP0 VTS receipt:** NOT OBSERVED in the existing raw inventory; no retry performed.
6. **S1–S9 KIS raw → input → signal → execution → single/multi-leg final admission:** NOT PROVEN; no runtime changes or tests executed.
7. **FRESH-01–14:** PLANNED / NOT RUN. Numeric freshness candidates remain proposals, not approved policy.

## 5. Next actions under the current plan

1. Keep the corrected evidence-level statuses in No.1275 and summarize them in No.1274.
2. Continue read-only caller-chain and file-boundary/test traceability work, using the existing coverage docs and preserving all current modified/deleted/untracked files.
3. Present exact implementation scope and test plan for explicit user approval. Do not implement freshness gates or create/run tests before approval.
4. Keep LIVE orders, prohibited H0IOCNT0/H0IOASP0 retries, account retries, Git stage/commit/push, and restoration of deleted tests prohibited.
