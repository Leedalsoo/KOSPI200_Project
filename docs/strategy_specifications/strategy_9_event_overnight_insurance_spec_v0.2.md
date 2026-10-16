# Strategy 9 — Event Overnight Insurance 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track9_event_overnight_insurance.py v3.0
- 연결: Track9 ATM IV/Option Master sources, AnalyticsSnapshot, resolve_track9, build_pair_plan, MultiLegBridge.

## 1. 목적 — 미확정
현 코드는 장 마감 전 PUT+CALL 보험을 매수해 다음 거래일 시초 급변을 보호하는 overnight strangle을 의도한다. 코드는 외부 macro/event/IV indicators를 entry trigger로 쓰지 않는다고 명시한다. Overnight risk budget, opening reference and payout acceptance criteria remain unresolved.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Entry time=15:10; opening window end=MarketSessionPolicy.STABILIZATION_END; opening shock threshold=1%; trailing profit giveback=30%; pair qty default=1.
- Entry requires time>=15:10, entered_today false, valid positive underlying price, ATM PUT/CALL strikes and multiplier. It does not visibly reject times after official close.
- State becomes OVERNIGHT_INSURANCE_AWAITING_FILLS before actual pair fills. Entry proposal PUT BUY; resolver builds PUT+CALL pair.
- Filled leg prices are synced from same-day VSSF fill metrics. Entry premium=(put fill+call fill)*qty*multiplier. If either fill metric missing, state remains awaiting fills; no explicit one-sided-exposure timeout manager exists here.
- Next session: if abs(opening move)<1%, close pair; if shock>=1% and pair current profit>0, activate trailing. Peak profit trails with 30% giveback. If no shock/no trailing, close. At window end without trailing, close.
- Marks calculate pair value; close plan uses authoritative open lots. Callback resets only after group_complete and position_flat.
- State lacks exact option expiry identity.

## 3. 목표 lifecycle
WAITING_ENTRY → ENTRY_WINDOW_OPEN → CONTRACT/QUOTE/RISK_PREFLIGHT → PAIR_ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ENTRY_FILLED_AND_RECONCILED → OVERNIGHT_HOLD → NEXT_SESSION_OPENING_WINDOW → NO_SHOCK_EXIT or SHOCK_PROFIT_TRAILING or WINDOW_TIMEOUT_EXIT → EXIT_PENDING → FLAT_CONFIRMED → CLOSED.

No shock is not proof both legs filled. Partial/unknown entry requires an approved recovery policy and blocks duplicate entries. Unknown overnight exposure must not be silently carried or reset.

## 4. 필수 데이터
Official session close and next trading calendar; exact ATM strikes/expiry/contract IDs/multiplier; actual per-leg fill price/qty/fees; next-session opening price and pair marks with timestamps; authoritative open lots; order/fill/cancel state across restart.

## 5. 미결정 항목
1. latest allowed entry time and after-close data behavior.
2. ATM definition, strike selection and expiry.
3. max premium/max overnight loss/account risk.
4. pair fill deadline and one-leg fill response.
5. opening reference and shock denominator.
6. opening stabilization window and holiday/timezone.
7. trailing mark source and fees.
8. shock but nonpositive pair profit; stale marks; no opening data.
9. terminal exit if quote unavailable.
10. expiry/restart/missed session/residual lots.
11. whether IV/event history sources remain informational only.

## 6. 검증 시나리오
15:09:59/15:10/official close/after close; missing strike/multiplier/quote; one-leg/partial fills; weekend/holiday; opening move below/equal/above 1%; pair profit negative/zero/positive; 30% giveback; exact window end; exit partial/reject/cancel-race; restart during overnight hold; no next-session data; account premium budget.

## 7. 추적/판정
관련 코드: track9_event_overnight_insurance.py, Track9 ATM IV/Option Master sources, resolve_track9, build_pair_plan, MultiLegBridge/PositionLotStore.
**BLOCKED** — after-close entry gate, partial entry recovery and max overnight risk unresolved.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | Buy near-close PUT/CALL pair to insure next session open; intentionally independent of macro/event/IV triggers. | Define overnight exposure protected, protection horizon, expected payout and max premium/overnight loss. | **미결정** |
| F02 | 적용 시장·상품 | ATM-ish PUT/CALL option pair; multiplier and listed strikes required. | General KOSPI200 options only, exact identity/expiry/multiplier and no Mini options. | **부분 확인** |
| F03 | entry/overnight lifecycle | ENTRY_TIME=15:10; no upper bound explicitly blocks post-close entry. Next session opening window ends at MarketSessionPolicy.STABILIZATION_END. | Official session close/last-entry cutoff, next trading day calendar, holidays and missed-session behavior. | **BLOCKED** — after-close entry gate |
| F04 | reference price/time | entry_price uses price.last at entry; opening move uses next-session price.last vs entry price. | Official entry reference and official opening reference, source/as-of/freshness, time zone and same-snapshot pair marks. | **미결정** |
| F05 | entry signal | entry if time>=15:10, not entered_today, price/strikes/multiplier positive. | Explicit entry window [start,end), valid quote/contract and risk gates. | **미결정** |
| F06 | repeat entry/rebuild | entered_today is set on entry; _sync_date exists but evaluate does not call it. close callback retains entry_date/entered_today. | Reset daily eligibility only after calendar advances and prior position is confirmed flat; idempotent entry key. | **BLOCKED** — daily flag lifecycle |
| F07 | pending/cancel lifecycle | state becomes AWAITING_FILLS before pair fills; missing entry prices leaves state waiting, with no explicit one-leg timeout manager. | Per-leg ACK/partial/reject/cancel/cancel-race and fill deadline; protect/reduce residual leg per approved policy. | **BLOCKED** |
| F08 | contract selection | ATM call/put strikes, multiplier and marks come from Analytics; exact expiry is not stored in Track9State. | Exact YYYYMMDD, contract IDs, standard product class, strike/tick, quote freshness and expiry identity. | **BLOCKED** — expiry identity absent |
| F09 | strike/tick/liquidity | Strategy consumes ATM strikes from analytics; no selector or liquidity/limit-price logic inside core strategy. | Authoritative Option Master/quote source, strike tick, bid/ask/depth and price collar. | **미결정** |
| F10 | IV/event regime | ATM IV/event materializer/time series sources exist in runtime, but strategy deliberately does not use external event/IV indicators for entry. | Keep that boundary only if approved; otherwise specify exact IV/event features and their use. | **미결정** — confirm intentional dependency boundary |
| F11 | opening shock/stabilization | shock = abs((next-session price.last - entry price)/entry price) >=1%; uses first available price rather than explicit official open. | Define official open, denominator, boundary equality, opening window and missing/late first tick. | **미결정** |
| F12 | quantity/capital/cost | pair_quantity default=1; entry premium=(put fill+call fill)*qty*multiplier. No explicit premium/account max-loss gate in strategy. | Editable total capital, strategy premium cap, strategy/account max-loss, fees/slippage, pair qty and overnight stress limits. | **수치 미확정** |
| F13 | order price/reprice | Entry proposal PUT BUY; resolver builds PUT+CALL pair. requested_price absent. | Per-leg limit/price source, net debit cap, repricing/cancel/timeout and fill deadline. | **미결정** |
| F14 | group preflight | build_pair_plan creates pair; account/margin/fee sources exist in contracts/runtime. Full preflight gate not proven here. | Both legs contract/quote/premium/margin/max-loss/account risk validated before submission. | **미검증** |
| F15 | partial/reject/unknown | Entry state stays awaiting fills if one/both fill metrics unavailable; no explicit one-leg exposure timeout. Close callback resets only group_complete + position_flat. | Independent leg fills/positions and approved partial recovery; unknown entry must block duplicate/assumed overnight state. | **BLOCKED** |
| F16 | hedge/add-on role | No Futures hedge; pair-only overnight insurance. | Do not add other instruments without separately approved role; track pair as one protection group. | **부분 확인** |
| F17 | holdings/exposure | State tracks entry prices/premium/qty/strikes but no exact expiry or per-leg actual lot IDs. | Authoritative position lots, per-leg fills/remaining qty, marks, Greeks, premium and overnight exposure. | **미검증** |
| F18 | stop/max overnight loss | no explicit hard premium/max-loss stop; close decisions are no-shock, trailing profit or window end. | Max premium/overnight stress loss, market unavailable emergency policy and risk-off priority. | **미결정** |
| F19 | take-profit/trailing | if shock>=1% and pair current_profit>0 activates trailing; peak profit giveback=30%. | Actual marks/fills/fees, net P&L, high-watermark and giveback thresholds; define shock but nonpositive profit path. | **미결정** |
| F20 | time exit/expiry/rollover | close at no shock; at exact OPENING_WINDOW_END equality close if trailing inactive; if evaluation skips exact end timestamp, later times return no close. No expiry state. | Use >= window-end terminal condition, exact expiry and next trading session calendar; close even if no tick at exact boundary. | **BLOCKED** — equality-only window exit |
| F21 | close scope/quantity | SELL proposal maps to pair close plan from open lots; proposal quantity is entry qty. | Actual open lots determine per-leg close quantities; no reset until both PUT/CALL flat. | common principle aligned; per-leg reconciliation **미검증** |
| F22 | P&L/fees/slippage | Current value=(PUT mark+CALL mark)*qty*multiplier; entry premium uses fills; current profit=current value-entry premium; fee ledger not directly used in shown strategy. | Net P&L includes fees/slippage/contract multiplier and actual fills/marks, with account attribution. | **미검증** |
| F23 | trigger priority | no-shock exit, shock+positive-profit trailing, trailing giveback, opening window end; priority overlaps with missing data/expiry. | Deterministic max-loss, expiry, no-shock, trailing and window-timeout priority; no contradictory signals. | **미결정** |
| F24 | lifecycle/provenance | Entry group built from canonical signal; close resolver marks exit pending and closes open lots; per-leg entry order state not durable in strategy. | run/group/leg/order/execution/position/P&L provenance across close/restart and config hash. | **미검증** |
| F25 | restart/duplicate/timeout | reset clears state; durable restore/missed session handling not shown; daily entered_today may remain true after close. | Restore overnight lots, entry date, fills, expiry, opening window and timers; no blind re-entry or reset. | **BLOCKED** |
| F26 | cross-strategy/account risk | margin/fee/position read models exist; strategy logic does not show explicit aggregate account risk gate. | Aggregate overnight premium, margin, correlated event stress and existing hedges across all strategies. | **미결정** |
| F27 | data failure/unavailable | strategy requires positive price/marks/multiplier for opening decision; missing data returns no close signal. | If quote/opening data unavailable, keep explicit UNAVAILABLE and execute approved fallback close/reconciliation; never silently hold unknown risk. | **BLOCKED** |
| F28 | editable settings | ENTRY_TIME and trailing giveback configurable; opening shock threshold and pair qty constructor; capital/premium/max-loss enforcement not proven. | Versioned editable total capital, premium cap, strategy/account max-loss, pair qty, entry window, shock threshold, fees/margin and hash. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | tests cover pair plan and qty preservation; complete after-close, opening-window skipped tick, one-leg fill, daily reset and account risk tests not proven. | Test entry cutoff, calendar, opening shock boundaries, missing marks, partial pair, skipped window-end tick, restart and max loss. | **미완료** |

## 9. Strategy 9 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_ENTRY_WINDOW | permission/config version | unknown → BLOCKED |
| WAITING_FOR_ENTRY_WINDOW | allowed session window begins | CONTRACT_QUOTE_PREFLIGHT | enforce entry end before official close | after-close → BLOCKED |
| CONTRACT_QUOTE_PREFLIGHT | both contracts/quotes/budget pass | ENTRY_PLANNED | exact expiry/IDs, premium reserve, stable group ID | any leg fails → no order |
| ENTRY_PLANNED | plan persisted | ENTRY_WORKING | independent PUT/CALL order/fill state | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | both legs filled/reconciled | OVERNIGHT_HOLD | actual fill premium, lots and expiry confirmed | partial/reject → PARTIALLY_EXPOSED |
| OVERNIGHT_HOLD | next trading session begins | OPENING_WINDOW | official open/shock and pair marks validated | missing data → UNAVAILABLE with approved fallback |
| OPENING_WINDOW | no shock or shock with nonpositive P&L | EXIT_PENDING | close pair from actual open lots | missing close plan → BLOCKED |
| OPENING_WINDOW | shock and positive P&L | TRAILING_ACTIVE | actual pair net P&L watermark | stale marks → RECONCILIATION_REQUIRED |
| TRAILING_ACTIVE | giveback/window end/max-loss | EXIT_PENDING | terminal priority and close all open lots | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | partial/cancel race | EXIT_PENDING | per-leg remaining qty | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | pair flat confirmed | FLAT_CONFIRMED | executions and position read model agree | mismatch → BLOCKED |
| FLAT_CONFIRMED | fees/P&L finalized and calendar day advanced | CLOSED / WAITING_FOR_ENTRY_WINDOW | reset daily eligibility only after reconcile | prior residual → BLOCKED |
| any active state | restart/no next-session data/API failure | RECONCILIATION_REQUIRED | restore orders/fills/lots/expiry before new entry | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S9-F01~F06, F10~F12, F18~F20, F23 | core/strategy/track9_event_overnight_insurance.py | entry window, opening shock, trailing/timeout priority | BLOCKED |
| S9-F08~F09, F13~F14 | track9 authoritative sources, resolve_track9, build_pair_plan | exact contracts, quote and group preflight | INCOMPLETE |
| S9-F07, F15, F17, F21, F24~F25 | Track9 position/execution read models, callbacks, MultiLegBridge | per-leg partial/overnight/restart/all-flat evidence | BLOCKED |
| S9-F22, F26, F28 | fee ledger, margin read model, account risk config | net P&L, overnight max-loss and account risk | BLOCKED |
| S9-F29 | tests/strategy/test_strategy9.py, Virtual integration | F01~F29-to-test map | INCOMPLETE |

Acceptance gates:
- A01: exact entry window ends before official close; after-close orders prohibited.
- A02: exact option identities/expiry and pair quote/budget validated.
- A03: state transitions to overnight hold only after both legs' actual fills and lots reconcile.
- A04: one-leg/partial fill recovery and overnight timeout policy approved.
- A05: official next-session opening reference, shock threshold and opening window are source-backed.
- A06: window-end exit uses >= and survives missing ticks/restarts.
- A07: actual pair P&L includes fills/marks/multiplier/fees/slippage.
- A08: editable capital/premium/strategy/account max-loss settings enforced.
- A09: all F01~F29 map to tests/evidence; validation separate from user approval.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | latest entry time/after-close policy | official session calendar and quote availability | current entry gate blocked |
| D02 | ATM/expiry selection | Option Master, expiry and quote identity | contract policy incomplete |
| D03 | premium/max overnight loss/account capital | account capital, option quotes, fees, margin, stress | numerical limits require separate approval |
| D04 | one-leg fill timeout/recovery | actual execution and risk scenarios | overnight exposure blocked |
| D05 | opening reference/shock denominator | official open source and synchronized marks | trigger not approved |
| D06 | opening stabilization window and missed tick | MarketSessionPolicy/calendar and replay scenarios | current equality-only close can miss exit |
| D07 | shock but nonpositive pair profit | payoff/exit priority and market liquidity | terminal path unresolved |
| D08 | stale quote/no opening data | broker and position read model, fallback close policy | risk can remain open |
| D09 | expiry/restart/missed session | exact expiry, persistent order/fill/position state | lifecycle incomplete |
| D10 | account-wide risk and IV dependency boundary | all strategy exposure; approved strategy thesis | enforcement/thesis unresolved |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: after-close entry gate, state before fills, one-leg timeout, exact expiry absent, daily flag not reset, equality-only opening window end, missing-data fallback and account risk.
- Document structure only; no strategy scenario/E2E tests run.
- Code changes/commit/push/KIS Live orders: none.
- Next: revise the integrated matrix after all 9 strategy specs exist; then validate cross-strategy interactions and omissions.
