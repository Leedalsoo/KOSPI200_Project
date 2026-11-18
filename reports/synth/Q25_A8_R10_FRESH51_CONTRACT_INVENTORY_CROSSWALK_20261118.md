# FRESH-51 — Contract inventory and identity crosswalk (2026-11-18)

## Source inventory

- My_Caddy_TS1 / R10 isolated worktree. No.1534, No.1538 and No.1554 applied. Raw/Canonical/Master/expiry originals were read-only; no new collection or API calls.
- KRX 2026-10-08 reference: 14,288 KOSPI200 standard+mini monthly rows / 7,144 unique KRX ISU codes / 7,144 derived KIS short codes; identity conflicts 0. Existing `derive_kis_shrn_iscd()` reused. Weekly and KOSPI150 rows excluded, matching No.1534.
- KIS Master: 33 manifest files; 32 verified archive hashes; one legacy alias manifest has no market_date_kst and points to the 2026-10-14 archive.
- Expiry cache: 42/42 exact Master code/side/strike/series-expiry matches; response/file hashes and request-before-receive all verified.

## REST Raw

- 12 dated files, 47,174 rows, 52 unique KIS option codes. This includes 2026-10-02 and 2026-10-14 files not included in the earlier No.1534 ten-day inventory. All 12 daily manifests list the raw file and match its SHA-256.
- Request symbol / OrderBook response symbol mismatches: 0. KRX identity crosswalk: 52/52. Exact-expiry cohorts: 26 codes at 2026-10-08, 26 at 2026-11-12.
- 2026-11-12 cohort matches the 2026-10-14 post-date Master 26/26. 2026-10-08 cohort is absent from the later Master as expected after expiry; KIS REST exact expiry and KRX crosswalk remain available.
- REST source time: 46,971 valid `aspr_acpt_hour` rows; 203 missing/000000; future-vs-collected 0. Lag median 27.430s, p90 197.322s, max 2,067.471s. No arbitrary freshness cutoff applied.

## WebSocket Raw

- H0IOCNT0: 235,466 frames / 352,065 parsed 58-field records / 129 unique symbols. KRX crosswalk: 129/129 unique symbols. Daily symbol counts: 26, 26, 26, 26, 30, 53.
- 2026-10-12 resolves 30/30 and 2026-10-13 resolves 53/53 to expiry 2026-11-12 through the existing `KISWebSocketOptionIdentityResolver` using the 2026-10-14 post-date Master and exact-row series expiry evidence. This is post-date corroboration, not a same-day historical Master.
- H0IOCNT0 `BSOP_HOUR` candidate event time: 352,065 records; invalid 0; future-vs-received 0. Receive lag median 582.372ms, p90 989.544ms, max 8,439.153ms. Official field semantics remain unverified.
- H0IOASP0: 323 frames / 18 symbols; KRX crosswalk 18/18. HHMMSS remains a raw candidate, not promoted to event time.

## Synthetic validation-only expiry supplement

- 26 unique WS-only contracts, absent from the 26 KIS REST anchor symbols and the later Master, share the KRX-verified KOSPI200 standard monthly 202610 series.
- A deterministic scenario assigns expiry 2026-10-08 using the 26 exact KIS REST `futs_last_tr_date` anchor contracts plus KRX identity crosswalk. Namespace: `SYNTHETIC:DERIVED_SCENARIO`.
- Every synthetic record retains the 10-01 REST Raw SHA-256, daily manifest SHA-256, KRX Raw SHA-256, 26 anchor symbols, anchor receive timestamp, generated timestamp, rule and record SHA-256. Source event time and quote timestamp are not generated.
- Per-day synthetic assignments: 10-06 12, 10-07 4, 10-08 14; the unique synthetic symbol count is 26. Source-backed exact-expiry coverage is 103 unique WS symbols; synthetic validation adds 26, yielding 129/129 validation coverage.
- The 26 synthetic expiry assignments are not authoritative KIS facts and must be replaced by exact official expiry fields after account API connection.

## Expiry cache vs REST and limits

- The 42 expiry-cache symbols and 52 REST symbols have zero direct-code and zero side+exact-expiry+strike overlap. They are separate evidence subsets, not an identity conflict. KRX monthly crosswalk covers 29/42 expiry-cache symbols; 12 weekly series and 1 later monthly series are outside the 2026-10-08 monthly KRX reference scope, but their bound Master+expiry evidence matches.
- Auditor issues: 0. `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`, `synthetic_data_used=true`.
- Contract multiplier, official tick/tradability, account/order/fill/fee/tax/margin and Live semantics remain unverified. S2 remains `PSB_UNVERIFIED`; Live/REAL_VTS/real-account orders remain disabled.
- Source hashes and detailed per-contract crosswalks are embedded in the JSON report.
- Report SHA-256: `894e0e923b40b0d112aed5b2a30e734eccce8aed33233b64ffd3757bcd69af08`.
