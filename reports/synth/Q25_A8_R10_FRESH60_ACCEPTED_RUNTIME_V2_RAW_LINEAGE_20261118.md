# FRESH-60 — Accepted Runtime v2 ↔ original H0IOCNT0 Raw lineage

- Report SHA-256: `c91230731817572623d0625320265e0010e7ffae565611c068107ef8c6d2408c`
- Accepted Runtime v2 manifest rows: 2,072 / 1,596 timestamp groups

| Date | Raw frames | Raw records | Accepted rows | Matched | Unmatched | Remaining Raw | ID unique | Source line unique |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 20261012 | 636 | 686 | 686 | 686 | 0 | 0 | 686 | 686 |
| 20261013 | 1,234 | 1,386 | 1,386 | 1,386 | 0 | 0 | 1,386 | 1,386 |

## Underlying source by day

- 20261012: `{'KIS:H0UPCNT0': 655, 'KIS:H0UPCNT0:GROUP_MEDIAN': 31}`
- 20261013: `{'SYNTHETIC:KRX_SHOCK_V4_NEAREST_SPOT': 62, 'KIS:H0UPCNT0': 1239, 'KIS:H0UPCNT0:GROUP_MEDIAN': 85}`

## Generated-field provenance by day

- 20261012: `{'contract_multiplier': 686, 'delta': 686, 'gamma': 686, 'implied_volatility': 686, 'order_book.ask_quantity': 686, 'order_book.bid_quantity': 686, 'theta': 686, 'vega': 686, 'underlying_price_group_consensus': 31}`
- 20261013: `{'ask_price': 1, 'contract_multiplier': 1386, 'delta': 1386, 'gamma': 1386, 'implied_volatility': 1386, 'order_book.ask_quantity': 1386, 'order_book.bid_quantity': 1386, 'theta': 1386, 'underlying_price': 62, 'vega': 1386, 'underlying_price_group_consensus': 85}`

## Provenance boundary

- Decimal normalization is used for numeric field matching; generated ask is excluded from raw ask equality but requires explicit field_provenance.
- 2026-10-14 KIS Master is post-date identity corroboration only. KRX contract multiplier, KRX-derived spot, and deterministic Greeks/depth/ask remain derived validation fields.
- Decimal string-format differences (for example 33.60 vs 33.6) were normalized as Decimal, not treated as source mismatch. All 2,072 rows matched.
- underlying_price_group_consensus has its own explicit provenance object; this is not a missing-provenance condition.
- Accepted Runtime v2 source canonical hash references are verified against manifest; source canonical sidecar itself is not materialized in current worktrees. Raw field crosswalk provides the alternative lineage evidence.
- No Raw/Canonical write, new collection, account API, broker execution claim, or Live gate release.
