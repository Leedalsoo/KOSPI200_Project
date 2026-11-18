# FRESH-56 — REST / H0IOASP0 OrderBook price and depth cross-check

- REST rows: 3,945; H0IOASP0 frames: 323; contracts: 18
- Report SHA-256: `b96ec5d68fd7d75eb5171e449e6db1a69342129175e669b7ac78534744a5ff4e`

## Alignment counts

| Metric | Count |
|---|---:|
| exact_source_time | 19 |
| nearest_prior | 304 |
| future_only | 0 |
| no_rest_source | 0 |
| rest_source_time_missing | 0 |
| price_equal | 671 |
| price_different | 2,535 |
| price_both_empty | 4 |
| price_one_empty | 20 |
| price_missing | 0 |
| quantity_equal | 2,085 |
| quantity_different | 1,145 |
| quantity_missing | 0 |

## Exact vs nearest-prior summary

| Alignment | Snapshots | Price equal | Different | Both empty | One empty | Missing | Qty equal | Qty different |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EXACT_SOURCE_TIME | 19 | 175 | 13 | 2 | 0 | 0 | 182 | 8 |
| NEAREST_PRIOR | 304 | 496 | 2522 | 2 | 20 | 0 | 1903 | 1137 |

## Per-level comparisons

### BID

| Level | Price equal | Different | Both empty | One empty | Missing | Qty equal | Qty different |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 35 | 288 | 0 | 0 | 0 | 216 | 107 |
| 2 | 67 | 256 | 0 | 0 | 0 | 261 | 62 |
| 3 | 46 | 277 | 0 | 0 | 0 | 109 | 214 |
| 4 | 55 | 268 | 0 | 0 | 0 | 134 | 189 |
| 5 | 75 | 248 | 0 | 0 | 0 | 193 | 130 |
### ASK

| Level | Price equal | Different | Both empty | One empty | Missing | Qty equal | Qty different |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 65 | 258 | 0 | 0 | 0 | 268 | 55 |
| 2 | 62 | 261 | 0 | 0 | 0 | 245 | 78 |
| 3 | 95 | 228 | 0 | 0 | 0 | 238 | 85 |
| 4 | 74 | 246 | 0 | 3 | 0 | 198 | 125 |
| 5 | 97 | 205 | 4 | 17 | 0 | 223 | 100 |

## Interpretation and limits

- Same-contract nearest-prior REST source-time candidate is compared to H0IOASP0 HHMMSS candidate; the latter is not promoted to official event time.
- Price and quantity differences are preserved as observed; no arbitrary freshness cutoff or error classification is applied.
- Empty/zero depth is counted separately from equal nonzero depth.
- This is market-data cross-validation, not broker execution/fill evidence or proof of authoritative KIS depth semantics.
- Original Raw/Canonical/Manifest files were read-only; no new collection/API call, authority promotion, gate release or mutation.
