# 요구사항-명세-코드-테스트 추적표 — S9 delta v0.3

- 상태: draft / unverified / unapproved
- 기준 HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 기존 03_requirements_spec_code_test_traceability_v0.2.md 보존.
- 테스트는 실행하지 않았다. 모든 계획 항목 NOT_RUN; legacy tests는 새 의도의 PASS 증거가 아니다.

## S9 F01–F29 추적

| Req ID | v0.3 요구사항 | 명세 | 코드/런타임 비교 경로 | 테스트 계획/상태 |
|---|---|---|---|---|
| S9-F01 | S1 short PUT 부분 보험 | S9 spec §1 | core/strategy/track9_event_overnight_insurance.py | TP-S9-N01; NOT_RUN |
| S9-F02 | 표준 KOSPI200 OTM PUT | §4 | Option Master, resolve_track9 | exact identity; NOT_RUN |
| S9-F03 | S1 PUT 보유 후 trigger | §4–5 | existing entry is time-based | TP-S9-N02; NOT_RUN |
| S9-F04 | authoritative S1 position/time | §4, §11 | S1 position read model/provider | source confirmation; BLOCKED |
| S9-F05 | target-vs-actual quantity/idempotency | §4–5 | strategy state/runtime resolver | duplicate/restart; NOT_RUN |
| S9-F06 | link ratio scaling | §3–4 | current S1 link path not verified | TP-S9-N03; NOT_RUN |
| S9-F07 | per-leg partial/cancel/fallback | §5–6 | MultiLegExecutionPlan/ExecutionReport | TP-S9-E01/E02; NOT_RUN |
| S9-F08 | rank 4 then rank 3 | §4–5 | current ATM pair; no rank selector verified | TP-S9-N04; NOT_RUN |
| S9-F09 | min volume/quote gap/freshness | §3, §7 | current ATM analytics/quotes | U30/U32; NOT_RUN |
| S9-F10 | exact YYYYMMDD expiry | §4 | Track9State lacks expiry field | TP-S9-B04; NOT_RUN |
| S9-F11 | qty/multiplier/fees | §4, §7 | actual fill/Position/PnL/fee ledger | TP-S9-N05; NOT_RUN |
| S9-F12 | no monthly cap; common account risk applies | §3, §6 | common Risk/account aggregate gate | TP-X01-S9; BLOCKED |
| S9-F13 | 30-min LIMIT and cancel-confirm | §5 | current pair entry; no rank fallback verified | TP-S9-B02; NOT_RUN |
| S9-F14 | config/contract/quote/risk preflight | §3, §6 | runtime Risk/OMS route | null/provisional gate; NOT_RUN |
| S9-F15 | late fill/cancel race/partial | §5–6 | ExecutionReport/Position | TP-S9-E01/E02/E09; NOT_RUN |
| S9-F16 | PUT-only, no event/overnight pair | §1 | current code still emits PUT/CALL pair | legacy difference |
| S9-F17 | actual S1/S9 lots and exposure | §4, §6 | authoritative position lots | TP-S9-E05; BLOCKED |
| S9-F18 | no invented S9 stop; common risk remains | §2–3 | common Risk controls | enforcement not verified |
| S9-F19 | configurable take-profit multiple | §3, §7 | no matching v0.3 path verified | TP-S9-N06; NOT_RUN |
| S9-F20 | DTE7 roll and S1 DTE4 conflict | §4–5, U35 | calendar/Option Master/S1 state | TP-S9-B05; BLOCKED |
| S9-F21 | close actual open lots | §5–6 | Position Read Model/MultiLegBridge | TP-S9-E06; NOT_RUN |
| S9-F22 | rebuy <= prior buy ×1.30 same instrument | §4–5 | no rebuy path verified | TP-S9-B03/N07; NOT_RUN |
| S9-F23 | deterministic trigger priority | §5, U36 | runtime event/order manager | simultaneous triggers; BLOCKED |
| S9-F24 | config version/hash/provenance | §3, §6 | run/group/leg/order/execution/position metadata | TP-S9-R01; NOT_RUN |
| S9-F25 | restart/pending order recovery | §5–6 | state persistence/runtime reconciliation | TP-S9-R01/R02; NOT_RUN |
| S9-F26 | S1/S9 and account aggregate risk | matrix delta §5 | common Risk/margin/premium model | TP-X01–X04; BLOCKED |
| S9-F27 | null/stale/mismatch fail-closed | §3, §11 | runtime gate enforcement not verified | TP-S9-E07; NOT_RUN |
| S9-F28 | PROVISIONAL settings/version log | §3 | config loader/runtime consumer | TP-S9-B06; NOT_RUN |
| S9-F29 | acceptance evidence/REAL_VTS split | §7 | REAL_VTS dataset/run manifests | no test executed; BLOCKED |

## Code-Intent Difference IDs
- DIFF-S9-01: PUT/CALL pair vs PUT-only insurance.
- DIFF-S9-02: fixed 15:10 time gate vs S1 actual short PUT trigger.
- DIFF-S9-03: ATM strikes vs rank 4/rank 3 OTM ladder.
- DIFF-S9-04: next-session opening shock vs no event/opening trigger.
- DIFF-S9-05: fixed 30% giveback trailing vs configurable take_profit_multiple.
- DIFF-S9-06: no 130% same-instrument rebuy path verified.
- DIFF-S9-07: no DTE7 close/next-expiry roll; exact expiry absent from state.
- DIFF-S9-08: no S1 linked quantity, cancel-confirm fallback or corresponding config enforcement verified.

## Evidence rules
Existing tests/strategy/test_strategy9.py tests the old behavior. Do not reuse its pass result as v0.3 validation. Static source inspection is not runtime verification. No test ID was executed and no REAL_VTS result was produced. Future PASS requires spec/config hash, S1 position snapshot, exact YYYYMMDD identity, timestamps, order/fill/position provenance, fees, risk snapshots and final reconciled state.

## S9 user decision traceability amendment (2026-10-12)
- S9-EXIT-STOP-LOT: per-lot actual entry fill x 0.50 threshold; exit remaining quantity for that lot. Evidence: lot-level entry fills, fresh premium mark, close fills, final position reconciliation.
- S9-EXIT-TRAIL-LOT: arm at per-lot premium >= 2.00 x actual entry; track per-lot high-water; exit on >=10% drawdown from peak. Evidence: entry price, peak series, trigger quote, close fills, state persistence/restart evidence.
- S9-HOLD-INDEPENDENT: S1 exposure=0 must not by itself close S9 lots; maintain independent lots through DTE7 rollover unless stop/trailing closes first. Evidence: S1 flat snapshot, S9 lot inventory, expiry and rollover logs.
- S5-U16…S5-U20 are namespaced; S1 U16…U29 remain unchanged. Test execution remains NOT_RUN; requirements are not implementation PASS.

## User-confirmed DTE7/restart/priority traceability (2026-10-12; NOT_RUN)
- S9-DTE-TRADING-DAYS: compute DTE from authoritative trading calendar; rollover reference time 11:00 KST. Evidence: calendar/version, expiry YYYYMMDD, session-day calculation and timestamp.
- S9-NEXT-EXPIRY-DELAY: if next monthly expiry is unlisted at 11:00, monitor listing and defer order; only trade after listing and full preflight. Evidence: Option Master snapshots/listing timestamp, selected contract identity, quote/risk preflight.
- S9-LOT-RESTORE: restore per-lot actual entry fills, remaining qty, expiry/contract, trailing state and high-water mark on restart; mismatch/missing state blocks order. Evidence: persisted snapshot vs broker fills/positions, restart reconciliation log.
- S9-QUOTE-FILL-RECON: same-contract fresh quote required; partial/late fills and residual positions must be reconciled; ACK/cancel request is not terminal confirmation. Evidence: quote timestamps, order/execution IDs, broker positions and reconciliation result.
- S9-TRIGGER-PRIORITY: trailing exit > stop-loss > DTE7 rollover. Exit-triggered lot is excluded from rollover/re-entry until actual fills and position reconciliation complete. Evidence: simultaneous-trigger event trace and per-lot final position.


## Additional S9 traceability — calendar / freshness / recovery (2026-10-12; NOT_RUN)
- S9-CALENDAR-SOURCE: KRX official derivatives calendar + exact contract expiry/listing snapshot; test weekend, holiday, exceptional closure, expiry inclusion/off-by-one, and delayed next-month listing. Evidence: calendar version/hash, expiry YYYYMMDD, included sessions, computed DTE, 11:00 KST timestamp.
- S9-QUOTE-FRESHNESS: approve no numeric threshold until KIS option REST/WS timestamp semantics are confirmed and VTS age/clock-skew/spread/depth observations are assessed. Evidence: source/receive timestamps, quote age, transport, contract identity and config hash.
- S9-RESTART-RECON: restore per-lot entry fills/price, residual quantity, exact contract/expiry, trailing flag, high-water mark and last event timestamp; compare with broker order/execution/position data. Missing/mismatch/duplicate/late/partial fill must fail closed.
- Detailed expected outcomes and minimum invariants are in `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`. Static inspection only; NOT_RUN.

---
## v0.4 — S9 D-4/liquidity trace
- S9-D4-01: four remaining KRX sessions at 11:00 KST trigger mandatory exit; boundary/calendar vectors — NOT_RUN.
- S9-PRI-02: simultaneous expiry close dispatch order S1 then S9; bounded starvation test — NOT_RUN.
- S9-LIQ-03: third strike illiquid means wait/recheck same exact contract; no arbitrary price/strike substitution — BLOCKED until quote freshness/liquidity/retry settings are evidenced.
- S9-ROLL-04: DTE7 rollover no longer overrides D-4 forced exit in latest draft; verify no rollover reactivation after restart — NOT_RUN.
