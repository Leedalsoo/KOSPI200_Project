# Strategy 8 — Macro Regime Monthly Strangle 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 현 코드: core/strategy/track8_macro_regime_monthly_strangle.py v2.0
- 연결: Option Master/AnalyticsSnapshot, resolve_track8, build_pair_plan, MultiLegBridge, risk/margin source.

## 1. 목적 — 미확정
현재 코드는 충분한 DTE와 예산이 있을 때 monthly CALL+PUT long strangle을 진입하고, regime stress 시 PUT 수량을 늘리려 한다. Monthly contract selection, payoff, loss budget, scale-up semantics and expiry policy는 재정립 대상이다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Entry DTE>=15; budget>=200,000; CALL/PUT multipliers positive and equal.
- CALL qty=1. HIGH_VOL PUT multiplier=2 → qty=2. Other regimes use 1.5 but int truncation makes qty=1.
- State is active before fills; proposal is CALL BUY and resolver creates full pair plan.
- Take profit uses moneyness distances as intrinsic proxy, retaining 85% of peak; close signal is PUT SELL and resolver uses open lots.
- Macro regimes: HIGH_VOL/CIRCUIT_BREAKER/CRASH. If active, extra PUT qty is computed and macro_hedge_scaled is set before fills.
- Resolver maps any BUY proposal, including MACRO_HEDGE_SCALE_UP, to full monthly pair plan instead of PUT-only incremental add. This is an intent/plan mismatch.
- evaluate_profit_rebuild returns DYNAMIC_PROFIT_TAKE and DYNAMIC_REBUILD_FENCE without explicit execution proposals; execution vs NON_EXECUTION semantics need definition.
- 15:00–15:15 emits NON_EXECUTION pending-tranche cancellation event.
- DTE<=4 emits NON_EXECUTION HOLD_LONG_ATTACK, not a close order. Do not silently change this to forced liquidation.
- premium_spent starts at zero and is not updated in the shown strategy path; exact expiry identity is not retained in state. In evaluate_take_profit, high_watermark_intrinsic is assigned before the comparison used to decide whether to emit UPDATE_TRAILING, so the comparison is against the just-assigned value and the update signal is effectively suppressed.

## 3. 목표 lifecycle
WAITING_FOR_MONTHLY_CONTRACT → DTE/BUDGET/REGIME_PREFLIGHT → ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ACTIVE → MACRO_SCALE_PENDING (optional) → TAKE_PROFIT/REBUILD/EXPIRY_POLICY → EXIT_PENDING or approved HOLD → FLAT_CONFIRMED → CLOSED.

Entry and macro scale-up are separate actions. Scale-up must send only approved incremental quantity and reconcile fills into state. DTE hold remains NON_EXECUTION unless an approved new spec changes it.

## 4. 필수 데이터
Exact monthly expiry/type/strike/instrument IDs/multipliers/quotes; budget definition; exact DTE/calendar; regime/IV/moneyness/marks/Greeks; per-leg premium/fills/fees; margin/risk guard/account exposure; authoritative open lots.

## 5. 미결정 항목
1. monthly contract selection and expiry roll.
2. budget meaning and minimum.
3. normal PUT ratio 1.5 rounding policy.
4. premium-spent and actual MTM accounting.
5. trailing/target/rebuild rules.
6. macro regime set, add-on quantity and incremental-vs-full-plan semantics.
7. DTE<=4 HOLD_LONG_ATTACK and acceptable expiry risk.
8. pending cancel request/confirmation/fills during cancellation.
9. rebuild signal semantics and authoritative contract selection.
10. account max loss/margin/fees/slippage.
11. partial fills/restart/expiry/session behavior.

## 6. 검증 시나리오
DTE 14/15/16; budget below/equal/above; regime quantity rounding; partial pair entry; macro scale before/after entry fill and repeated regime; verify resolver plan purpose/legs/qty for scale-up; moneyness vs actual marks; zero premium; P&L/risk guard boundaries; DTE 4/3/1/0; pending cancel race; restart/new month with residual lots.

## 7. 추적/판정
관련 코드: track8_macro_regime_monthly_strangle.py, resolve_track8, build_pair_plan, Option Master, risk/margin sources, MultiLegBridge.
**BLOCKED** — macro add-on resolver mismatch, P&L proxy, expiry identity and target policy unresolved.