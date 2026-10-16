# Strategy 4 — Gamma Scalping 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track4_gamma_scalping.py v1.0
- 연결: Track4 Greeks provider, AnalyticsSnapshot, delta hedge sizing, resolve_track4, MultiLegBridge.

## 1. 목적 — 미확정
현 코드는 옵션 basecamp 상태 이벤트와 options delta 기반 Mini Futures rebalance를 결합한 gamma scalping 형태다. Basecamp가 실제 옵션 포지션인지, 어떤 계좌/전략 포지션의 delta를 hedge하는지 확정되지 않았다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- active_vol <= base_vol*0.85면 ATM±2.5 wide basecamp; active_vol >= base_vol*1.30이면 ATM CALL/PUT basecamp. 둘 다 NON_EXECUTION 이벤트이며 옵션 주문을 생성하지 않는다.
- basecamp_active는 Futures hedge 실행의 필수 조건으로 검사되지 않는다.
- 필수 analytics: active/base/ratio vol, options.delta, current P&L, equity, tick deadband.
- equity >= threshold면 active. abs(delta)<=deadband이면 no-op.
- target absolute Futures qty=min(delta_to_mini_futures_qty(abs(delta)),100). delta>0이면 signed target negative/SELL; delta<0이면 positive/BUY.
- adjustment=target_signed_qty-state.active_hedge_qty이며, active_hedge_qty는 order fill 전 목표값으로 갱신된다.
- equity threshold 미만이면 hedge unwind. callback은 group_complete/position_flat 후 active hedge state를 지운다.
- trailing high P&L >30,000 and premium_spent available; ratio >=2.0/1.3/other uses 90/88/85% retention. Trigger closes only Futures hedge, not option basecamp.
- active hedge가 없으면 trailing event is NON_EXECUTION.

## 3. 목표 lifecycle
OPTION_POSITION_CONFIRMED → GREEKS_VALIDATED → TARGET_DELTA_COMPUTED → HEDGE_PLAN → HEDGE_WORKING → POSITION_RECONCILED → REBALANCE/UNWIND → FLAT_CONFIRMED. Target quantity state updates only from authoritative fills and open lots.

## 4. 필수 데이터
Option position identity/qty/side/multiplier; Greeks source/unit/as-of/freshness; underlying quote; active/base vol; deadband formula; Futures identity/multiplier/point value/margin/quote; account equity/margin/P&L/premium/fees; execution reports and position provenance.

## 5. 미결정 항목
1. Basecamp actual trade vs state-only event.
2. Which option positions supply delta and whether delta is per-contract or aggregate.
3. delta sign/unit/multiplier and hedge direction formula.
4. deadband, rebalance cadence, maximum delta error and qty cap=100.
5. equity threshold and account-wide risk limits.
6. trailing closes Futures only or also option positions.
7. order pricing/retry/cancel/partial-fill and state reconciliation.
8. expiry/session/overnight/restart.
9. gamma P&L vs theta decay and transaction costs.

## 6. 검증 시나리오
Basecamp absent/present with nonzero delta; positive/negative/zero/stale delta; deadband boundaries; target qty 0/1/100/>100; adjustment direction reversal; partial/rejected hedge; equity threshold crossing; trailing thresholds; missing premium; wrong contract/multiplier; partial unwind/restart; concurrent strategies contributing portfolio delta.

## 7. 추적/판정
관련 코드: track4_gamma_scalping.py, Track4 Greeks provider, delta_hedge_quantity, resolve_track4, MultiLegBridge/PositionLotStore.
**BLOCKED** — option ownership/basecamp and delta units are undefined; target qty updates before fills.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | Options delta 기반 Futures hedge와 state-only basecamp를 결합한 gamma scalping 형태. Basecamp option은 실제 주문이 아니다. | 보호/수익 대상 option lots, gamma/theta economics, hedge objective and expected risk reduction을 정량 정의한다. | **미결정** — option ownership/thesis 필요 |
| F02 | 적용 시장·상품 | Strategy emits Mini Futures proposal; basecamp only NON_EXECUTION. | 일반 KOSPI200 option identity와 Futures identity를 분리하고 permitted product/multiplier를 master에서 검증한다. | **부분 확인** — basecamp product/position relation 미정 |
| F03 | 운용 주기·활성화 경계 | basecamp cutoff uses MarketSessionPolicy; hedge path is not gated on basecamp_active. | session/entry/hedge windows, option expiry, overnight and reactivation rules explicit. | **미결정** |
| F04 | 기준가격·시점 | RuntimeInputMaterializer enforces tick, runtime source and Greeks timestamps equal; history must exist. | synchronized quote/Greeks/account/position snapshot with source time, receive time, identity and freshness. | **부분 확인** — actual option lot snapshot identity needed |
| F05 | 진입/basecamp condition | active_vol<=base_vol*0.85 emits wide ATM±2.5 state event; active_vol>=base_vol*1.30 emits ATM pair state event; no option order. | Decide whether basecamp is conceptual state or executable option pair; if executable, contract/quote/risk preflight required. | **미결정** |
| F06 | 추가 진입/rebuild | basecamp_active suppresses further basecamp event; hedge rebalance may run regardless of basecamp state. | Define hedge eligibility from authoritative option positions and prevent unowned delta or duplicate basecamp lifecycle. | **BLOCKED** — hedge not gated by actual option position |
| F07 | 주문/취소 lifecycle | Futures rebalance signal is emitted; target state changes before fill. | Per-order ACK/working/partial/cancel/reject/timeout/cancel-race and fill-confirmed target state. | **BLOCKED** — pre-fill target update |
| F08 | Option/Futures contract identity | Runtime Greeks provider supplies aggregate delta; resolver builds Futures plan via current Futures identity. | Option Greeks mapped to exact option lots; Futures symbol/expiry/multiplier/tick/quote authoritative. | **BLOCKED** — option lot ownership/identity not proven |
| F09 | Delta/Gamma/Theta units | Delta input is Decimal and delta_to_mini_futures_qty(abs(delta)) converts quantity; sign rule is delta>0→SELL, delta<0→BUY. | Define per-contract vs aggregate delta, multiplier, point value, portfolio net delta, Greeks units and sign conventions. | **미결정** — dimensional correctness/ownership needed |
| F10 | Volatility/regime | active/base volatility used for basecamp tiers; analytics also supplies volatility ratio. | Source/window/unit, threshold boundaries and regime change effect on active hedge. | **미결정** |
| F11 | Tick deadband/price history | no hedge when abs(delta)<=price.tick_deadband; deadband comes from analytics; current price history required. | Define deadband formula in delta units, update cadence, max tolerated residual delta and stale-history handling. | **미결정** — key name suggests price ticks but compared to delta |
| F12 | Quantity/capital/cost | target_abs_qty=min(delta_to_mini_futures_qty(abs(delta)),100); equity threshold defaults to zero; no premium/max-loss cap here. | Editable total capital, strategy premium/max-loss, account max-loss, margin/fee/slippage, qty cap and hedge notional limits. | **수치 미확정** |
| F13 | Order price/reprice | Futures proposal requested_price=None; no strategy price/collar/reprice policy. | Futures bid/ask tick, limit order/collar, reprice/timeout/cancel/replace, liquidity and price-band controls. | **미결정** |
| F14 | Risk preflight | resolver creates a Futures plan; standard RiskGate exists. Strategy-specific group/account risk proof absent. | Validate position-reducing vs opening order, margin, max qty, account risk and stale quote before each rebalance. | **미검증** |
| F15 | Partial/reject/unknown | active_hedge_qty is assigned target_signed_qty before execution confirmation. Callback clears state only for completed flat unwind/trailing. | Keep target quantity separate from actual filled quantity; reconcile partial/reject/cancel-race and actual open lots. | **BLOCKED** |
| F16 | Hedge/rebalance role | adjustment=target signed qty minus stored active_hedge_qty; proposal qty is abs(adjustment). | Calculate adjustment from authoritative current Futures lots and target delta; prevent duplicate in-flight rebalance. | **미결정** — current state uses target not actual qty |
| F17 | Holdings/exposure | Track4State stores active_hedge_qty, basecamp_active, high P&L and is_active; no per-lot Futures identity in state. | Actual Futures lots and option exposure linked by group/provenance; separate target, pending and filled qty. | **미검증** |
| F18 | Stop/risk exit | equity<threshold triggers hedge unwind; no explicit delta error/max-loss hard stop shown. | Define account equity guard, max-loss/stress-loss, max delta error and safe terminal unwind priorities. | **미결정** |
| F19 | Profit/trailing | high current P&L>30,000 with premium_spent available; retention 85/88/90% by high/premium ratio. Closes Futures hedge only. | Use strategy-attributed P&L and fees; define if trailing should close hedge only or the underlying option portfolio as a separate policy. | **미결정** |
| F20 | Time/expiry/overnight | Basecamp stops emitting after market cutoff; no option expiry/rollover path in strategy. | Exact expiry/session cutoff, option position close policy and hedge-to-option lifecycle linkage. | **BLOCKED** — expiry/option lifecycle absent |
| F21 | Close scope/qty/side | unwind side/qty is derived from signed state.active_hedge_qty; if that target diverged from fills, close may mismatch actual lots. | Close direction/qty from authoritative Futures open lots and confirm flat after all fills. | **BLOCKED** — target qty not actual position |
| F22 | P&L/fees/theta | Analytics provides portfolio.current_pnl and premium_spent; gamma/theta fields on input are not used by shown strategy decision. | Strategy-attributed Futures hedge P&L + option MTM/theta decay + fees/slippage with timestamped marks. | **미결정** |
| F23 | Trigger priority | evaluate emits basecamp, then delta hedge, then trailing signals; no explicit precedence prevents simultaneous conflicting signals. | Deterministic priority: risk/expiry > reconcile/unwind > rebalance > profit trailing > basecamp; one compatible plan per evaluation. | **미결정** |
| F24 | Lifecycle/provenance | Resolver uses stable group id suffix for Futures hedge; basecamp is NON_EXECUTION and not linked to authoritative option lots. | Link option position group, hedge group, evaluation, orders, fills and P&L with distinct identities. | **미검증** |
| F25 | Restart/duplicate/timeout | reset clears all state; durable restore and in-flight rebalance idempotency not shown. | Restore target/actual hedge, orders/fills/lots, Greeks snapshot and config hash before rebalancing. | **미결정** |
| F26 | Cross-strategy/account risk | Uses portfolio-wide current P&L/equity/delta input but ownership/strategy attribution is not established. | Aggregate net delta by authoritative lots, avoid double-hedging delta already hedged by other strategies, enforce account max loss. | **BLOCKED** |
| F27 | Data failure/unavailable | strategy feature validation requires all analytics available; materializer rejects tick/Greeks timestamp mismatch and incomplete readiness. | Any stale/mismatched Greeks, equity, position, quote or source causes UNAVAILABLE; no guessed delta/zero. | common fail-closed aligned; end-to-end enforcement **미검증** |
| F28 | Editable limits/config | equity_threshold constructor parameter and hard-coded qty cap 100; editable capital/premium/max-loss enforcement not proven. | Versioned editable total capital, strategy premium cap, strategy/account max-loss, equity threshold, delta deadband and qty cap. | **수치·강제경로 미확정** |
| F29 | Tests/acceptance | tests cover positive delta sells 3 contracts and deadband no-op only. | Test Greeks sign/units, option ownership, cap boundary, partial fills, target/actual divergence, unwind, trailing, expiry, restart and account limits. | **미완료** |

## 9. Strategy 4 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | explicit ON/config valid | WAITING_FOR_SESSION | strategy permission and config version | unknown config → BLOCKED |
| WAITING_FOR_SESSION | synchronized option/Greeks/account/Futures sources | OPTION_POSITION_RECONCILIATION | verify exact option lots and aggregate delta ownership | mismatch → UNAVAILABLE |
| OPTION_POSITION_RECONCILIATION | actual option lots and Greeks match | DELTA_VALIDATED | confirm units/multiplier/source timestamps | mismatch → BLOCKED |
| DELTA_VALIDATED | target delta/qty computed | HEDGE_PRECHECK | target vs actual lots, deadband, cap and account risk | risk fail → BLOCKED |
| HEDGE_PRECHECK | approval and idempotency key | HEDGE_WORKING | order per leg and independent status | uncertain route → RECONCILIATION_REQUIRED |
| HEDGE_WORKING | actual fills reconciled | HEDGE_ACTIVE | actual Futures lots set active hedge qty | partial/reject → PARTIALLY_HEDGED |
| HEDGE_ACTIVE | delta changes outside band | REBALANCE_PENDING | target from authoritative option lots and actual Futures position | stale source → BLOCKED |
| any active state | equity/max-loss/expiry/terminal trigger | UNWIND_PENDING | close from actual open Futures lots; option close policy separate | no policy → BLOCKED |
| UNWIND_PENDING | partial/unknown fills | UNWIND_PENDING | actual remaining qty and cancel race | unknown → RECONCILIATION_REQUIRED |
| UNWIND_PENDING | Futures hedge flat confirmed | HEDGE_FLAT_CONFIRMED | verify actual Futures lots flat; do not infer option flat | mismatch → RECONCILIATION_REQUIRED |
| HEDGE_FLAT_CONFIRMED | option lifecycle and accounting reconciled | CLOSED or OPTION_POSITION_ACTIVE | retain/release option exposure only per approved policy | unresolved option state → BLOCKED |
| any active state | restart/API/source failure | RECONCILIATION_REQUIRED | restore orders/fills/positions/Greeks/config before new rebalance | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S4-F01~F06, F16~F19, F23 | core/strategy/track4_gamma_scalping.py | option ownership, delta economics, trigger priority tests | BLOCKED |
| S4-F04, F08~F11, F17, F22, F27 | track4_market_input_materializer.py, track4_runtime_input_provider_factory.py, Track4 Greeks provider, core/analytics/track4.py | identity/units/freshness/P&L source evidence | INCOMPLETE |
| S4-F07, F12~F15, F20~F21, F24~F25 | resolve_track4, MultiLegBridge, Futures execution/position read model | target-vs-fill, partial/unwind/restart tests | BLOCKED |
| S4-F26, F28 | core/risk, account/fee/margin sources, editable risk config | account delta aggregation and limits tests | BLOCKED |
| S4-F29 | tests/strategy/test_strategy4.py and Virtual E2E | F01~F29-to-test evidence | INCOMPLETE |

Acceptance gates:
- A01: basecamp is explicitly classified as state-only or an executable option group.
- A02: delta source is tied to exact option positions and correct contract multiplier.
- A03: target and actual Futures qty remain separate; rebalance only after fills/reconciliation.
- A04: equity/max-loss/expiry/trailing priorities are deterministic.
- A05: actual option P&L, Futures P&L, theta, fees and slippage are separately attributed.
- A06: all-strategy delta/account risk prevents duplicate or conflicting hedges.
- A07: editable total capital/premium/max-loss settings are versioned and enforced.
- A08: F01~F29 link to test IDs and actual evidence.
- A09: validation and user approval remain separate.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | Basecamp is real option trade or state-only | strategy payoff and authoritative option positions | gamma scalping thesis incomplete |
| D02 | Which option lots determine delta | option identity, qty, side, multiplier, Greeks source | hedge ownership blocked |
| D03 | Delta/deadband units and conversion | Greeks contract definitions and Futures point value | sizing correctness unproven |
| D04 | target qty cap/equity threshold/max delta error | account capital, margin, stress scenarios | risk limits unapproved |
| D05 | trailing closes hedge only or option group | option P&L, gamma/theta, hedge economics | terminal behavior unresolved |
| D06 | order pricing/partial-fill recovery | quotes, broker behavior, execution reports | safe rebalance blocked |
| D07 | expiry/session/restart | KRX calendar, exact expiry, persisted positions | lifecycle incomplete |
| D08 | editable total capital/premium/max-loss values | capital, premium, fees, margin and stress analysis | separate approval required |
| D09 | cross-strategy delta ownership | all strategy positions and current hedges | double-hedging risk |
| D10 | P&L attribution and theta cost | authoritative option marks and Futures fills | trailing economics not verified |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: basecamp is not an option order; hedge not gated by confirmed option position; target qty changes before fills; delta/deadband units and cross-strategy ownership unresolved; trailing closes Futures only; expiry absent.
- 문서 구조 검사 only; no strategy scenario/E2E tests.
- Code changes/commit/push/KIS Live orders: none.
- Next: Strategy 5 same F01~F29 depth.
