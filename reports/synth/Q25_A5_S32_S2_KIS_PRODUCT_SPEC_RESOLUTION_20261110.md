??: Current Baseline v2 @fb47f62636e9d343a597bec137e5862bd4da770d66f9814660fb33a0339d0e43, ??? SSOT ?? ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-08, CB2-09

# Q25 A5 S32 ? KIS official product specification?? S2 U17 expiry/multiplier ?? (2026-11-10)

## ??

**U17_PRODUCT_SPEC_RESOLVED / U20_VALIDATION_ONLY_PASS / PSB_UNVERIFIED**

KIS ?? ????? KIS MTS master? hash-bound provenance? ??? ?? ??, ?? ?? ??, ?? ???? grid ? premium tick ??? ????. ?? ?? master?? ? S2 ??? ?? ??? 2026-11-12 ??? 250,000 ??? ???? Track2 contract source ? Virtual Runtime bridge ??? ????. U17? expiry/multiplier ??? ????? ?? tradability/freshness, U16/U18/U19/U21 ?? ? natural-signal Runtime E2E/Replay? ?? ?? S2 PSB? PASS? ???.

## KIS ?? ????

Source URL:
https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp

?????? ?? ????? KOSPI200 option ??:
- Standard option transaction multiplier: 250,000 (option premium ? 250,000).
- Monthly option final trading day: settlement month second Thursday; if holiday, advance to preceding trading day.
- Recent three near-month strike interval: 2.5 index points.
- Option premium tick: below 10 points = 0.01; 10 points or more = 0.05.
- Mini KOSPI200 option multiplier: 50,000.

The implementation stores the official source URL and rule ID in the option identity. The exact expiry evidence is bound to the same KIS master SHA-256; the monthly expiry is not inferred from a YYYYMM label alone.

## Four-leg master resolution

Latest saved KIS MTS master snapshot:
- market_date_kst: 20261110
- fetched_at_utc: 2026-11-09T23:29:00.959665+00:00
- row_count: 8,419
- archive SHA-256: c9333fc2e8f043e10e6e39f9fdc96f605185824a6be1733b6ec5e6447345ce23

Resolved identities:
| Leg | Symbol | Option type | Strike | Exact expiry | Multiplier |
| --- | --- | --- | ---: | --- | ---: |
| PUT inner | C01611882 | PUT | 882.5 | 20261112 | 250000 |
| PUT outer | C01611877 | PUT | 877.5 | 20261112 | 250000 |
| CALL inner | B01611887 | CALL | 887.5 | 20261112 | 250000 |
| CALL outer | B01611892 | CALL | 892.5 | 20261112 | 250000 |

All four are STANDARD/MONTHLY and their expiry_master_sha256 equals master_sha256. The two saved KIS REST futs_last_tr_date records (B01611887 and C01611882) independently report 20261112 and match the product-spec-derived expiry. The official second-Thursday rule supplies the same exact expiry for the other two contracts.

Runtime data path verification:
- KisProductionOptionContractMaster loaded the saved snapshot offline: 14,860 legacy contract keys and 7,430 identities.
- Track2OptionContractSource.nearest_expiry(as_of=2026-11-10) returned 20261112.
- resolve_identity resolved all four symbols, option types, strikes and 250,000 multipliers.
- VirtualMultiLegExecutionBridge.identity_for_leg independently accepted all four stored identities against the same Option Master.
- load_from_raw_mst_content now computes a deterministic SHA-256 over the decoded raw KIS MST and creates a hash-bound offline identity registry. No KIS REST call is needed for monthly expiry resolution.

## Historical KIS VTS WebSocket quote evidence

Source file: data/kis_market_data_restart/20261021/kis_vts_websocket_raw.jsonl
- record_count: 137,319
- file SHA-256: 54cf62fa97f07384b55536fb433f239851acc67f372b41d062705234bbd3e252
- manifest SHA-256: 15135c3f4e0b7aa16a8114466e026a4e176f2bbae63acffdf44be135322f3db3
- observed_hour: 133813 (2026-10-21 13:38:13 KST)
- KOSPI200 index H0UPCNT0: 885.93

KIS H0IOASP0 two-sided quotes:
- PUT 877.5 C01611877: bid 35.90 / ask 39.05
- PUT 882.5 C01611882: bid 38.15 / ask 41.75
- CALL 887.5 B01611887: bid 39.20 / ask 41.25
- CALL 892.5 B01611892: bid 36.70 / ask 38.40

All four strikes are on the 2.5-point near-month grid. All observed premiums are >=10 and all recorded bid/ask prices are multiples of the KIS 0.05 premium tick. These are historical VTS quotes only; they do not prove 2026-11-10 current tradability or quote freshness. U21 maximum age/spread thresholds remain unspecified.

## Code changes

- contracts/kis_option_product_spec.py: KIS official multiplier, monthly second-Thursday expiry, near-month/premium tick facts.
- core/option/option_master.py: monthly exact expiry derivation using the injected TradingCalendar, KIS standard/mini multipliers, and raw-MST hash-bound offline identity loading.
- application/composition/track2_option_contract_source.py: accept KIS official product-spec provenance only when URL, rule ID and master hash binding match; require standard multiplier 250,000.
- application/composition/virtual_multi_leg_execution.py: recheck KIS expiry provenance and exact standard multiplier before accepting a Track2 stored identity.
- Existing S2 U20 sequential progression and entry lifecycle guards remain in place.
- Added tests for KIS expiry calculation, holiday adjustment, multiplier, price tick, offline raw-MST Option Master loading, four-leg resolution, bridge identity validation and negative mismatches.

## Validation

- S2 focused suite: **64 passed**
- Adjacent bridge/S6/S7/S8/S9 regression suite: **37 passed**
- Full pytest: **546 passed / 29 failed / 1 skipped** (10.05 seconds)
- The 29 full-suite failures are the existing S5/S7/S8 synthetic dataset/manifest family; representative failure is SYNTHETIC_REPLAY_MANIFEST_REQUIRED. No S2 focused or adjacent regression failures.
- py_compile: PASS
- git diff --check: PASS
- Graphify: 7,775 nodes / 21,772 edges / 375 communities
- Existing Graphify warning remains: application/composition/virtual_composition_root.py syntax error at line 54; not modified.

## Remaining PSB blockers

1. U16: repair/hedge, pre-retry reconciliation, retry interval/repricing, final virtual flatten and group block.
2. U17: strategy volatility boundary and current tradability/freshness evidence. Product expiry, standard multiplier, near-month strike grid and premium tick facts are resolved.
3. U18: fee/slippage-aware group PnL exit wiring and exact stop-loss/trailing ratios.
4. U19: durable restart recovery and broker-position/ledger mismatch procedure.
5. U21: maximum quote age/spread, conservative fallback formula/priority and Runtime tick-rounding integration.
6. Natural-signal four-leg validation-only Runtime E2E, U16-U21 boundary scenarios, restart/flat reconciliation and FAST/DETAILED Replay parity.

## Execution boundary

- Worktree: C:\Users\white\AppData\Local\Temp\Q25_A5_S22_S5_GROUP_CLOSE_20261109
- Branch: q25-a5-s22-s5-group-close-20261109
- HEAD unchanged: 1ea0129131370109344548827780a1e15b2ab414
- Original working-folder dirty count remains 224.
- No commit/push.
- No KIS API, REAL_VTS, Live, account, order, cancel or modify call. No real order submitted.

U17 product-spec identity resolution and U20 validation-only progression are implemented and tested. Production readiness and overall S2 PSB PASS are not claimed.
