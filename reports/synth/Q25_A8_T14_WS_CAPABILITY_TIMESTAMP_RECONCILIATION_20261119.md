# Q25 A8 T14 — WS Source Capability and Timestamp-Semantics Reconciliation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: read-only source reconciliation + metadata correction; no Raw/Canonical/accepted rewrite

## Evidence reconciliation

- Mandatory Notion No.1534 and No.1422 were reviewed with the original daily manifests, raw WS files, and the 2026-10-13 WebSocket timing sidecar.
- Daily manifest says run_id vts-rest-daily-2026-10-13 and lists kis_vts_websocket_raw.jsonl. Raw event schema contains schema, received_at, trading_date, instrument, tr_id, payload_sha256, payload and sequence, but no independent account/environment proof.
- The per-event timing sidecar marks all 1,234 H0IOCNT0 rows as source_capability_status=UNVERIFIED_FOR_VTS_OFFICIAL_SAMPLE_SAYS_LIVE_ONLY, source_clock_timezone=UNVERIFIED and source_date_semantics=UNVERIFIED.
- Official KIS sample code documents H0IOCNT0 (index option realtime conclusion) and H0IOASP0 (index option realtime quote) as real-account-only; virtual trading is unsupported. Official source file:
  https://github.com/koreainvestment/open-trading-api/blob/74b0a082fa67a0be5bf53f561719c853890ed2df/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py
- Therefore the VTS-labelled raw manifest and official TR capability conflict. Do not infer that the capture is REAL or VTS. Keep environment UNKNOWN/CONFLICT until independently verified.
- No H0IOASP0 frames appear in the six audited raw days. No unsupported VTS subscription attempt was made.

## Interpretation correction

- The T13 WS lag values (median 0.565s, p95 1.023s, max 8.439s) are only candidate lags under the KST + trading_date assumption. They are not verified absolute source ages.
- Accepted Runtime v2 source hashes match original raw files, but that establishes file lineage only; it does not establish source environment, source clock timezone, or source-date semantics.
- H0IOCNT0 BSOP_HOUR remains a time-of-day candidate. Accepted source_observed_at values are candidate interpretations until the capability/date/timezone conflict is resolved.
- H0IOASP0 is not collected in VTS. No workaround or reclassification as an order-book feed is permitted.
- REST aspr_acpt_hour remains time-only with date/timezone unresolved, as recorded in T13.

## Code correction

- WS normalizer now sets source_timestamp_timezone=UNVERIFIED, source_timestamp_date_resolution=UNVERIFIED, source_timestamp_absolute=false, and source_capability_status=UNVERIFIED_FOR_VTS_OFFICIAL_SAMPLE_SAYS_LIVE_ONLY.
- Candidate KST/trading-date interpretation is isolated into candidate_source_clock_timezone, candidate_source_date_basis and candidate_source_to_receipt_lag_ms.
- observed_at_semantics is CANDIDATE_SOURCE_EVENT_TIME_UNVERIFIED for H0IOCNT0; H0IOASP0 remains receipt-time fallback with source time unverified.
- This metadata correction does not rewrite or reclassify existing raw/accepted files. No production freshness PASS is derived from these fields.

## Validation and boundaries

- Combined T5-T14 regression suite: 204 passed, 0 failed.
- compileall, REST normalizer Ruff, WS/test import and critical Ruff, git diff --check PASS.
- No Live/REAL_VTS account connection, API call, order, cancellation, liquidation, new collection or collector restart.
- Synthetic validation remains the only approved substitute until the actual investment API is connected and exact account/feed capability, timezone, date and contract standards can be verified.
- Next T15: keep this feed UNKNOWN/CONFLICT and use only provenance-controlled synthetic evidence for validation; when the user connects the real API, verify the environment and field semantics before enabling any source-backed freshness.
