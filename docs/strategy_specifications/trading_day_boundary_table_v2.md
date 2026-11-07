# Trading-Day Boundary Table v2 — KRX exact expiry / D-4 / DTE10

- Created: 2026-10-13
- Status: **D-4 counting convention user-approved on 2026-10-13; calendar dates remain candidates / not executable until expiry and current-session evidence are verified**.
- Prior draft preserved at `trading_day_boundary_table_draft.md`; this version supersedes its weekday-only date guesses as the current evidence summary.
- Rule: expiry is D=0. Count backward only actual KRX trading sessions; exclude weekends, official holidays, temporary closures, and any other KRX non-trading session. D-4 is the fourth preceding trading session strictly before expiry (user-approved 2026-10-13). S1/S9 11:00 KST action timing remains subject to runtime boundary validation. S8 requires DTE >= 10 based on actual sessions.

## 1. Official source links and evidence status

| Evidence | Official URL / local artifact | Retrieval evidence | Result |
|---|---|---|---|
| KRX official Market Closing (Holiday) | https://global.krx.co.kr/contents/GLB/05/0501/0501110000/GLB0501110000.jsp | Existing project fetch log No.1045; KRX OTP?JSON implementation in `infrastructure/kis/holiday_fallback_provider.py` | Official year-based source; No.1045 recorded 2026/2027/2028 as 17/16/17 holidays |
| KRX 2026 holiday snapshot | `data/calendar/krx/2026.json` | `fetched_at=2026-10-12T15:00:23.046399+00:00`; 17 dates; file modification 2026-10-13 | Local official-source cache exists and validates source URL/year |
| KRX 2027 holiday snapshot | `data/calendar/krx/2027.json` | `fetched_at=2026-10-11T08:24:18.488702+00:00`; 16 dates; file modification 2026-10-11 | Local official-source cache exists and validates source URL/year |
| KRX 2028 holiday snapshot | `data/calendar/krx/2028.json` | `fetched_at=2026-10-11T08:24:18.921445+00:00`; 17 dates; file modification 2026-10-11 | Local official-source cache exists, but dates beyond 2027-10 are outside this table |
| KRX official holiday lookup (web UI) | https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp | Searchable page; cached yearly result is the stronger evidence for actual dates | Current page UI itself does not expose a saved query in the page snapshot |
| KRX annual derivatives schedule | https://open.krx.co.kr/contents/MKD/01/0110/01100303/MKD01100303.jsp | Linked by earlier project notes | Supplemental product/session schedule; do not substitute for the year holiday data |

**Correction to prior v2 wording:** holiday evidence is not wholly UNSET. Project cache snapshots for 2026 and 2027 exist and record their source URL, fetch timestamp, year, and exact holiday dates. Date vectors below are therefore **calculated candidates** using these recorded KRX holidays plus weekends. They remain unapproved, and a new temporary closure notice or source refresh must be checked before operational use. The option master snapshot is still dated 2026-09-19 and does not contain every monthly expiry in the 12-month window.

### Official-source cache holiday list by month (2026-11 through 2027-10)

| Month | KRX cache holiday dates | Evidence |
|---|---|---|
| 2026-11 | None listed | `2026.json`, fetched 2026-10-12 |
| 2026-12 | 2026-12-25, 2026-12-31 | `2026.json`, fetched 2026-10-12 |
| 2027-01 | 2027-01-01 | `2027.json`, fetched 2026-10-11 |
| 2027-02 | 2027-02-08, 2027-02-09 | `2027.json`, fetched 2026-10-11 |
| 2027-03 | 2027-03-01 | `2027.json`, fetched 2026-10-11 |
| 2027-04 | None listed | `2027.json`, fetched 2026-10-11 |
| 2027-05 | 2027-05-03, 2027-05-05, 2027-05-13 | `2027.json`, fetched 2026-10-11 |
| 2027-06 | None listed | `2027.json`, fetched 2026-10-11 |
| 2027-07 | 2027-07-19 | `2027.json`, fetched 2026-10-11 |
| 2027-08 | 2027-08-16 | `2027.json`, fetched 2026-10-11 |
| 2027-09 | 2027-09-14, 2027-09-15, 2027-09-16 | `2027.json`, fetched 2026-10-11 |
| 2027-10 | 2027-10-04, 2027-10-11 | `2027.json`, fetched 2026-10-11 |

## 2. Exact expiry candidates from historical KRX master snapshot

Historical source snapshot: filenames dated `20260919`; Git shows the files were added 2026-09-19, moved to `tests/fixtures/krx/` 2026-10-03, and deleted 2026-10-05. Original filesystem modification times and actual download time are unavailable. Exact G-column values are source-provided but current listing/freshness has not been re-verified. Dates below are **historical master candidates only**.

| Contract month | Exact expiry from historical KRX master | D-4 candidate (S1/S9) | S9 11:00 KST boundary date | S8 DTE10 candidate | KRX holidays relevant to calculation | Status |
|---|---|---|---|---|---|---|
| 2026-11 | 2026-11-12 | 2026-11-06 | 2026-11-06 | 2026-10-29 | None listed in Nov; October holidays are in the source cache | Candidate; D-4 convention approved, source freshness/runtime unverified |
| 2026-12 | 2026-12-10 | 2026-12-04 | 2026-12-04 | 2026-11-26 | 2026-12-25 and 2026-12-31 (after expiry) | Candidate; D-4 convention approved, source freshness/runtime unverified |
| 2027-01 | 2027-01-14 | 2027-01-08 | 2027-01-08 | 2026-12-29 | 2027-01-01 (before expiry) | Candidate; D-4 convention approved, source freshness/runtime unverified |
| 2027-02 | 2027-02-11 | 2027-02-03 | 2027-02-03 | 2027-01-26 | 2027-02-08 and 2027-02-09; affects D-4 week | Candidate; holiday-week cross-check |
| 2027-03 | 2027-03-11 | 2027-03-05 | 2027-03-05 | 2027-02-24 | 2027-03-01; excluded from session count | Candidate; holiday-aware count |
| 2027-04 | UNSET | UNSET | UNSET | UNSET | None listed in cache | BLOCKED: no exact contract expiry in snapshot |
| 2027-05 | UNSET | UNSET | UNSET | UNSET | 2027-05-03, 2027-05-05, 2027-05-13 | BLOCKED: no exact contract expiry in snapshot |
| 2027-06 | 2027-06-10 | 2027-06-04 | 2027-06-04 | 2027-05-27 | 2027-06 has none listed; 2027-05 holidays affect DTE10 count | Candidate; D-4 convention approved, source freshness/runtime unverified |
| 2027-07 | UNSET | UNSET | UNSET | UNSET | 2027-07-19 | BLOCKED: no exact contract expiry in snapshot |
| 2027-08 | UNSET | UNSET | UNSET | UNSET | 2027-08-16 | BLOCKED: no exact contract expiry in snapshot |
| 2027-09 | 2027-09-09 | 2027-09-03 | 2027-09-03 | 2027-08-26 | 2027-09-14, 2027-09-15, 2027-09-16 (after expiry) | Candidate; D-4 convention approved, source freshness/runtime unverified |
| 2027-10 | UNSET | UNSET | UNSET | UNSET | 2027-10-04 and 2027-10-11 | BLOCKED: no exact contract expiry in snapshot |

These are calculated candidates, not approved execution dates. The table remains incomplete because exact monthly expiry records are missing for 2027-04, 2027-05, 2027-07, 2027-08, and 2027-10. S9 11:00 KST is a time boundary on the candidate D-4 date, not a separately derived date.

## 3. Source field sample (10+ contracts)

`G` means the actual `최종거래일` cell, not a rule-derived date.

| File | Row | KRX standard code | Name (abbreviated) | G: final trading day |
|---|---:|---|---|---|
| `data_2801_20260919.xlsx` | 2 | `KR4B016A7454` | KOSPI200 C 202610 745.0 | 2026/10/08 |
| `data_2801_20260919.xlsx` | 3 | `KR4B016A7470` | KOSPI200 C 202610 747.5 | 2026/10/08 |
| `data_2801_20260919.xlsx` | 4 | `KR4B016A7504` | KOSPI200 C 202610 750.0 | 2026/10/08 |
| `data_2801_20260919.xlsx` | 343 | `KR4B016B7503` | KOSPI200 C 202611 750.0 | 2026/11/12 |
| `data_2801_20260919.xlsx` | 682 | `KR4B016C1802` | KOSPI200 C 202612 180.0 | 2026/12/10 |
| `data_0841_20260919.xlsx` | 340 | `KR4B056B7504` | Mini KOSPI C 202611 750.0 | 2026/11/12 |
| `data_0900_20260919.xlsx` | 3 | `KR4A01730006` | KOSPI200 F 202703 | 2027/03/11 |
| `data_2836_20260919.xlsx` | 5 | `KR4A05710004` | Mini KOSPI F 202701 | 2027/01/14 |
| `data_2923_20260919.xlsx` | 2 | `KR4B09FE9375` | KOSPI weekly C 2609W4 | 2026/09/23 |
| `data_2935_20260919.xlsx` | 2 | `KR4BAFBY9227` | KOSPI weekly-M C 2609W3 | 2026/09/21 |

The row numbers and values shown are taken from the historical XLSX cell contents. Because the source files are no longer in the working tree and the snapshot is dated 2026-09-19, refresh and re-archive the official export before treating the sample as current evidence.

## 4. Rule cross-check / discrepancies

- Monthly expiry values present in the snapshot (2026-10, 2026-11, 2026-12, 2027-01, 2027-02, 2027-03, 2027-06, 2027-09) coincide with the second-Thursday weekday candidate. This is a cross-check only; it is not the source of the stored dates.
- `data_2923_20260919.xlsx`: weekly option exact expiry is 2026-09-23 (Wednesday), while the next Thursday weekday candidate is 2026-09-24. This is a **discrepancy requiring official holiday evidence**; the cause is not asserted and no correction is applied.
- `data_2935_20260919.xlsx`: weekly-M exact expiry is 2026-09-21 (Monday), matching the Monday weekday label. No future weekly expiry vector is present in this snapshot.
- No mismatch is silently repaired. If an updated KRX master conflicts with a rule/holiday cross-check, the master value and evidence are recorded, and the row remains blocked until the discrepancy is understood.

## 5. D-4 counting examples (definition, not executable dates)

1. **Consecutive weekdays, illustrative only:** if expiry were Thursday D=0 and every prior weekday were confirmed as a KRX trading session, Wednesday would be D-1, Tuesday D-2, Monday D-3, and the prior Friday D-4. A real holiday invalidates this vector.
2. **Holiday week, illustrative only:** if the Monday before a Thursday expiry were an official KRX holiday, it is skipped; the previous actual session becomes the next counted day. The D-4 date must be recomputed from an archived official KRX session list. No concrete future date is assigned here because that list was not captured.

**User decision (2026-10-13): YES.** D-4 excludes expiry day D=0 and means the fourth actual KRX trading session strictly before expiry. Weekends, official holidays, temporary closures, and any other KRX non-trading sessions are skipped. This approves the counting convention only; it does not approve candidate dates for strategy/order use.

## 6. Scenario vectors — current state

The scenario definitions remain `NOT_RUN`. Candidate date vectors are now calculated from the historical exact-expiry master and the project?s KRX holiday caches (`2026.json`/`2027.json`); they are not approved for execution. Missing monthly expiry records remain `UNSET/BLOCKED`.

| ID | Required actual vector | Current value | Status |
|---|---|---|---|
| CAL-D4-01 | expiry 2026-11-12; candidate D-4 2026-11-06; evaluate 10:59:59 KST | 2026-11-12 / 2026-11-06 / 10:59:59 | NOT_RUN; convention approved, calendar/runtime unverified |
| CAL-D4-02 | expiry 2026-11-12; candidate D-4 2026-11-06; evaluate 11:00:00 KST | 2026-11-12 / 2026-11-06 / 11:00:00 | NOT_RUN; convention approved, boundary behavior unverified |
| CAL-D4-03 | expiry 2026-11-12; candidate D-4 2026-11-06; evaluate 11:00:01 KST | 2026-11-12 / 2026-11-06 / 11:00:01 | NOT_RUN; convention approved, boundary behavior unverified |
| CAL-DTE10-01 | expiry 2026-11-12; DTE=11 session | 2026-10-28 | NOT_RUN; candidate vector only |
| CAL-DTE10-02 | expiry 2026-11-12; DTE=10 session | 2026-10-29 | NOT_RUN; candidate vector only |
| CAL-DTE10-03 | expiry 2026-11-12; DTE=9 session | 2026-10-30 | NOT_RUN; candidate vector only |
| CAL-HOL-01 | expiry 2027-02-11; holiday cluster 20270208/09; candidate D-4 | expiry 2027-02-11 / D-4 2027-02-03 | NOT_RUN; cache-backed candidate vector |
| CAL-HOL-02 | expiry 2027-03-11; 2027-03-01 holiday between DTE10 and expiry | DTE11 2027-02-23 / DTE10 2027-02-24 / DTE9 2027-02-25 / expiry 2027-03-11 | NOT_RUN; cache-backed candidate vector |

## 7. U items / next evidence needed

- **U-CAL-01:** retrieve current KRX official option master export and preserve file, source URL, retrieval time, source date, and SHA-256.
- **U-CAL-02:** retrieve and archive the official KRX holiday/derivatives schedule for every month 2026-11 through 2027-10, including the listed holidays per month and temporary closures/notices.
- **U-CAL-03:** confirm refresh cadence, owner, and max-age threshold; all three remain UNSET.
- **U-CAL-04: RESOLVED 2026-10-13.** User confirmed D-4 strictly excludes expiry day and counts the fourth preceding actual KRX trading session.

Until U-CAL-01/02 are resolved, candidate D-4/DTE10 vectors remain non-executable and must not be used by a strategy or order path. Months without exact YYYYMMDD expiry remain UNSET/BLOCKED.

