# FRESH-53 ? REST / WebSocket OrderBook time alignment (2026-10-01)

- Raw inputs are read-only. REST Raw: 3,945 rows; source time valid 3,922, missing/000000 23. WS H0IOASP0: 323 frames / 18 contracts. KRX identity crosswalk from FRESH-51: 18/18.
- Alignment uses REST `aspr_acpt_hour` and H0IOASP0 raw HHMMSS as timestamp candidates only. WS candidate is not promoted to official event time. `collected_at` and `received_at` remain separate.
- Same-symbol nearest-prior anchor: exact same time 19; prior anchor 304; future-only 0; no REST source-time anchor 0. No future anchor selected.
- REST source?collection lag seconds: `{"count": 3922, "min": 0.085427, "median": 22.0649825, "p90": 181.570809, "max": 1167.305745}`. WS candidate?received lag seconds: `{"count": 323, "min": 0.119115, "median": 0.724854, "p90": 1.166397, "max": 1.415927}`. Nearest-prior age seconds: `{"count": 323, "min": 0.0, "median": 206.0, "p90": 593.0, "max": 908.0}`. No arbitrary freshness cutoff applied.
- WS receive-order reversals: 0; duplicate sequence excess: 0; duplicate payload excess: 2.

## Per-contract matrix

| Contract | WS frames | Exact | Prior | Age median (s) | Age max (s) | REST rows |
|---|---:|---:|---:|---:|---:|---:|
| B01610A31 | 31 | 1 | 30 | 60.0 | 460.0 | 151 |
| B01610A32 | 3 | 1 | 2 | 276.0 | 276.0 | 158 |
| B01610A34 | 98 | 2 | 96 | 570.0 | 649.0 | 156 |
| B01610A39 | 1 | 1 | 0 | 0.0 | 0.0 | 148 |
| B01610A42 | 1 | 1 | 0 | 0.0 | 0.0 | 147 |
| B01610A43 | 7 | 1 | 6 | 74.0 | 76.0 | 154 |
| C01610A29 | 22 | 0 | 22 | 162.0 | 208.0 | 157 |
| C01610A30 | 33 | 1 | 32 | 120.0 | 196.0 | 160 |
| C01610A31 | 5 | 2 | 3 | 892.0 | 908.0 | 152 |
| C01610A32 | 24 | 0 | 24 | 85.0 | 156.0 | 160 |
| C01610A33 | 1 | 1 | 0 | 0.0 | 0.0 | 148 |
| C01610A34 | 5 | 1 | 4 | 186.0 | 189.0 | 154 |
| C01610A37 | 2 | 1 | 1 | 52.5 | 105.0 | 153 |
| C01610A38 | 2 | 2 | 0 | 0.0 | 0.0 | 153 |
| C01610A39 | 5 | 2 | 3 | 233.0 | 250.0 | 148 |
| C01610A40 | 66 | 1 | 65 | 207.0 | 263.0 | 151 |
| C01610A41 | 1 | 1 | 0 | 0.0 | 0.0 | 141 |
| C01610A43 | 16 | 0 | 16 | 261.5 | 318.0 | 150 |

## Judgement

- Issues: 0; future anchors: 0; `freshness_threshold_applied=false`, `official_event_time_semantics_claimed=false`, `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`.
- Source SHA-256: REST Raw `1c0eb48ffca3e065d789bbee334540e9512c1a55989185712a7be5bd7f348c5b`, H0IOASP0 Raw `efee6e6e101c6aa2fa63a2c8b4408e56bc824ba1ea7dd271d547bf3dd941ea83`, daily manifest `c378814aa4ee630d9a8e1ded0c1d593c6d2adea26c04184469c5a9c5f701232d`, KRX Raw `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`, KRX manifest `f91b69bc7aea2ecf462d738346f7c8cd513bc57983a1e822ffac6a51f815e411`.
- Report SHA-256: `4f329a4db8c04b665a23b360ddc93b38e9828095c866e150294efaeee26c733f`.
- Limits: candidate-time alignment only; no claim that REST source time and WS HHMMSS have officially certified identical semantics. Price/depth equality is not inferred from timestamps alone. This report does not prove continuous feed coverage, real executions, multiplier/tick/tradability, or Live readiness.
