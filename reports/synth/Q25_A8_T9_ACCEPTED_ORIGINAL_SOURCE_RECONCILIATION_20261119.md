# Q25 A8 T9 — Accepted/Original and Notion Source-Lineage Providers

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only S2-CANDIDATE-001 evidence chain

## Mandatory decisions

- No.1534 was treated as mandatory. No.1535/1538/1554/1555 decision references are required by the reconciliation provider.
- Data shortage is not treated as an immediate stop. Provider order is accepted/original primary -> Notion/source-lineage reconciliation -> T7 provenance-preserving synthetic alternative.
- Original Raw/Canonical and accepted files remain read-only. Synthetic evidence is never promoted to observed KIS, account, broker, Production or Live facts.
- Runtime code requires explicit Notion decision references as configuration; it does not call the Notion API itself. The decision pages were reviewed through Notion before this implementation.

## Original-source reconciliation performed

- Original day: 2026-10-12.
- Original KIS WebSocket raw file: data/kis_market_data_restart/20261012/kis_vts_websocket_raw.jsonl.
- Original raw manifest: KIS_VTS_WEBSOCKET_RAW, 77,310 records.
- Verified original raw file SHA-256: 17940636bdf18c0b5ab8d128c524fd8c7593fb3db66dc9d5c6a696873a98145f.
- Accepted Runtime v2 20261012 partition: 686 rows; all source_raw_sha256 references match the original raw file hash.
- Candidate timestamp: 2026-10-12 09:26:00 KST; underlying anchor 1034.62.
- Accepted partition has 2 option rows at that exact timestamp. Exact original quote coverage for the candidate's four target expiry/type/strike legs is 0/4. No nearest-strike or future-master substitution is used.
- All 12 distinct S2 source anchor observation IDs were found in accepted Runtime v2 source observation lineage (12/12). This confirms the sidecar's source anchors, but does not turn the four generated synchronized quotes into simultaneous observed quotes.

## Implementation

- Added ValidationOnlyS2AcceptedOriginalPrimaryProvider. It checks exact accepted source observations for all four legs; it never synthesizes missing quotes.
- Added ValidationOnlyS2NotionSourceReconciliationProvider. It requires No.1534/1535/1538/1554/1555 references, verifies original day manifest and raw WebSocket manifest, hashes the original raw file, reconciles accepted partition source_raw_sha256 values, verifies scenario registry crosswalk, and confirms source-anchor observation IDs.
- The providers are tick-scoped through the T7 S2 candidate matcher. Unrelated ticks are not reported as missing evidence.
- T5 supervisor now preserves provider-specific diagnostic reasons instead of replacing every unavailable result with a generic message.
- When original evidence is incomplete, the supervisor proceeds to T7 S2 synthetic alternative. The integration test uses a pre-entry flat VSSF runtime, independent synthetic broker flat snapshot, U19 FLAT_CONFIRMED, X1 PASS and X2 ARMED.

## Validation

- Combined T5/T6/T7/T8/T9, X1/X2/U19/FRESH31/freshness regression suite: 161 passed, 0 failed.
- Actual local original-source read-only verification: primary reports 0/4 exact original legs; reconciliation verifies raw SHA and 12/12 anchors, then reports 0/4 original leg coverage.
- compileall: PASS.
- Ruff on changed source/test files: PASS.
- git diff --check: PASS.

## Boundaries and next step

- The provider chain is implemented and tested with the T7 fallback, but it is not yet injected into the default Virtual session or a dedicated replay factory.
- Notion references are explicit runtime configuration; the provider validates local source lineage and records those references, while live Notion fetching remains an external orchestration responsibility.
- Next T10: inject the complete primary/reconciliation/T7 alternative chain into an isolated validation-only replay session using the per-run VSSF bridge, X2 switch and risk sources. Do not enable it in Live/REAL_VTS or the default strategy runtime until the isolated replay passes.
- No KIS Live/REAL_VTS/real account/order/cancel/liquidation API, new REST/WS collection, collector restart, or actual order action was performed.
- Existing T2 invariant-checker working diff and Graphify output changes were preserved and excluded from this commit.
