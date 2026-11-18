# FRESH-55 ??REST price / H0IOCNT0 trade cross-check

- Dates: 20261001, 20261006, 20261007, 20261008, 20261012, 20261013
- REST rows: 24,856; parsed H0IOCNT0 trade records: 352,065
- Report SHA-256: `b3c4bcba088b3561c73dde1f5f62206b3320084415e1729d1082178e0596fc74`

## Counts

| Metric | Count |
|---|---:|
| exact_source_time | 714 |
| nearest_prior_source_time | 11,019 |
| nearest_prior_receive_time_proxy | 0 |
| future_trade_only | 1,159 |
| no_trade_source | 11,964 |
| missing_rest_price | 0 |
| last_equal | 8,683 |
| bid_equal | 1,317 |
| ask_equal | 1,251 |
| all_three_equal | 412 |
| any_price_different | 11,321 |

## Identity crosswalk

- KIS Master 2026-10-14 is used only as post-date identity corroboration, not as a historical market-date snapshot.
- 2026-10-12: REST 26 / WS 30 symbols; exact product-series + family + month + option-side + strike tuple overlap 12 (REST-only 14, WS-only 18).
- 2026-10-13: REST 26 / WS 53 symbols; exact identity tuple overlap 0 (REST-only 26, WS-only 53). This is a distinct contract subset, not a price discrepancy.
- 2026-10-01/06/07/08 expired series: reuse FRESH51 KRX crosswalk evidence (26/26 each); post-expiry KIS Master absence is expected.

## Interpretation and limits

- REST time candidate comes from order_book.output2.aspr_acpt_hour; REST last price is price.output1.futs_prpr and has no independent source timestamp in this raw shape.
- When that paired-response time is missing/000000, collected_at is used only as a receive-time proxy, not source event time.
- H0IOCNT0 BSOP_HOUR remains an event-time candidate, not independently certified official event time.
- Price differences are not automatically data errors: snapshot timing and field semantics differ.
- H0IOCNT0 is public market trade data, not account broker execution/fill.
- No freshness cutoff, authority promotion, gate release, or mutation was applied.
- Original Raw/Canonical/Manifest files were read-only; no collection or API call.
