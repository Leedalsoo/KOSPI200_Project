# FRESH-59 — H0IOCNT0 raw 58-field ↔ existing KIS adapter equivalence

- Report SHA-256: `c7448677d2f7beaec1b65d77acf21843a3dc693b11648747d2ffb75e28b2c7e2`

## Aggregate

| Metric | Count |
|---|---:|
| frames | 235,466 |
| raw_records | 352,065 |
| adapter_records | 352,065 |
| adapter_errors | 0 |
| payload_hash_mismatches | 0 |
| source_mismatches | 0 |

## Field-by-field

| Field | Comparisons | Mismatches |
|---|---:|---:|
| shrn_iscd | 352,065 | 0 |
| observed_hour | 352,065 | 0 |
| last_price | 352,065 | 0 |
| volume | 352,065 | 0 |
| ask_price | 352,065 | 0 |
| bid_price | 352,065 | 0 |
| implied_volatility | 352,065 | 0 |

## Per-day

| Date | Frames | Raw records | Adapter records | Errors | Symbols |
|---|---:|---:|---:|---:|---:|
| 20261001 | 2,421 | 2,710 | 2,710 | 0 | 26 |
| 20261006 | 7,952 | 10,359 | 10,359 | 0 | 26 |
| 20261007 | 51,517 | 69,055 | 69,055 | 0 | 26 |
| 20261008 | 171,706 | 267,869 | 267,869 | 0 | 26 |
| 20261012 | 636 | 686 | 686 | 0 | 30 |
| 20261013 | 1,234 | 1,386 | 1,386 | 0 | 53 |

## Limits

- Adapter field mappings were checked against exact raw 58-field positions; no Raw/Canonical mutation or new collection.
- H0IOCNT0 is public market trade data, not user-account broker Execution/fill. Official event-time, KIS contract/account terms, and Live readiness remain unverified.
