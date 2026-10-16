# Strategy 8 — Macro Regime Monthly Strangle 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
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

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | DTE>=15 and budget>=200,000 triggers monthly long strangle; macro regimes attempt extra PUT protection. | Define monthly macro/tail-risk thesis, expected volatility event, payoff and maximum cost. | **미결정** |
| F02 | 적용 시장·상품 | Option Master selects listed PUT/CALL with same positive multiplier and symmetric 15-point offset around listed center. | General KOSPI200 options only; exact monthly expiry, IDs, multipliers, quote/tradability. | **부분 확인** |
| F03 | monthly lifecycle | Entry requires DTE>=15; DTE<=4 emits HOLD_LONG_ATTACK NON_EXECUTION; pending cancel event in session window. | Define monthly contract selection, calendar/expiry, overnight and final close policy without silently converting HOLD to close. | **미결정** |
| F04 | reference price/time | Current price and options analytics drive strike/moneyness; common input supplies budget/date/time. | Synchronized underlying/option quote/expiry/vol/regime/portfolio risk snapshot with provenance. | **미결정** |
| F05 | entry signal | DTE>=15, budget>=200,000, call/put multipliers positive/equal; qty based on regime. | Approve DTE/budget/regime gates and exact boundary semantics. | **미결정** |
| F06 | add-on/rebuild | Entry state active before fills; macro scale flag set before add-on fills; profit/rebuild emits signals without explicit proposals. | Separate initial entry, macro add-on, profit close and rebuild as distinct state transitions/plans. | **BLOCKED** |
| F07 | pending/cancel lifecycle | 15:00–15:15 event is NON_EXECUTION pending-tranche cancel; actual cancel confirmations/partial fill states not stored here. | Per-leg cancel request/confirmed/cancel-race/fill-after-cancel lifecycle and no re-entry until reconciled. | **미검증** |
| F08 | contract selection | Track8OptionContractSource requires exact listed symmetric ±15 pair and equal positive multipliers. | Exact YYYYMMDD expiry and product class/ID/quote/strike ticks validated. | **부분 확인** |
| F09 | strike/tick | offset=15; source fails if exact listed ±15 structure is absent; no nearest-strike fallback. | Define offset/tick rounding and approved fallback or explicit no-entry behavior. | **미결정** |
| F10 | macro regime/IV | Entry qty: HIGH_VOL PUT multiplier=2; otherwise multiplier=1.5 converted with int truncation to 1. Macro set HIGH_VOL/CIRCUIT_BREAKER/CRASH. | Define regime source, IV/skew/vol formulas, multiplier mapping and rounding. | **미결정** |
| F11 | moneyness/protection trigger | Uses options.moneyness call_distance/put_distance as intrinsic proxy; IV/ATM IV features exist but not entry trigger. | Define whether macro/IV/moneyness changes entry/add-on/exit; distinguish intrinsic value from time value/MTM. | **미결정** |
| F12 | quantity/capital/cost | CALL qty=1; normal PUT int(1*1.5)=1; HIGH_VOL PUT qty=2. MIN_BUDGET=200,000; profit target=300,000. | Editable total capital, premium cap, strategy/account max-loss, margin, fees/slippage, qty caps and budget semantics. | **수치 미확정** |
| F13 | order pricing/reprice | Entry proposal CALL BUY; pair plan creates CALL+PUT. Pricing label MID_PRICE_OFFSET but actual requested_price absent. | Per-leg limit price, net debit cap, tick/quote freshness, reprice/cancel/timeout rules. | **미결정** |
| F14 | group preflight | Resolver maps BUY proposals to full monthly pair plan regardless of tag; scale-up PUT-only intent can become full pair. | Tag-specific resolver must produce exactly the approved incremental or full plan; group risk check before routing. | **BLOCKED** — resolver/intent mismatch |
| F15 | partial/reject/unknown | Active state and macro_hedge_scaled update before fills; close callback resets only group_complete + position_flat. | Per-leg fill state, incremental quantity, rejection/cancel-race and actual position reconciliation. | **BLOCKED** |
| F16 | hedge/add-on role | Macro extra PUT computed with ceil; resolver may turn it into full pair instead of PUT-only add-on. | Explicit add-on role, extra quantity, contract identity, max exposure and rollback/recovery. | **BLOCKED** |
| F17 | holdings/exposure | State stores strikes/qtys/premium_spent=0, entry date, watermark and flags; exact expiry not stored in state. | Store exact contract identities/expiry, actual fills/remaining qty, cost basis and all-leg exposure. | **BLOCKED** — expiry/actual cost missing |
| F18 | stop/max loss | No authoritative strategy max-loss exit; DTE<=4 emits HOLD, not close. | Define premium-at-risk, max-loss/stress-loss and DTE policy; preserve HOLD behavior until user approves change. | **미결정** |
| F19 | take-profit/trailing | Intrinsic proxy based on moneyness distances; watermark is assigned before comparison, suppressing update signal; retain ratio=85%. | Actual pair MTM/P&L with qty/multiplier/fees, watermark update before comparison, target/trailing semantics. | **BLOCKED** |
| F20 | time/expiry | DTE<=4 HOLD_LONG_ATTACK; 15:00–15:15 cancel pending event; exact expiry stored nowhere in state. | Canonical expiry/calendar, exact cutoff, cancel-race and explicit terminal close/hold policy. | **미결정** — do not infer forced liquidation |
| F21 | close scope/qty | SELL proposal resolves from open lots to MONTHLY_STRANGLE_CLOSE; actual lots determine close plan. | Close all actual option legs and quantities; group flat confirmation before reset. | common principle aligned; per-leg behavior **미검증** |
| F22 | P&L/fees/slippage | portfolio.net_pnl/fees available for rebuild gate; take-profit uses moneyness proxy and premium_spent remains zero in shown path. | Separate expected, realized and unrealized P&L; per-leg premium, multiplier, fees, slippage and account attribution. | **BLOCKED** |
| F23 | trigger priority | evaluate concatenates entry, macro protection, take-profit, rebuild and expiry; multiple signals may coexist. | Deterministic priority and one compatible action plan per evaluation; no entry while exit/rebuild pending. | **미결정** |
| F24 | lifecycle/provenance | resolver routes BUY to pair plan and SELL to open-lot close; add-on tag not handled distinctly. | Stable group/parent group/leg/order/execution IDs and config hash; distinguish add-on group from original. | **BLOCKED** |
| F25 | restart/duplicate/timeout | reset clears state; durable state restore and idempotent macro scale not shown. | Restore exact expiry/positions/orders/add-on state/watermark before new evaluation. | **미결정** |
| F26 | cross-strategy/account risk | margin_ratio/risk_guard_active features affect rebuild; aggregate strategy/account exposure not proven. | Aggregate premium/margin/stress loss and shared options across all strategies before entry/add-on/rebuild. | **미결정** |
| F27 | data error/unavailable | required analytics include DTE, IVs, strikes, multipliers, moneyness, regime, P&L, margin and risk guard; missing metrics suppress action. | Missing/stale/mismatched contract/marks/account risk => UNAVAILABLE; no zero substitution or assumed expiry. | **부분 확인** — freshness/runtime enforcement needs evidence |
| F28 | editable settings | strategy constants/config registry includes DTE/budget/qty multipliers/trailing/margin limits; actual account capital/premium/max-loss enforcement not proven. | Versioned editable capital, premium max, strategy/account max-loss, budget, qty, expiry policy and hash. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | tests cover entry proposal and no-repeat macro signal; complete add-on resolver, watermark, DTE hold and risk scenarios not proven. | Test DTE/budget boundaries, qty rounding, add-on exact plan, trailing watermark, HOLD semantics, partial fills, expiry/restart/account risk. | **미완료** |

## 9. Strategy 8 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_MONTHLY_CONTRACT | entry permission/config version | unknown → BLOCKED |
| WAITING_FOR_MONTHLY_CONTRACT | authoritative monthly expiry/strikes | DTE_BUDGET_REGIME_PREFLIGHT | exact expiry, listed pair, budget and risk | missing source → UNAVAILABLE |
| DTE_BUDGET_REGIME_PREFLIGHT | DTE/budget/regime pass | ENTRY_PLANNED | approved qty rounding and pair plan | risk fail → no order |
| ENTRY_PLANNED | group plan persisted | ENTRY_WORKING | per-leg CALL/PUT order states | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | all initial legs filled | ACTIVE | actual quantities/cost/expiry confirmed | partial/reject → PARTIALLY_EXPOSED |
| ACTIVE | macro regime needs add-on | MACRO_ADDON_PREFLIGHT | exact incremental PUT qty and account risk | intent mismatch → BLOCKED |
| MACRO_ADDON_PREFLIGHT | approved add-on plan | MACRO_ADDON_WORKING | only incremental legs routed | partial/reject → PARTIALLY_EXPOSED |
| ACTIVE | profit/expiry/max-loss exit | EXIT_PENDING or approved HOLD | deterministic policy; HOLD is not a close | undefined → BLOCKED |
| EXIT_PENDING | partial/cancel race | EXIT_PENDING | actual remaining lots and orders | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | all option lots flat | FLAT_CONFIRMED | authoritative positions agree | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | P&L/fees finalized | CLOSED | persist monthly result/config hash | mismatch → BLOCKED |
| any active state | new month/restart/source failure | RECONCILIATION_REQUIRED | reconcile old group before new entry | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S8-F01~F06, F10~F12, F18~F20, F23 | core/strategy/track8_macro_regime_monthly_strangle.py | monthly thesis, DTE/budget/regime, HOLD/exit priority | BLOCKED |
| S8-F08~F09, F13~F14, F16, F24 | track8_option_contract_source.py, resolve_track8, build_pair_plan | exact pair identity, add-on-specific plan and group preflight | BLOCKED |
| S8-F07, F15, F17, F21, F25 | MultiLegBridge, PositionLotStore, callbacks | per-leg fill/add-on/close/restart evidence | INCOMPLETE |
| S8-F19, F22, F26, F28 | moneyness/mark/P&L/fee/margin/account risk providers | actual pair MTM, max-loss and account risk | BLOCKED |
| S8-F29 | tests/strategy/test_strategy8.py, Virtual integration | F01~F29-to-test map | INCOMPLETE |

Acceptance gates:
- A01: monthly contract and expiry are authoritative and retained in state.
- A02: macro add-on resolves to exactly the intended incremental legs/qty, not a full pair.
- A03: state updates only from authoritative fills; partial add-on has recovery policy.
- A04: take-profit uses actual quantity-aware marks/P&L and watermark logic is verified.
- A05: DTE<=4 HOLD semantics are explicitly approved or changed only by a new decision.
- A06: deterministic trigger priority and pending cancellation semantics.
- A07: editable capital/premium/strategy/account max-loss settings enforced.
- A08: all F01~F29 map to tests/evidence.
- A09: validation and user approval separate.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | monthly expiry/contract selection | Option Master and calendar | monthly lifecycle incomplete |
| D02 | budget definition and 200,000 threshold | capital, premium, margin, cost evidence | entry budget unapproved |
| D03 | normal PUT multiplier 1.5 rounding | payoff/risk and discrete contract quantities | current int truncation not target |
| D04 | macro add-on role/qty and resolver | stress payoff and exact incremental plan | add-on execution blocked |
| D05 | actual pair MTM and trailing | marks/fills/fees/multiplier | current proxy not authoritative |
| D06 | DTE<=4 HOLD vs close | expiry risk, market liquidity, approved policy | keep as observed behavior until approval |
| D07 | rebuild signal semantics | explicit proposal/action state machine | signals lack clear execution contract |
| D08 | capital/premium/max-loss numerical values | account capital/quotes/fees/margin/stress loss | separate approval required |
| D09 | account aggregate risk | all strategy positions and shared options | enforcement unproven |
| D10 | restart/partial fills/expiry state | order/fill/position provenance | lifecycle incomplete |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: macro add-on resolver mismatch, pre-fill state, intrinsic proxy/watermark update defect, expiry identity absent, DTE<=4 HOLD unresolved, account risk.
- Document structure only; no strategy scenario/E2E tests run.
- Code changes/commit/push/KIS Live orders: none.
- Next: Strategy 9 same F01~F29 depth.
