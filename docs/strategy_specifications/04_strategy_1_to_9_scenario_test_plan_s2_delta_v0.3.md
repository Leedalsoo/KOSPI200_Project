# Strategy 1–9 scenario test plan — Strategy 2 delta v0.3

- 작성일: 2026-11-10
- 상태: USER-APPROVED TEST PLAN v0.3 / PLANNING ONLY / NOT_RUN
- 기준 명세: strategy_2_asymmetric_trap_spec_v0.5.md
- Current Baseline v2 SHA-256: 3FDC91266DE43EAB12EDAC50EB35200F824BC352024D21374F1DB93CD3880CB4
- U16 결정 근거: No.1491 및 No.1501–1505 (정책 반영, 테스트 실행은 아님)
- 이 문서는 기존 v0.2를 보존하며 새 정책 반영 시나리오를 추가한다. 시나리오 정의는 실행·검증 PASS가 아니다.

## A. U16 — partial fill / reject / cancel race

| Scenario | Event | Expected fail-closed target | Status |
|---|---|---|---|
| S2-V05-U16-01 | first leg partial fill, residual quantity remains | reconcile fill/leaves/position; calculate repair only under approved formula; no blind next leg | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U16-02 | later leg reject after earlier fills | use actual filled leg quantities for group repair decision; unresolved repair path blocks | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U16-03 | fill arrives during cancel request | wait for cancel terminal + fill/position reconciliation; include late fill | NOT_RUN / BLOCKED_INPUT |
| S2-V05-U16-04 | repair finally fails, or retry/time limit is exceeded | reconcile all order/fill/position state; apply full liquidation policy to already-filled legs and block group; if state is unclear, no duplicate order and RECONCILIATION_REQUIRED | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U16-05 | repair quantity calculation after partial fill/reject | repair only the missing quantity derived from confirmed actual fills after cancel/terminal, fill and position reconciliation | NOT_RUN |
| S2-V05-U16-06 | retry attempt begins | re-reconcile original/repair order terminal state, fills and positions before each retry; unknown state blocks retry | NOT_RUN |
| S2-V05-U16-07 | retry/time boundary | allow at most 3 additional retries after initial repair and at most 120 seconds from initial repair submission; either limit exceeded means repair failure | NOT_RUN |
| S2-V05-U16-08 | repair limit price | use best BID/ASK-based limit order; quote validity and fallback limits remain governed by U21 and are not inferred here | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U16-09 | final repair failure | policy requires full liquidation of already-filled legs with opposite-direction orders and group block; actual submission remains unauthorized | NOT_RUN / BLOCKED_SPEC |

## B. U20 — zero-fill cancellation

| Scenario | Event | Expected target | Status |
|---|---|---|---|
| S2-V05-U20-01 | cancel confirmed; cumulative fill=0; no working order; position reconciles | mark ZERO_FILL_CONFIRMED and advance sequence cursor; do not mark leg filled or group ACTIVE; all four target quantities still require fill/reconciliation or U16 repair | NOT_RUN |
| S2-V05-U20-02 | cancel requested but not confirmed | no next leg | NOT_RUN |
| S2-V05-U20-03 | cancel confirmed but fill/position query incomplete or late fill possible | no next leg; RECONCILIATION_REQUIRED | NOT_RUN |
| S2-V05-U20-04 | partial fill found after cancel | do not classify as zero-fill; route to U16 repair policy | NOT_RUN / BLOCKED_SPEC |

## C. U17 — contract selection

| Scenario | Event | Expected target | Status |
|---|---|---|---|
| S2-V05-U17-01 | two listed strikes equidistant from index price | select lower listed strike at/below index price | NOT_RUN |
| S2-V05-U17-02 | one or more offset strikes not listed | block; no inferred strike rounding | NOT_RUN / BLOCKED_INPUT |
| S2-V05-U17-03 | nearest expiry is not confirmed monthly series | block; do not substitute nearest expiry | NOT_RUN / BLOCKED_INPUT |
| S2-V05-U17-04 | multiplier/tradability missing for any of four legs | block whole group | NOT_RUN / BLOCKED_INPUT |

## D. U18 — group P&L

| Scenario | Event | Expected target | Status |
|---|---|---|---|
| S2-V05-U18-01 | valid BID/ASK for all four legs | use MID for each option mark | NOT_RUN |
| S2-V05-U18-02 | initial group net premium received <= 0 | block ratio/stop/trailing metric; no denominator substitution | NOT_RUN / BLOCKED_INPUT |
| S2-V05-U18-03 | realized and unrealized P&L with fees/slippage | include fees/slippage in both | NOT_RUN |
| S2-V05-U18-04 | cumulative net loss reaches approved stop percentage | trigger close only after percentage is approved | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U18-05 | pullback from maximum cumulative net profit reaches approved pullback percentage | trigger trailing close only after percentage is approved | NOT_RUN / BLOCKED_SPEC |

## E. U19 — restart reconciliation

| Scenario | Event | Expected target | Status |
|---|---|---|---|
| S2-V05-U19-01 | broker position and persisted ledger agree | broker position is primary; ledger is supplementary | NOT_RUN |
| S2-V05-U19-02 | broker position and ledger disagree | block resume/flat; apply no invented adjustment | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U19-03 | broker position unavailable or stale | block resume and new entry | NOT_RUN / BLOCKED_INPUT |
| S2-V05-U19-04 | pending order or late fill across restart | reconcile terminal order/fill/position before resume | NOT_RUN / BLOCKED_INPUT |

## F. U21 — quote fallback and order price

| Scenario | Event | Expected target | Status |
|---|---|---|---|
| S2-V05-U21-01 | BID/ASK missing | conservative fallback only if approved formula yields valid price; otherwise block | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U21-02 | quote stale or spread above approved limit | apply approved conservative fallback or block | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U21-03 | fallback output violates tick/price bounds | block; do not round by guessed rule | NOT_RUN / BLOCKED_SPEC |
| S2-V05-U21-04 | no valid fallback | block order | NOT_RUN |

## G. Shared acceptance constraints

- All four contracts must be authoritative standard KOSPI200 options with exact monthly expiry, strike, option type, broker symbol, multiplier and tradability.
- Entry group risk/cost preflight must pass before any leg.
- Runtime state must be fill/position-driven; signal/ACK is not fill.
- S2 natural-signal Runtime E2E and FAST/DETAILED parity require same dataset hash, manifest, scenario, run scope and clock.
- No KIS Live, REAL_VTS, account API or actual orders are included in this plan.
- No.1501–1505 policy decisions are reflected in the expected outcomes; they do not constitute execution evidence. All scenarios remain NOT_RUN. The 2026-11-09 S25 catalog is stale against this plan and current SSOT.
