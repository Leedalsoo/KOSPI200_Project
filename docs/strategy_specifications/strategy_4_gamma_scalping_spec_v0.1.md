# Strategy 4 — Gamma Scalping 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
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