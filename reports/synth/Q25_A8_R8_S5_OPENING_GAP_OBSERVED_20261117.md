# Q25 A8 R8 — S5 opening-gap observed-data coverage and threshold sensitivity

- Date: 2026-11-17
- Status: READ-ONLY OBSERVED-DATA ANALYSIS / VALIDATION ONLY
- Worktree: `C:\Users\white\Desktop\MovingProject\Q25_A8_R8`
- Branch: `work/q25-a8-r8-s5-gap-observed-20261117`
- Base: `9f17b828884494cb31988ff5d0a9d92d9d55ff19` (`Project200` remote HEAD at analysis time)
- Source root: `C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart`

## 1. Scope and method

- Read-only scan of 27 existing `kis_vts_websocket_raw.jsonl` files; no collector/API calls and no new collection.
- Filter: `tr_id=H0UPCNT0`, index instrument `2001`, payload time 09:00:00–09:30:00 KST.
- Gap direction and size use the first available index event's KIS payload day-change field. This is a first-observation proxy, not independently certified official opening-auction price or prior-close reference.
- Favorable/adverse excursion is measured from the first available index price in the gap direction / opposite direction, respectively, through 09:30:00 KST.
- `advance 1.0` is the first observed time favorable excursion reaches 1.0 index point.
- `adverse 0.1/0.2` are sensitivity markers only; no persistence, confirmation, option premium, execution, or cost filter is applied.
- These are retrospective underlying-index path statistics. They do not establish option P&L, trade profitability, or approved operating thresholds.

## 2. Aggregate findings

| Metric | Result |
|---|---:|
| Opening-window dates | 27 |
| Gap-up / gap-down | 11 / 16 |
| Absolute gap range / median | 1.35–56.71pt / 15.96pt |
| Absolute gap >= 1.0 / 1.5 / 2.0 / 3.0 / 5.0pt | 27 / 26 / 26 / 24 / 21 days |
| Favorable excursion >= 0.5 / 1.0 / 2.0 / 5.0 / 10.0 / 15.0pt | 27 / 24 / 21 / 19 / 10 / 7 days |
| Advance 1.0pt reached | 24 / 27 days |
| No 1.0pt advance | 2026-10-07 (0.97pt), 2026-10-16 (0.78pt), 2026-11-11 (0.74pt) |
| Adverse 0.1pt observed | 26 / 27 days |
| Adverse 0.2pt observed | 25 / 27 days |
| Adverse 0.1pt before 1.0pt advance | 20 / 27 days |
| Adverse 0.2pt before 1.0pt advance | 20 / 27 days |
| Median time from first observation to adverse 0.1 / 0.2pt | 2s / 2s |
| Favorable excursion median / range | 8.43pt / 0.74–63.19pt |
| Adverse excursion median / range | 5.75pt / 0–18.45pt |

Interpretation:
- The current draft `min_gap_pt=1.0` would admit all 27 observed dates; the sample contains no small-gap observations below 1.35pt, so it cannot validate the low-gap no-trade boundary.
- A simple 0.1–0.2pt adverse-move hedge trigger would be highly sensitive: in 20 of 27 sessions it appeared before a 1.0pt favorable advance. Median first occurrence was only 2 seconds after the first observation.
- This supports testing a reversal magnitude together with persistence/confirmation, rather than adopting a 0.1–0.2pt point-only trigger. No persistence duration or confirmation count is approved by this report.
- The 1.0pt advance draft is reached in 24/27 sessions, but this is only underlying-index excursion frequency; it does not prove option profitability or justify the threshold.

## 3. Per-date opening-window observations

| Date | First tick KST | Frames | Gap pt | Dir. | Max fav. pt | Max adv. pt | Advance 1.0 first | Adv. 0.1 first | Adv. 0.2 first |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 2026-10-02 | 09:00:30 | 1771 | -6.15 | DOWN | 2.34 | 10.27 | 09:00:39 | 09:00:32 | 09:00:32 |
| 2026-10-07 | 09:00:30 | 1769 | -13.63 | DOWN | 0.97 | 18.45 | — | 09:00:37 | 09:00:40 |
| 2026-10-08 | 09:00:30 | 1771 | +1.35 | UP | 1.72 | 9.33 | 09:00:46 | 09:00:32 | 09:00:32 |
| 2026-10-12 | 09:00:30 | 1771 | -8.36 | DOWN | 8.07 | 3.17 | 09:00:35 | 09:00:31 | 09:00:31 |
| 2026-10-13 | 09:00:30 | 1771 | -32.41 | DOWN | 18.89 | 3.18 | 09:00:44 | 09:00:32 | 09:00:32 |
| 2026-10-14 | 09:00:49 | 1752 | +6.43 | UP | 17.63 | 1.23 | 09:01:11 | 09:00:53 | 09:00:53 |
| 2026-10-15 | 09:00:31 | 1743 | -56.71 | DOWN | 8.19 | 14.63 | 09:15:15 | 09:00:34 | 09:00:34 |
| 2026-10-16 | 09:00:30 | 1756 | +16.99 | UP | 0.78 | 12.64 | — | 09:00:31 | 09:00:31 |
| 2026-10-20 | 09:00:30 | 1771 | -4.67 | DOWN | 19.54 | 0.00 | 09:00:32 | — | — |
| 2026-10-21 | 09:00:30 | 1771 | +20.05 | UP | 15.83 | 6.00 | 09:00:45 | 09:00:43 | 09:00:43 |
| 2026-10-22 | 09:00:30 | 1771 | -10.49 | DOWN | 1.75 | 12.17 | 09:00:31 | 09:00:45 | 09:00:45 |
| 2026-10-23 | 09:00:30 | 1771 | -21.29 | DOWN | 15.89 | 5.75 | 09:01:42 | 09:00:31 | 09:00:31 |
| 2026-10-26 | 09:00:30 | 1771 | -7.48 | DOWN | 1.47 | 11.95 | 09:05:00 | 09:00:32 | 09:00:32 |
| 2026-10-27 | 09:00:30 | 1770 | +32.76 | UP | 8.47 | 0.64 | 09:00:31 | 09:00:41 | 09:01:20 |
| 2026-10-28 | 09:00:30 | 1771 | +21.87 | UP | 14.18 | 4.32 | 09:04:05 | 09:00:33 | 09:00:33 |
| 2026-10-29 | 09:00:30 | 1771 | +2.01 | UP | 17.24 | 4.71 | 09:00:40 | 09:00:32 | 09:00:33 |
| 2026-10-30 | 09:00:31 | 1770 | -30.12 | DOWN | 13.64 | 4.67 | 09:02:14 | 09:00:33 | 09:00:33 |
| 2026-11-02 | 09:00:30 | 1771 | -14.72 | DOWN | 4.94 | 12.51 | 09:01:19 | 09:00:31 | 09:00:31 |
| 2026-11-03 | 09:00:30 | 1770 | -25.76 | DOWN | 10.78 | 0.14 | 09:00:32 | 09:00:37 | — |
| 2026-11-04 | 09:00:30 | 1771 | +24.37 | UP | 6.63 | 9.57 | 09:00:34 | 09:01:02 | 09:01:04 |
| 2026-11-05 | 09:00:30 | 1770 | -19.87 | DOWN | 9.98 | 1.53 | 09:01:25 | 09:00:31 | 09:00:31 |
| 2026-11-06 | 09:00:30 | 1769 | -15.96 | DOWN | 63.19 | 1.21 | 09:02:14 | 09:00:36 | 09:00:37 |
| 2026-11-09 | 09:00:30 | 1771 | -3.22 | DOWN | 8.05 | 6.27 | 09:00:31 | 09:01:12 | 09:01:12 |
| 2026-11-10 | 09:00:30 | 1771 | +38.02 | UP | 9.10 | 0.76 | 09:00:44 | 09:00:31 | 09:00:31 |
| 2026-11-11 | 09:00:30 | 1770 | -4.92 | DOWN | 0.74 | 6.58 | — | 09:00:31 | 09:00:31 |
| 2026-11-12 | 09:00:30 | 1770 | +2.58 | UP | 5.97 | 9.56 | 09:01:15 | 09:00:31 | 09:00:31 |
| 2026-11-13 | 09:00:31 | 1770 | +19.17 | UP | 8.43 | 1.04 | 09:00:33 | 09:25:55 | 09:25:55 |

## 4. Raw-window quality

- Expected one-second slots from 09:00:30 through 09:30:00: 47,817.
- Observed unique second slots: 47,744; missing slots: 73 (including initial offsets: 2026-10-14 19s, 2026-10-15 1s, 2026-10-30 1s, 2026-11-13 1s).
- Internal missing-second counts: 2026-10-07 2s, 2026-10-15 27s, 2026-10-16 15s, 2026-10-27 1s, 2026-11-03 1s, 2026-11-05 1s, 2026-11-06 2s, 2026-11-11 1s, 2026-11-12 1s; other dates 0.
- All 27 streams reached payload time 09:30:00; payload-time reversals: 0.
- 2026-10-01 first index event was 14:55 and 2026-10-06 first index event was 10:38; excluded from opening-window sample.
- Source files total 2,900,705,624 bytes (~2.90 GB). Original files were read only and not modified.

## 5. Source raw-file SHA-256

All paths are relative to `data/kis_market_data_restart/<date>/kis_vts_websocket_raw.jsonl`.

| Date directory | SHA-256 |
|---|---|
| 2026-10-02 | FBF4F362E24D28AE80D182C830E15CB567D7AC1F994D20E752F08E290BC1AB99 |
| 2026-10-14 | C8F0DB829DBB5E7D9882B81BB80DD74454D5AEDC987082221F16AC7179EDC812 |
| 20261015 | 40D1EEE8863407C8CE2E68CC85B5A4FD8F410F31DB217853958DA6A2DFC207ED |
| 20261016 | 13CAE135D01FEAD9A73A1132A8BC42F83463C1815846ACC5A462B12EFA548BC2 |
| 20261020 | 9D63EF6512468249833E0571F99D0303CD6057C7906DA18EBE55CF4FBB80CFF2 |
| 20261021 | 54CF62FA97F07384B55536FB433F239851ACC67F372B41D062705234BBD3E252 |
| 20261022 | 227C915E7324B9FA7D45439D26A9236C0962DD1349706C0D9EC83C0E269741CA |
| 20261023 | ACAD73CBB815F00E020205627E3A474EDFF873C65A483E3FB70EE31B1F6EAFB5 |
| 20261026 | B69202432723A11A97315094BF2BC52584ACB9BB67F3C3C1459309DB9FA030C4 |
| 20261027 | D7AC75D654D3ADD3625726C6A4779759E872B4E005FD1FB6115EC0E44915C2B6 |
| 20261028 | 396584258956E87154F4BB5FE8650B77AB3AE235DDACD637F5E1ADB2C258C30C |
| 20261029 | 40E00263BCC33CE90E23581341764F42887A4F5D5FA622F2148EE5EB94C5C80F |
| 20261030 | D0645C3F4FAAD783469AC3E4DDC335286A19343263F5309740086A2D122DFC49 |
| 20261102 | 4C9447A8E524E9212E4E6084CCAECDF59E0A01C3558D852C72048BB6FD255A79 |
| 20261103 | 7D39974901039724B39DFC0A6CAD7780CC927C2F4B7CD0DACF00AA9CC1ACA826 |
| 20261104 | 367377AC04D9A9FCC893E34AEBF5E25FB5A2863256CBF31058811B0D52D7E78E |
| 20261105 | 97D1D982702F922366606764870C06BCF513E4B70F6D791C043FF238C40417AD |
| 20261106 | 225AE936762EF1623C2E4FBAA43302192FE36CE29F74FB02C764F362177BC283 |
| 20261109 | 005AE7DC17B20AA2DAAF8AF62D4419D7160A5E019219CC425EC18CE8917D45DF |
| 20261110 | 46C66395F6350828FC3F492C82EE0A4AE36DA6E8EBDA47CD716EC56E1A119EB9 |
| 20261111 | 4BE8D46295CBC460406FB72BFA6EE3AE7DDADD8C00F610D8352FEC696243E37C |
| 20261112 | 267332228B2B37DC784FF0E51569E2F69D7C55FFF834879BAC0E61EA88BAEE6A |
| 20261113 | E1267BFE1E6D0638044F395F43A6ADA525423C1C18920369F3EE0707BA2D8A40 |
| 20261007 | 1D908AB4B576E42C9201071FEF6C640AF57FB4218476ED32A65B0272C110E2E1 |
| 20261008 | 794F17CB445878B6688FEA79E04D5473A33B5E5E1856EB166AB0232EAF429C2F |
| 20261012 | 17940636BDF18C0B5AB8D128C524FD8C7593FB3DB66DC9D5C6A696873A98145F |
| 20261013 | 3432D42AD0A90AD453A703BCE9B0D08421DB085E36F2BDC31AAAD2B9002B4B30 |

## 6. Decision and limitations

- D2 remains unapproved. Existing v0.3 values `min_gap_pt=1.0`, `advance_pt=1.0`, `reversal_ratio=0.10`, `hedge_reversal_pt=null` remain draft/provisional; no value is promoted by this analysis.
- Do not use the 0.1/0.2pt adverse markers as a live hedge trigger. Compare magnitude plus persistence/confirmation candidates on a chronological split, and include gap-size regimes and incomplete-window flags.
- Option strike/expiry/identity, actual option bid/ask/depth, multiplier, premium/fill, fees, slippage, account risk and strategy-level P&L were not established by this underlying-index scan.
- No strategy code, adapter, manifest, Risk/OMS, Runtime or production configuration was modified. No pytest/Runtime replay was run in this R8 analysis worktree. No Live/REAL_VTS/account/order API calls, new collection, commit or push.
- This report is validation evidence only; it does not approve entry, hedge, exit, or production behavior.

## 7. Exploratory chronological split (not a model acceptance test)

Split by date order: first 18 sessions (2026-10-02 through 2026-11-02) as exploratory calibration sample; last 9 sessions (2026-11-03 through 2026-11-13) as small holdout.

| Candidate | First 18 | Last 9 |
|---|---:|---:|
| abs gap >= 1.0pt | 18/18 | 9/9 |
| abs gap >= 1.5pt | 17/18 | 9/9 |
| abs gap >= 2.0pt | 17/18 | 9/9 |
| abs gap >= 3.0pt | 16/18 | 8/9 |
| abs gap >= 5.0pt | 15/18 | 6/9 |
| favorable advance >= 1.0pt | 16/18 | 8/9 |
| favorable advance >= 2.0pt | 13/18 | 8/9 |
| favorable advance >= 5.0pt | 11/18 | 8/9 |
| adverse 0.1pt before 1.0pt advance | 15/18 | 5/9 |
| adverse 0.2pt before 1.0pt advance | 15/18 | 5/9 |

The 9-session holdout is too small for statistical acceptance, and the split measures only underlying-index path frequencies, not option returns. The different rates across periods also argue against choosing thresholds from the aggregate count alone. All D2/D3 thresholds remain UNSET/PROVISIONAL.
