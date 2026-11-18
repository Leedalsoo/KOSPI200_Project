# FRESH-57 — REST / H0IOCNT0 / H0IOASP0 three-source triangulation

- WS OrderBook snapshots: 323; report SHA-256: `70e1e7ce7fc5fe6ec13cfe94276b4fddef81282ee551307de312212fdae4a925`

## Alignment

| Metric | Count |
|---|---:|
| exact_rest_anchor | 19 |
| nearest_prior_rest_anchor | 304 |
| nearest_prior_trade_anchor | 323 |
| rest_vs_trade_ask_different | 322 |
| rest_vs_trade_ask_equal | 1 |
| rest_vs_trade_bid_different | 297 |
| rest_vs_trade_bid_equal | 26 |
| rest_vs_ws_ask_different | 258 |
| rest_vs_ws_ask_equal | 65 |
| rest_vs_ws_bid_different | 288 |
| rest_vs_ws_bid_equal | 35 |
| trade_vs_ws_ask_different | 306 |
| trade_vs_ws_ask_equal | 17 |
| trade_vs_ws_bid_different | 293 |
| trade_vs_ws_bid_equal | 30 |

## Pairwise price comparison

### rest_vs_ws

| Side | Equal | Different | Both empty | One empty | Missing | Delta median | Delta p90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bid | 35 | 288 | 0 | 0 | 0 | -0.25 | 0.05 |
| ask | 65 | 258 | 0 | 0 | 0 | -0.1 | 0.4 |
### trade_vs_ws

| Side | Equal | Different | Both empty | One empty | Missing | Delta median | Delta p90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bid | 30 | 293 | 0 | 0 | 0 | 0.15 | 0.9 |
| ask | 17 | 306 | 0 | 0 | 0 | 0.25 | 0.8 |
### rest_vs_trade

| Side | Equal | Different | Both empty | One empty | Missing | Delta median | Delta p90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bid | 26 | 297 | 0 | 0 | 0 | -0.4 | 0.15 |
| ask | 1 | 322 | 0 | 0 | 0 | -0.4 | 0.2 |

## Three-source consensus

- bid: all-three equal 7, mixed/different 316, missing/empty 0
- ask: all-three equal 1, mixed/different 322, missing/empty 0

## Time age

- REST anchor age: `{'count': 323, 'min': 0.0, 'median': 206.0, 'p90': 593.0, 'max': 908.0}`
- Trade anchor age: `{'count': 323, 'min': 185.0, 'median': 304.0, 'p90': 1834.0, 'max': 7342.0}`

## Interpretation and limits

- All sources are aligned to the same H0IOASP0 HHMMSS candidate per same-contract row; this candidate is not official event time.
- REST and H0IOCNT0 anchors use nearest-prior only; no future or cross-day anchor is accepted.
- Differences are retained with separate anchor ages; no freshness cutoff or automatic error/blocked decision.
- H0IOCNT0 is public market trade data, not account broker execution/fill. No authority promotion, gate release, mutation, or new collection.
