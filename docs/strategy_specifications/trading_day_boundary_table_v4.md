# Trading Day Boundary Table v4 — DRAFT / NOT APPROVED

작성일: 2026-10-14 KST
상태: 검증 중 · 사용자 승인 대기 · 런타임 기준 아님

## 입력·정책
- Exact expiry: KIS REST output1.futs_last_tr_date provenance cache only. No YYYYMM or YYMMWn inference.
- Calendar: data/reference/calendar/holidays_2026_draft.json and holidays_2027_draft.json; both are unapproved drafts sourced from KRX cache as non-authoritative drafting input only.
- D-4: expiry D=0 excluded; count backward four candidate trading sessions (weekends and dates in the draft list excluded).
- DTE10 gate boundary: previous candidate trading session before the 10th trading session counted backward from expiry, consistent with current calculator convention that sessions-to-expiry counts sessions after as-of including expiry.
- All computed D-4/DTE10 dates below are CANDIDATE_ONLY; calendar approval and official KIS expiry coverage are not complete. Do not use for runtime.

## Monthly contracts — next 12 months
| Contract month | KIS exact expiry | D-4 candidate | DTE10 boundary candidate | Evidence/status |
|---|---|---|---|---|
| 2026-11 | 2026-11-12 | 2026-11-06 | 2026-10-29 | KIS exact-expiry cache; unapproved candidate calendar |
| 2026-12 | 2026-12-10 | 2026-12-04 | 2026-11-26 | KIS exact-expiry cache; unapproved candidate calendar |
| 2027-01 | 2027-01-14 | 2027-01-08 | 2026-12-29 | KIS exact-expiry cache; unapproved candidate calendar |
| 2027-02 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-03 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-04 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-05 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-06 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-07 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-08 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-09 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |
| 2027-10 | UNSET | UNSET | UNSET | No exact KIS expiry cache coverage; no YYYYMM inference |

## Weekly examples
| Product | KIS exact expiry | D-4 candidate | DTE10 boundary candidate | Evidence/status |
|---|---|---|---|---|
| Thursday weekly | 2026-10-15 | 2026-10-08 | 2026-09-29 | KIS exact-expiry cache sample; candidate calendar only |
| Monday weekly | 2026-10-19 | 2026-10-13 | 2026-10-01 | KIS exact-expiry cache sample; candidate calendar only |

## Required cross-checks / unresolved
- The draft calendar has not been approved by the user and is not runtime eligible.
- KIS annual holiday coverage is not proven; CTCA0903R prior VTS HTTP 500 and HHMCM000002C0 date-field semantics remain unresolved.
- Monthly exact expiries not found in the immutable KIS expiry cache remain UNSET. Weekly rows are samples only; they do not define future weekly expiries.
- Candidate dates are not evidence of official expiry-date shifting rules. KIS exact expiry remains authoritative; any mismatch must be reported, never corrected from a calendar rule.
- The D-4 11:00 KST cutoff transition requires separate boundary unit tests. CAL scenario-plan items remain NOT_RUN.

## Calendar hashes
- 2026 holidays_sha256: 4a2e448a60095a673fa9ac966a196eb79818e265647e3066a89ccbfd0ba36740; file SHA-256: 893be926fbe5f224ee55058d69c7e6fed955476877a72c2e8b73e096fa3cacbc
- 2027 holidays_sha256: 871282ecd66deac17e70bef7aa1434818100900ec831e07c9ac8f463ada49937; file SHA-256: fead755bac7aa6369af143823998b708b3ce99819518af55169819741950f9f9


## Addendum — Daily KIS trading-day source integration (2026-10-14)

- Separate from the unapproved annual candidate table above, the KIS VTS read-only `HHMCM000002C0` response has been integrated as a bounded daily source.
- Runtime code: `infrastructure/kis/daily_trading_day_provider.py`; `infrastructure/kis/trading_calendar.py`; `application/composition/option_master_factory.py`; `infrastructure/kis/kis_vts_weekday_collector.py`.
- Smoke/integration status: **PASS_DAILY_SOURCE_INTEGRATED** for 2026-10-14; KIS explicitly returned 2026-10-12 through 2026-10-16 and session 08:45–15:45. Evidence response hash: `9e7a93be93f9d6b701563a7e1e4c66abf9dce582b794f300dbeff4f19c8467c9`.
- The provider saves an immutable raw response snapshot with environment, TR ID, endpoint, source date, fetched UTC time, date list, session times, and response hash.
- A date listed by the KIS rolling response is positively confirmed. A date absent from the rolling list is UNKNOWN and must be resolved by a complete KIS annual calendar or an explicitly user-approved calendar; it is not inferred open/closed.
- Annual API retry: `CTCA0903R` returned HTTP 500 / `EGW02006` for VTS requests for 2026 and 2027. LIVE credentials were unavailable and no LIVE request was sent. Annual calendar remains BLOCKED.
- Therefore this addendum changes the daily source/runtime integration status only; it does not approve the annual candidate dates in the tables above or establish future expiry-shift rules.


## Addendum — Shared calendar composition refactor and runtime freshness audit (2026-10-14)

- Shared calendar construction is now centralized in `infrastructure/kis/trading_calendar_factory.py`. The factory owns the KIS daily provider and annual calendar resolver wiring; production option-master composition and the VTS weekday collector both call this shared factory.
- `application/composition/market_calendar_factory.py` is a compatibility re-export only. Strategy modules do not create their own `ProductionTradingCalendar`; source scan found the only direct constructor in the shared factory.
- Credential boundary preserved: the VTS collector passes LIVE auth only to annual `CTCA0903R` resolution and VTS auth only to daily `HHMCM000002C0`. No cross-environment fallback.
- Annual resolution is KIS-complete-calendar or explicitly user-approved/hash-verified list only. No KRX runtime fallback is wired. With no complete annual calendar, dates absent from the rolling response remain UNKNOWN/fail-closed.
- Validation: `py_compile` PASS for shared factory, calendar provider, option-master factory and VTS collector. Actual read-only integrations PASS for 2026-10-14 through both the production calendar and VTS collector; no order endpoints called. Offline contract checks PASS for listed-date confirmation, unknown-date fail-closed and weekend closure.
- Evidence: `verification/evidence/kis_production_calendar_daily_integration_20261014.json`; `verification/evidence/kis_vts_collector_calendar_daily_integration_20261014.json`; `verification/evidence/shared_calendar_factory_contract_20261014.json`.
- Runtime freshness/provenance audit: `infrastructure/kis/kis_rest_market_observation_normalizer.py` rejects unsuccessful responses, missing authoritative contract identity, KOSPI200 underlying mismatch and mismatched source timestamps. It records endpoint/TR IDs and source timestamp in provenance, but currently sets `observed_at=None`, `raw_reference=None`, and does not enforce a maximum quote age or carry an end-to-end freshness verdict to final order admission. End-to-end fail-closed propagation remains **BLOCKED / NOT_PROVEN**; no strategy behavior was changed to compensate.
- Annual holiday API remains BLOCKED: VTS `CTCA0903R` failed for 2026/2027 with `EGW02006`; LIVE credentials absent. VTS account binding remains BLOCKED pending account/API registration confirmation; no repeat API call was made.
- No Manifest changes, order/modify/cancel API calls, Git stage/commit/push, or restoration of deleted tests.
