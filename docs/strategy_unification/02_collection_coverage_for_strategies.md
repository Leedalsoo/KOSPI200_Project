# Project200 — KIS VTS collection coverage check for strategy strike rules

Date: 2026-10-11
Scope: read-only review of collector code and existing `data/kis_market_data_restart/YYYYMMDD/` partitions. No collector, scheduler, or data file was changed. Prices below are stored observations only; there is no synthetic price series.

## 1. Code findings

- `scripts/kis_vts_websocket_collector.py:56-69`: `build_subscriptions()` calls `KISKOSPI200IndexPriceSource(KISAuthManager.from_env(is_vts=True)).refresh().price` once at line 62, passes that value to `current_monthly_option_symbols()`, then adds current standard/mini futures and the KOSPI200 index subscription. The exact `reference_price` is **not persisted** in the daily manifest; the target strike center below is inferred from the selected contracts, not a recovered reference price.
- `infrastructure/kis/kis_index_option_master_source.py:85-105`: the selected ATM is the listed monthly strike nearest the supplied reference price (line 96); each configured offset then adds PUT and CALL symbols.
- `infrastructure/kis/kis_weekday_collection_plan.py:16-33`: 13 monthly offsets from −15 to +15 in 2.5-point steps; 26 monthly option symbols.
- `scripts/kis_vts_websocket_collector.py:30` and `:67-69`: active collector limit is 41 subscriptions. The active `build_subscriptions()` path uses 26 monthly option symbols + 2 futures symbols + 1 index symbol = **29/41**, leaving 12 slots. It does not add weekly option symbols or resubscribe during the session; the subscription list is built before the single subscribe pass at `:153`.
- Separate helper `infrastructure/kis/kis_weekday_collection_plan.py:118-154` defines 4 weekly option symbols and 4 futures trade/quote streams in addition to 26 monthly symbols (34 total, before any index subscription). That helper is **not** the active `build_subscriptions()` call path above; do not assume its weekly subscriptions are being captured by this collector.
- Strategy selection evidence: S6 `application/composition/track6_option_contract_source.py:47-68` selects a listed symmetric ±12.5 pair around the closest valid center to current price. S1's `OUTER_FENCE_DISTANCE=12.5` is defined at `core/strategy/track1_tail_defense.py:47-51`, but actual fence depends on strategy state/base price, so a current-price proxy is not exact. S2 uses offsets 10/7.5/5/2.5 at `core/strategy/track2_asymmetric_trap.py:29-32, 123-169`; its runtime call supplies `tick.price` directly at `:277`, so rounding that value to a 2.5-point strike for this coverage estimate is only a proxy. S7 uses weekly expiry and ±12.5 at `application/composition/track7_option_contract_source.py:22-46`; active collector targets show no weekly options. S8 requires monthly ±15 at `application/composition/track8_option_contract_source.py:20, 49-58`. S9 enters at 15:10 at `core/strategy/track9_event_overnight_insurance.py:45-48, 160-205` and resolves its PUT/CALL selection through the shared current-price contract source.

## 2. Partition and target summary

The folder actually contains **20 date partitions** from 2026-09-22 through 2026-10-11, not 21. Nine partitions contain 26 option targets spanning strikes 1075.0–1105.0 (13 strike levels, PUT and CALL); the target center 1090.0 is inferred from that range. Eight of those target dates have a stored futures REST price series; 2026-09-22 has targets but no futures series. 2026-10-05 has 776 session-window price observations in the file but no option targets, and all stored prices are 1107.52, so it cannot establish strike coverage over price movement. Other partitions are empty/unknown or explicitly `NO_TRADING_SESSION`.

The daily manifest's exact `reference_price` field is absent. For dates with targets, `1075.0..1105.0` is the observed strike range; it is not proof that the exact initial index reference price was 1090.0.

## 3. Intraday price/coverage observations

Method: use only `futures_underlying_rest.jsonl` observations within 08:45–15:45 KST. For the *proxy* missing-coverage percentage, round each stored futures price to the nearest 2.5-point center, assume that observed price remains in effect until the next stored sample, and duration-weight the intervals. This is **not** an exact wall-clock coverage measure: futures are a proxy for the KOSPI200 index price used by the selectors, the 2.5-point center is an approximation for some strategies, and the longest sample gaps below reach 12 minutes 46 seconds. The manifest session status for 2026-09-28 through 2026-10-02 is `UNKNOWN`, so those dates are historical observations, not a confirmed clean-session set.

| Date | Manifest status | Futures samples | Observed futures min–max | S6 ±12.5 pair outside target set (weighted proxy) | S1 ±12.5 proxy | S2 all ±10/7.5/5/2.5 legs outside (proxy) | S8 ±15 pair outside (proxy) | Nearest 15:10 S9 pair proxy |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-09-28 | UNKNOWN | 145 | 1084.16–1113.72 | 30.2% | 30.2% | 18.3% | 78.9% | in range; sample 26 s away |
| 2026-09-29 | UNKNOWN | 146 | 1074.90–1093.14 | 57.2% | 57.2% | 37.5% | 79.2% | in range; sample 40 s away |
| 2026-09-30 | UNKNOWN | 145 | 1080.98–1103.86 | 68.9% | 68.9% | 36.6% | 97.4% | BLOCKED; sample 123 s away |
| 2026-10-01 | UNKNOWN | 160 | 1068.62–1103.88 | 81.0% | 81.0% | 70.1% | 92.4% | out of range; sample 9 s away |
| 2026-10-02 | UNKNOWN | 164 | 1097.56–1111.00 | 100.0% | 100.0% | 100.0% | 100.0% | BLOCKED; sample 71 s away |
| 2026-10-06 | TRADING | 320 | 1089.78–1120.00 | 92.6% | 92.6% | 58.9% | 98.3% | BLOCKED; sample 74 s away |
| 2026-10-07 | TRADING | 176 | 1073.82–1104.32 | 78.2% | 78.2% | 48.3% | 96.3% | out of range; sample 37 s away |
| 2026-10-08 | TRADING | 132 | 1049.00–1076.68 | 100.0% | 100.0% | 100.0% | 100.0% | BLOCKED; sample 340 s away |

S1 and S2 columns are explicitly proxy-only; their exact selected strike series cannot be reconstructed from the stored futures snapshots alone. S7 is **BLOCKED**, not assigned a percentage, because the active collector target manifest has no weekly option contracts. S9 is a nearest-sample proxy only; no exact 15:10 quote/price snapshot is implied. All “in range” results refer to strike membership, not a verified executable bid/ask at each timestamp.

## 4. What the observed range means for the 41-subscription cap

The current active collector's 13 strike levels (±15) produce 26 monthly option symbols. Expanding the monthly ladder to 19 strike levels (±22.5) would consume 38 option subscriptions; plus 2 futures and 1 index subscription, that reaches **41/41**. It still cannot cover the full observed daily price excursion for the selected S6 pair:

- 2026-10-06: rounded center range about 1090–1120 requires monthly strikes about 1077.5–1132.5 (23 strike levels, 46 option symbols); plus 3 current non-option subscriptions = 49.
- 2026-10-07: rounded center range about 1075–1105 requires about 1062.5–1117.5 (23 levels, 46 option symbols; 49 total).
- 2026-10-08: rounded center range about 1050–1077.5 requires about 1037.5–1090 (22 levels, 44 option symbols; 47 total).

These are observed-futures range calculations, not claims that the index selector used the exact same prices. They nevertheless show that a static widened monthly subscription bounded at 41 cannot guarantee the ±12.5 pair across these observed daily ranges. If weekly options are added to the active collector, four more option subscriptions leave room for at most 17 monthly strike levels (34 monthly option symbols) + 4 weekly + 2 futures + 1 index = 41; that is narrower still.

## 5. Conclusion and proposal (no implementation)

1. **“Collect for a few more days with the same subscription logic” is not a reliable fix.** Existing TRADING-status days show a 78.2%–100% estimated interval share outside the currently subscribed S6 pair, and the 41-subscription limit cannot hold a static strike ladder wide enough to cover the observed full-day ranges.
2. The likely solution requires a separately approved data design: intraday re-centering/rotation of subscriptions with explicit unsubscribe/resubscribe lifecycle and gap/provenance accounting, or an authorized larger/multiple subscription channel. Weekly-expiry strategies need explicit weekly contract subscriptions as well. No changes are made here.
3. Before any collector change, approve the desired coverage objective (e.g., S6 ±12.5 pair only vs S1/S2/S7/S8/S9 together), data provenance standard, and behavior during resubscription gaps. The active S6 strategy/strike rule remains unchanged.
