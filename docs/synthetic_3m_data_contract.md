# Project200 3-Month Synthetic Market Data Contract

Version: 1.1
Status: implementation contract for scheduled DERIVED_SCENARIO generation
Scope: KOSPI200 regular monthly/weekly options; this is not REAL_VTS or Live data.

## 1. Non-negotiable principle

Scenario patterns may change the generated underlying path and scenario implied volatility, but may not change the exchange calendar, market session, contract identity, expiry, multiplier, option strike ladder, quote tick-size rules, or provenance. Missing authoritative contract/calendar information is UNAVAILABLE/BLOCKED; never fill it with invented exchange data.

## 2. Three-calendar-month horizon

- Select the latest available KRX Option Master snapshot not later than the current KST date.
- The snapshot date is the inclusive scenario start date.
- The end boundary is start date plus three calendar months, exclusive. Clamp the day to the last valid day if the target month is shorter.
- Generate every KRX trading date in [start, end_exclusive), using the year-specific KRX calendar snapshot. Exclude weekends and official holidays. Also load the calendar year(s) needed to resolve authoritative contract expiries beyond the horizon, including the next monthly rollover. If a required year calendar is absent, invalid, or not sourced from KRX, generation fails closed.
- The number of trading days and event rows is calculated from the actual horizon; never hard-code 63 trading days or 49,140 events as the correctness condition.

## 3. KRX KOSPI200 options session and sampling

- KRX regular session is 08:45–15:45 KST. The last trading day of an expiring option contract ends at 15:20 KST.
- The generated records are five-minute bar-start observations: 08:45, 08:50, …; normal session samples stop at 15:40, and the expiring monthly contract's samples stop at 15:15. Do not emit a quote timestamp at or after that contract's last-trading cutoff.
- Where a weekly contract expires during a day, do not emit that weekly contract after 15:15; monthly contracts that have not expired may continue through the normal session.
- Timestamp spacing must be exactly five minutes within each generated session. There must be no weekend/holiday observations.
- The dataset is regular-session-only. Night-session data must not be implied or fabricated.

Official reference: https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp

## 4. Contract identity, expiry, and lifecycle

- Select only the regular KOSPI200 option product family; exclude Mini KOSPI200 and unrelated products.
- Preserve the authoritative instrument code, option type, strike, product family, and multiplier from the selected KRX Option Master snapshot.
- The KOSPI200 options multiplier is KRW 250,000 per option point.
- Canonical exact expiry is YYYYMMDD. Keep contract month (YYYYMM) as a separate field; never invent a day from YYYYMM.
- Monthly options expire on the second Thursday of the contract month, adjusted to the previous trading day if the exchange calendar requires it, and the expiry must agree with the shared Option Master expiry resolver.
- Monday weekly contracts expire on Monday, pushed back to the next trading day if Monday is a market holiday. Thursday weekly contracts expire on Thursday except the second Thursday, brought forward to the previous trading day if Thursday is a market holiday.
- A weekly series that coincides with monthly expiry is not listed. Only weekly identities present in the authoritative snapshot may be emitted. Do not synthesize missing weekly contract codes, expiries, or strikes.
- On every emitted row, expiry must be exact, in the future or at the row timestamp's valid final-trading interval, and consistent with the identity source. No contract may survive beyond its last-trading cutoff.
- Month rollovers must use exact expiry and actual trading dates, not string-only YYYYMM assumptions.

Official reference: https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp

## 5. Scenario price and option valuation

- The initial underlying value must come from the same-date regular KOSPI200 futures daily authoritative source; exclude Mini futures. Missing, invalid, or conflicting source values block generation.
- A scenario pattern changes only the synthetic underlying path and its declared implied-volatility assumptions. It must not alter calendar dates, session times, contract identities, expiry, or multiplier.
- Calculate option theoretical values from underlying, strike, option type, implied volatility, and exact time remaining to the contract's last-trading cutoff (15:20 KST on expiry date). Use actual elapsed calendar time, including intraday time; do not use a one-day minimum time-to-expiry.
- Keep the pricing assumptions explicit in the manifest. This approximation uses zero risk-free rate and zero dividend yield unless authoritative input values are available.
- Time value is max(theoretical option value minus intrinsic value, 0). With spot, strike, and volatility held fixed, the theoretical value must not increase solely because time passes. Total option premium may rise or fall when spot or volatility changes.
- Align quoted option prices to KRX tick sizes: 0.01 point below 10 points of premium and 0.05 point at or above 10 points. Bid/ask must be positive and ask must exceed bid.
- KRX also applies phased daily option price limits of ±8%, ±15%, and ±20% relative to the option base price. The current collected inputs do not provide an authoritative prior-session base price for every generated contract, so this v1 does not claim to enforce those bands. The generated rows are DERIVED_SCENARIO valuation quotes for signal/replay testing, not exchange-valid executable quotes. Do not claim full exchange-mechanics compliance until per-contract base-price/limit handling is implemented and validated.
- Prices are scenario estimates, not exchange observations. Mark every row DERIVED_SCENARIO and preserve source hashes and assumption metadata.

## 6. Pattern rotation

Patterns rotate in this order:
trend_up → trend_down → mean_revert → high_volatility → low_volatility → shock

Changing pattern may change the path and volatility regime only. It may not change the three-month horizon, calendar, session sampling, expiry rules, identity set, or validation gates.

## 7. Required manifest and pre-replay gate

Manifest must include:
- rules version, DERIVED_SCENARIO provenance, pattern, seed, and exact start/end-exclusive horizon;
- KRX calendar source(s), Option Master path/hash/snapshot date, and initial underlying source path/code/field;
- session open/close and last-trading cutoff, bar interval, actual trading-day/event counts;
- exact monthly and observed weekly expiries/rollovers;
- contract multiplier and option valuation/tick-size assumptions;
- per-day event count, timestamp bounds, session type, and explicit contract coverage/unavailable reasons.

Before replay, the scheduled runner must validate:
1. the manifest rule version and source provenance;
2. the exact three-calendar-month date window and authoritative KRX trading dates;
3. no generated rows on weekends/holidays;
4. five-minute timestamps within the applicable session, including expiry cutoffs;
5. each row's exact YYYYMMDD expiry and source-backed contract identity;
6. expected event count computed from the manifest, per-day counts, and contiguous unique sequence IDs;
7. positive, tick-aligned bid/ask/last prices and ask > bid;
8. option time-to-expiry and valuation fields are internally consistent;
9. unavailable weekly coverage remains explicitly blocked and is not presented as full coverage;
10. the manifest carries the explicit daily-price-limit limitation and validation reports PASS_WITH_LIMITATION, never full exchange-mechanics PASS.

If any structural pre-replay check fails, write a BLOCKED_DATASET_VALIDATION result and do not start strategy replay. With the declared daily-price-limit limitation, the data may be used for DERIVED_SCENARIO signal/replay tests only, not to claim exchange-valid quote or execution-mechanics compliance. The Control Tower smoke remains a separate result and must not convert a failed dataset gate into PASS.

## 8. Scheduler safety

- Do not stop, disable, restart, or re-register the Windows task as part of code updates.
- Do not alter its repetition interval or queue policy without a separate explicit instruction.
- The running invocation may continue with the script version it already loaded; the next invocation must use the updated code.
- Preserve run-specific logs/results and never overwrite prior evidence.


## 9. Required authoritative input files and recovery procedure

The generator does not create substitute calendars, option identities, or underlying spot prices. Before generation, confirm these inputs exist and validate their source metadata:

| Required input | Required path/schema | Gate behavior when missing or invalid |
|---|---|---|
| KRX trading calendars | `data/calendar/krx/YYYY.json` for every year needed by the three-month horizon and expiry resolution; `source` must be `KRX`, and `year` must match the filename | Stop with `KRX_AUTHORITATIVE_CALENDAR_REQUIRED` or `KRX_AUTHORITATIVE_CALENDAR_INVALID` |
| KRX daily option snapshot | `data/historical/krx_raw/YYYYMMDD_options_daily.json`; non-empty `OutBlock_1` containing `ISU_CD`, `ISU_NM`, `RGHT_TP_NM`, and `PROD_NM`; at least four usable monthly expiries and required CALL/PUT coverage | Stop with the corresponding `KRX_AUTHORITATIVE_OPTION_MASTER_*` error |
| Same-date regular KOSPI200 futures daily snapshot | `data/historical/krx_raw/YYYYMMDD_futures_daily.json` using the exact option snapshot date; `OutBlock_1` must contain regular futures `ISU_CD=A016C000` with a positive `SPOT_PRC` | Stop with `KRX_AUTHORITATIVE_UNDERLYING_REQUIRED`, `KRX_AUTHORITATIVE_UNDERLYING_EMPTY`, or `INITIAL_UNDERLYING_SPOT_INVALID` |

### Obtaining a reproducible minimum input set

1. Obtain calendar snapshots from the approved KRX calendar collection process and retain the original source metadata. Do not create a weekday-only calendar or infer holidays.
2. Obtain the KRX daily option and futures snapshots from the approved KRX data collection process. The two daily files must share the same `YYYYMMDD` date; do not pair an option snapshot with a different day's futures spot.
3. Place the original files under the paths above without rewriting source rows. Record source URL/collection timestamp and SHA-256 in the collection evidence. Keep these local authoritative data files out of Git when repository policy ignores `data/`.
4. Run the generator, then the validator before starting any replay:

```powershell
py -m scripts.generate_authoritative_option_synthetic_3m --output data/synthetic/authoritative_option_3m --pattern mean_revert --seed 20061009
py -m scripts.validate_authoritative_option_synthetic_3m --dataset data/synthetic/authoritative_option_3m
```

Use the actual approved output directory and seed for the scheduled run; do not overwrite prior run evidence. If any required file cannot be obtained, record `BLOCKED_DATASET_VALIDATION` with the exact missing path/reason and stop. There is no synthetic-calendar or guessed-spot fallback.

### Contract multiplier provenance

The current KRX daily option snapshot schema does not contain a contract multiplier column. For that schema, the generator uses the documented regular KOSPI200 option contract specification (`250000`) and records `contract_multiplier_source=KRX_REGULAR_KOSPI200_OPTION_CONTRACT_SPEC` in the manifest. If an input row does provide a multiplier field, the generator validates that it is positive, unambiguous, and consistent with the regular-option specification; mismatch or conflicting fields block generation. Each emitted tick uses the multiplier attached to its parsed contract identity, and the validator checks both row values and manifest provenance. Mini options remain excluded.


Contract update note: v1.1 / `project200-synthetic-3m-v2` adds explicit multiplier-source provenance to the manifest and validates every emitted row against its parsed identity. Existing v1 manifests must be regenerated before they can pass the updated validator.
