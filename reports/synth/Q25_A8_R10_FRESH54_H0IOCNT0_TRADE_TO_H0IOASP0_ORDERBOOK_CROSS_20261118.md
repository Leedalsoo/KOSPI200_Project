# FRESH-54 ? H0IOCNT0 market-trade / H0IOASP0 OrderBook cross-check (2026-10-01)

- Read-only source set: H0IOCNT0 2421 Raw frames / 2710 parsed 58-field market-trade records / 26 contracts; H0IOASP0 323 Raw OrderBook frames / 18 contracts. Invalid H0IOCNT0 candidate timestamps: 0.
- Per contract, choose nearest-prior H0IOCNT0 `BSOP_HOUR` candidate at or before H0IOASP0 HHMMSS candidate. These are source-time candidates; H0IOASP0 HHMMSS is not promoted to official event time. Both received_at fields remain separate.
- Alignment: exact 0; nearest-prior trade 323; future-only 0; no trade source 0. No future anchor selected.
- Nearest-prior trade age seconds: `{"count": 323, "min": 185.0, "median": 304.0, "p90": 1834.0, "max": 7342.0}`. H0IOCNT0 source candidate?received lag: `{"count": 2710, "min": 0.048158, "median": 0.563009, "p90": 0.9564, "max": 2.698552}`. H0IOASP0 candidate?received lag: `{"count": 323, "min": 0.119115, "median": 0.724854, "p90": 1.166397, "max": 1.415927}`. No freshness threshold applied.
- Top-of-book comparison against selected prior trade record: bid equal 30/323, ask equal 17/323, both equal 7/323, both different 316/323. These are time-separated observations; differences are not automatically classified as data corruption.

## Per-contract coverage and age

| Contract | OrderBook | Exact | Prior | Age median (s) | Age max (s) | Bid equal | Ask equal |
|---|---:|---:|---:|---:|---:|---:|---:|
| B01610A31 | 31 | 0 | 31 | 1893.0 | 1922.0 | 0 | 0 |
| B01610A32 | 3 | 0 | 3 | 1706.0 | 1707.0 | 0 | 0 |
| B01610A34 | 98 | 0 | 98 | 235.5 | 318.0 | 5 | 13 |
| B01610A39 | 1 | 0 | 1 | 270.0 | 270.0 | 0 | 1 |
| B01610A42 | 1 | 0 | 1 | 1208.0 | 1208.0 | 0 | 0 |
| B01610A43 | 7 | 0 | 7 | 252.0 | 256.0 | 0 | 0 |
| C01610A29 | 22 | 0 | 22 | 486.0 | 532.0 | 0 | 0 |
| C01610A30 | 33 | 0 | 33 | 251.0 | 339.0 | 7 | 0 |
| C01610A31 | 5 | 0 | 5 | 1709.0 | 1718.0 | 0 | 0 |
| C01610A32 | 24 | 0 | 24 | 950.0 | 1021.0 | 0 | 0 |
| C01610A33 | 1 | 0 | 1 | 483.0 | 483.0 | 0 | 0 |
| C01610A34 | 5 | 0 | 5 | 318.0 | 335.0 | 0 | 0 |
| C01610A37 | 2 | 0 | 2 | 7341.5 | 7342.0 | 0 | 0 |
| C01610A38 | 2 | 0 | 2 | 487.0 | 487.0 | 0 | 0 |
| C01610A39 | 5 | 0 | 5 | 2076.0 | 2092.0 | 0 | 0 |
| C01610A40 | 66 | 0 | 66 | 303.5 | 382.0 | 18 | 3 |
| C01610A41 | 1 | 0 | 1 | 2060.0 | 2060.0 | 0 | 0 |
| C01610A43 | 16 | 0 | 16 | 1679.5 | 1736.0 | 0 | 0 |

## Judgement

- Issues: 0; `freshness_threshold_applied=false`, `official_orderbook_event_time_claimed=false`, `market_trade_is_broker_execution=false`, `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`.
- Source SHA-256: H0IOCNT0 Raw `b9b7681518b0502c5e37c13351cdb15af88c4a388e52bc42a39435ffd1adcc49`, H0IOASP0 Raw `efee6e6e101c6aa2fa63a2c8b4408e56bc824ba1ea7dd271d547bf3dd941ea83`, daily Manifest `c378814aa4ee630d9a8e1ded0c1d593c6d2adea26c04184469c5a9c5f701232d`, KRX Raw `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`, KRX Manifest `f91b69bc7aea2ecf462d738346f7c8cd513bc57983a1e822ffac6a51f815e411`.
- Report SHA-256: `d4c73d93d44a8761e749d2f45b4b29c672a11a7ab28fb5cf45acd221ef6f7949`.
- Limits: H0IOCNT0 are public market trade prints, not user/account order executions. H0IOASP0 raw HHMMSS semantics are unverified. Price differences are retained as observed and not forcibly reconciled. No claim of actual broker fill, multiplier/tick/tradability/account/fee/margin/Live readiness.
