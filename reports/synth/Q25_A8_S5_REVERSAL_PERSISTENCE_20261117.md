# Q25 A8 S5 reversal-persistence sensitivity analysis

- Date: 2026-11-17
- Status: READ-ONLY OBSERVED UNDERLYING ANALYSIS / VALIDATION ONLY
- Source: existing KIS WS Raw, H0UPCNT0 / index 2001
- Dates: 27; bytes scanned: 2,900,705,624
- Unique second slots: 47,744; missing slots: 73

## 1. Baseline reconciliation

- Gap-up/down: 11/16.
- Favorable 1.0pt advance: 24/27.
- Adverse 0.1pt / 0.2pt before 1.0pt advance: 20/27 and 20/27.
- All 27 sessions reconcile to the R8 baseline: 73 missing one-second slots, no interpolated observations, all windows reach 09:30:00.

## 2. D2 gap-size and advance sensitivity

These are underlying-index frequencies only; they do not validate option returns.

### Minimum gap filter

| Minimum abs gap (pt) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- |
| 1.0 | 27 | 18 | 9 |
| 1.5 | 26 | 17 | 9 |
| 2.0 | 26 | 17 | 9 |
| 3.0 | 24 | 16 | 8 |
| 5.0 | 21 | 15 | 6 |

### Favorable advance

| Advance (pt) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- |
| 1.0 | 24 | 16 | 8 |
| 2.0 | 21 | 13 | 8 |
| 3.0 | 20 | 12 | 8 |
| 5.0 | 19 | 11 | 8 |

## 3. D3 pre-advance adverse reversal candidates

A candidate is counted only if adverse movement reaches the stated magnitude for N consecutive observed seconds and the confirmation completes strictly before the favorable advance. Missing seconds reset the confirmation streak. This is a candidate for the opposite-option hedge, not an approved trigger.

### Before advance 1.0pt

| Adverse move (pt) | Persistence (s) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- | --- |
| 0.5 | 2 | 15 | 10 | 5 |
| 0.5 | 3 | 14 | 10 | 4 |
| 0.5 | 5 | 13 | 10 | 3 |
| 0.5 | 10 | 10 | 8 | 2 |
| 1.0 | 2 | 12 | 10 | 2 |
| 1.0 | 3 | 10 | 8 | 2 |
| 1.0 | 5 | 10 | 8 | 2 |
| 1.0 | 10 | 9 | 7 | 2 |
| 1.5 | 2 | 9 | 8 | 1 |
| 1.5 | 3 | 9 | 8 | 1 |
| 1.5 | 5 | 8 | 7 | 1 |
| 1.5 | 10 | 8 | 7 | 1 |
| 2.0 | 2 | 8 | 7 | 1 |
| 2.0 | 3 | 8 | 7 | 1 |
| 2.0 | 5 | 8 | 7 | 1 |
| 2.0 | 10 | 8 | 7 | 1 |
| 3.0 | 2 | 8 | 7 | 1 |
| 3.0 | 3 | 8 | 7 | 1 |
| 3.0 | 5 | 8 | 7 | 1 |
| 3.0 | 10 | 8 | 7 | 1 |

### Before advance 2.0pt

| Adverse move (pt) | Persistence (s) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- | --- |
| 0.5 | 2 | 19 | 13 | 6 |
| 0.5 | 3 | 18 | 13 | 5 |
| 0.5 | 5 | 16 | 12 | 4 |
| 0.5 | 10 | 14 | 11 | 3 |
| 1.0 | 2 | 15 | 12 | 3 |
| 1.0 | 3 | 14 | 11 | 3 |
| 1.0 | 5 | 14 | 11 | 3 |
| 1.0 | 10 | 13 | 10 | 3 |
| 1.5 | 2 | 13 | 11 | 2 |
| 1.5 | 3 | 13 | 11 | 2 |
| 1.5 | 5 | 12 | 10 | 2 |
| 1.5 | 10 | 12 | 10 | 2 |
| 2.0 | 2 | 12 | 10 | 2 |
| 2.0 | 3 | 11 | 10 | 1 |
| 2.0 | 5 | 11 | 10 | 1 |
| 2.0 | 10 | 11 | 10 | 1 |
| 3.0 | 2 | 11 | 10 | 1 |
| 3.0 | 3 | 11 | 10 | 1 |
| 3.0 | 5 | 11 | 10 | 1 |
| 3.0 | 10 | 11 | 10 | 1 |

## 4. Post-advance peak-retracement candidates

After the favorable advance, retracement is measured from the subsequent favorable peak. These are original-option exit candidates, not opposite-option hedge entries. No option premium or profit-lock calculation is implied.

### After advance 1.0pt

| Peak retracement (pt) | Persistence (s) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- | --- |
| 0.5 | 2 | 24 | 16 | 8 |
| 0.5 | 3 | 24 | 16 | 8 |
| 0.5 | 5 | 24 | 16 | 8 |
| 0.5 | 10 | 24 | 16 | 8 |
| 1.0 | 2 | 24 | 16 | 8 |
| 1.0 | 3 | 24 | 16 | 8 |
| 1.0 | 5 | 24 | 16 | 8 |
| 1.0 | 10 | 24 | 16 | 8 |
| 1.5 | 2 | 24 | 16 | 8 |
| 1.5 | 3 | 24 | 16 | 8 |
| 1.5 | 5 | 24 | 16 | 8 |
| 1.5 | 10 | 24 | 16 | 8 |
| 2.0 | 2 | 24 | 16 | 8 |
| 2.0 | 3 | 24 | 16 | 8 |
| 2.0 | 5 | 24 | 16 | 8 |
| 2.0 | 10 | 24 | 16 | 8 |
| 3.0 | 2 | 24 | 16 | 8 |
| 3.0 | 3 | 23 | 16 | 7 |
| 3.0 | 5 | 23 | 16 | 7 |
| 3.0 | 10 | 23 | 16 | 7 |

### After advance 2.0pt

| Peak retracement (pt) | Persistence (s) | All 27 | First 18 | Last 9 |
| --- | --- | --- | --- | --- |
| 0.5 | 2 | 21 | 13 | 8 |
| 0.5 | 3 | 21 | 13 | 8 |
| 0.5 | 5 | 21 | 13 | 8 |
| 0.5 | 10 | 21 | 13 | 8 |
| 1.0 | 2 | 21 | 13 | 8 |
| 1.0 | 3 | 21 | 13 | 8 |
| 1.0 | 5 | 21 | 13 | 8 |
| 1.0 | 10 | 21 | 13 | 8 |
| 1.5 | 2 | 21 | 13 | 8 |
| 1.5 | 3 | 21 | 13 | 8 |
| 1.5 | 5 | 21 | 13 | 8 |
| 1.5 | 10 | 21 | 13 | 8 |
| 2.0 | 2 | 21 | 13 | 8 |
| 2.0 | 3 | 21 | 13 | 8 |
| 2.0 | 5 | 21 | 13 | 8 |
| 2.0 | 10 | 21 | 13 | 8 |
| 3.0 | 2 | 21 | 13 | 8 |
| 3.0 | 3 | 20 | 13 | 7 |
| 3.0 | 5 | 20 | 13 | 7 |
| 3.0 | 10 | 20 | 13 | 7 |

## 5. Exploratory gap-size regimes

| Gap regime | Sessions | Advance 1pt | Pre-advance adverse 1pt/3s | Post-advance retrace 1pt/3s |
| --- | --- | --- | --- | --- |
| SMALL_LT_5 | 6 | 5 | 1 | 5 |
| MEDIUM_5_TO_15 | 7 | 6 | 3 | 6 |
| LARGE_GE_15 | 14 | 13 | 6 | 13 |

Regime boundaries (<5pt, 5–15pt, >=15pt) are exploratory buckets only, not approved operating filters.

## 6. Decision and limitations

- Keep the No.1565 policy mapping: gap-up CALL BUY 1 / gap-down PUT BUY 1; opposite option BUY 1 is considered only for an objectively confirmed adverse reversal before the required favorable advance; after advance, manage/close the original option rather than adding the hedge.
- The tables compare candidate magnitude/persistence combinations on a chronological 18-session calibration / 9-session holdout split. The holdout is too small for statistical acceptance; do not select an operating threshold from these counts.
- The gap value is the first available H0UPCNT0 day-change payload field, not an independently certified official opening-auction/prior-close pair.
- No option premium, strike/expiry identity, option multiplier, fills, fees, slippage, account margin, or option PnL was available in this analysis. No profitability claim is made.
- All D2/D3 numeric thresholds remain UNSET/PROVISIONAL. No strategy code, manifest, Risk/OMS, Runtime, production setting, or original source data was changed.
- No new collection, collector/API calls, KIS Live/REAL_VTS/real-account/order API calls, or Project200 merge.

## 7. Source SHA-256 by date

| Date | Raw SHA-256 |
| --- | --- |
| 20261002 | fbf4f362e24d28ae80d182c830e15cb567d7ac1f994d20e752f08e290bc1ab99 |
| 20261007 | 1d908ab4b576e42c9201071fef6c640af57fb4218476ed32a65b0272c110e2e1 |
| 20261008 | 794f17cb445878b6688fea79e04d5473a33b5e5e1856eb166ab0232eaf429c2f |
| 20261012 | 17940636bdf18c0b5ab8d128c524fd8c7593fb3db66dc9d5c6a696873a98145f |
| 20261013 | 3432d42ad0a90ad453a703bce9b0d08421db085e36f2bdc31aaad2b9002b4b30 |
| 20261014 | c8f0db829dbb5e7d9882b81bb80dd74454d5aedc987082221f16ac7179edc812 |
| 20261015 | 40d1eee8863407c8ce2e68cc85b5a4fd8f410f31db217853958da6a2dfc207ed |
| 20261016 | 13cae135d01fead9a73a1132a8bc42f83463c1815846acc5a462b12efa548bc2 |
| 20261020 | 9d63ef6512468249833e0571f99d0303cd6057c7906da18ebe55cf4fbb80cff2 |
| 20261021 | 54cf62fa97f07384b55536fb433f239851acc67f372b41d062705234bbd3e252 |
| 20261022 | 227c915e7324b9fa7d45439d26a9236c0962dd1349706c0d9ec83c0e269741ca |
| 20261023 | acad73cbb815f00e020205627e3a474edff873c65a483e3fb70ee31b1f6eafb5 |
| 20261026 | b69202432723a11a97315094bf2bc52584acb9bb67f3c3c1459309db9fa030c4 |
| 20261027 | d7ac75d654d3add3625726c6a4779759e872b4e005fd1fb6115ec0e44915c2b6 |
| 20261028 | 396584258956e87154f4bb5fe8650b77ab3ae235ddacd637f5e1adb2c258c30c |
| 20261029 | 40e00263bcc33ce90e23581341764f42887a4f5d5fa622f2148ee5eb94c5c80f |
| 20261030 | d0645c3f4faad783469ac3e4ddc335286a19343263f5309740086a2d122dfc49 |
| 20261102 | 4c9447a8e524e9212e4e6084ccaecdf59e0a01c3558d852c72048bb6fd255a79 |
| 20261103 | 7d39974901039724b39dfc0a6cad7780cc927c2f4b7cd0dacf00aa9cc1aca826 |
| 20261104 | 367377ac04d9a9fcc893e34aebf5e25fb5a2863256cbf31058811b0d52d7e78e |
| 20261105 | 97d1d982702f922366606764870c06bcf513e4b70f6d791c043ff238c40417ad |
| 20261106 | 225ae936762ef1623c2e4fbaa43302192fe36ce29f74fb02c764f362177bc283 |
| 20261109 | 005ae7dc17b20aa2daaf8af62d4419d7160a5e019219cc425ec18ce8917d45df |
| 20261110 | 46c66395f6350828fc3f492c82ee0a4ae36da6e8ebda47cd716ec56e1a119eb9 |
| 20261111 | 4be8d46295cbc460406fb72bfa6ee3ae7ddadd8c00f610d8352fec696243e37c |
| 20261112 | 267332228b2b37dc784ff0e51569e2f69d7c55fff834879bac0e61ea88baee6a |
| 20261113 | e1267bfe1e6d0638044f395f43a6ada525423c1c18920369f3ee0707ba2d8a40 |
