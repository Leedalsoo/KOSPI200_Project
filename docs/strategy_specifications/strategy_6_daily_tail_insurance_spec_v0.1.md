# Strategy 6 — Daily Tail Insurance 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 현 코드: core/strategy/track6_daily_tail_insurance.py v1.0
- 연결: Track6ExecutionInput, Track6OptionContractSource, AnalyticsSnapshot, build_pair_plan, resolve_track6.

## 1. 목적 — 미확정
현 코드는 당일 변동성이 기준 대비 높을 때 long PUT+CALL insurance pair를 매수하고 같은 날 trailing/시간 cutoff로 청산하려는 구조다. 보호 대상, tail payoff 목적, 프리미엄/손실 예산은 미확정이다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Required analytics: price.last, active/base/ratio volatility, portfolio.premium_spent.
- ExecutionInput provides date/time, listed PUT/CALL strikes and multiplier.
- Entry if base_vol>0, active_vol >= base_vol*1.3, multiplier positive, both strikes exist. Default quantity 1.
- State is_active is set before pair fills. Entry proposal is PUT BUY; resolver/build_execution_plan creates PUT+CALL pair.
- Current take-profit uses strike-distance “intrinsic” proxy. It derives a multiplier from premium_spent/qty, not contract multiplier and actual marks, so it is not authoritative option pair MTM.
- Trailing activation uses 1.5x or 2.0x spent, then 85/88/90% retention tiers.
- Time exit: from LIMIT_CUTOFF to MARKET_CUTOFF request LIMIT close; at/after MARKET_CUTOFF request fallback close. Exact session constants need reconciliation with authoritative calendar.
- Close proposal is PUT SELL and resolver closes actual open lots. Reset requires group_complete and position_flat.

## 3. 목표 lifecycle
WAITING_FOR_SESSION → VOL_TRIGGER_CHECK → CONTRACT/BUDGET_PREFLIGHT → ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ACTIVE → TRAILING_OR_TIME_EXIT → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. “Daily” entry cap/reset must never hide an open prior-day position.

## 4. 필수 데이터
Authoritative session/calendar; active/base volatility formula/source/freshness; exact expiry/type/strike/instrument ID/multiplier; quotes/marks and fill prices for both legs; premium budget/max loss/fees/slippage; open lots and fill provenance; cancel/reject/partial state.

## 5. 미결정 항목
1. entry window and max entries/day.
2. 1.3 volatility trigger and baseline.
3. ATM/strike/expiry selection.
4. max premium/max loss and account capital gate.
5. actual pair MTM vs intrinsic proxy and trailing activation.
6. 1.5x/2.0x and 85/88/90 tier policy.
7. exact LIMIT_CUTOFF/MARKET_CUTOFF/PENDING_CANCEL_END handling.
8. one-leg/partial pair entry and emergency risk response.
9. daily reset only after both legs flat.
10. multiplier, fees/slippage and risk enforcement.
11. restart, stale quote and overnight residual handling.

## 6. 검증 시나리오
Volatility exactly around 1.3x; missing/stale strike/multiplier/quote; PUT-only/CALL-only/partial pair fill; premium_spent zero/stale; mark vs intrinsic mismatch; trailing tier boundaries; cutoff/limit/fallback/cancel-race; new date while prior position remains; partial close/restart/flat confirmation.

## 7. 추적/판정
관련 코드: track6_daily_tail_insurance.py, Track6OptionContractSource, resolve_track6, build_pair_plan, MultiLegBridge/PositionLotStore.
**BLOCKED** — P&L proxy and pre-fill active state are insufficient for approved execution.