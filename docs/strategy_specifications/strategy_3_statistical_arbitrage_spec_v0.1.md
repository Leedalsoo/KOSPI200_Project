# Strategy 3 — Statistical Arbitrage 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 현 코드: core/strategy/track3_statistical_arbitrage.py v1.0
- 연결: Track3 runtime input, common Analytics, execution_cost estimator, Track3PlanAdapter, Futures identity source, MultiLegBridge.

## 1. 목적 — 미확정
현재 구현은 spread z-score mean reversion, regime별 threshold/size/cost gate를 시사한다. 실제 spread 구성, 자산 조합, 양쪽 leg의 경제적 역할은 확정되지 않았다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- 기본 z-entry=2.0, z-exit=0.2, stop=3.5, max holding=300 evaluate calls, min expected net profit=15,000, base round-trip cost=10,000.
- HIGH_VOLATILITY: threshold=max(2.2, 2.0*vol_ratio*1.2), min profit 1.5x, qty=1.
- EXTREME_MOVE: threshold=999, entry blocked.
- GAP: threshold=max(2.0, 2.0*1.1), min profit 1.3x, qty=1; market_stable와 spread_normalizing 둘 다 필요.
- Other regime: threshold=max(1.5, 2.0*vol_ratio); abs(z)>=2.5 and allow_size_up이면 qty=2.
- expected gross=abs(z)*spread_std*0.8*contract_multiplier*qty, net=gross-cost. 이전 exit z와 차이가 0.8 미만이면 재진입 차단.
- _signal은 Futures proposal을 만들고 resolver/Track3PlanAdapter가 execution plan을 구성한다.
- position/group/leg state는 실제 fill 확인 전에 진입 평가에서 설정된다. Track3MultiLegExecutionPlanAdapter는 hedge_identity == identity를 강제하고 동일 instrument identity에 같은 qty의 반대 side legs를 만든다. 따라서 현재 계획은 순노출을 상쇄할 수 있으며, spread 차익거래라는 전략 목적과 모순될 수 있다. 신규 명세에서 두 leg가 다른 상품/identity인지 또는 단일 Futures leg인지 확정해야 한다.
- evaluate_input에서 _exit_pending을 확인할 때 regime이 아직 할당되지 않아 pending 경로에서 UnboundLocalError가 날 수 있다.
- cutoff, trailing, z-stop, timeout, convergence+profitability 순서로 exit signal을 생성한다. trailing high-watermark는 portfolio current P&L + options P&L, premium-spent ratio를 사용한다.
- close resolver는 open lots를 기준으로 만들고 callback은 group_complete와 position_flat 후 상태를 초기화한다.

## 3. 목표 lifecycle
DATA_WARMUP → REGIME_VALIDATION → COST_AND_EDGE_CHECK → ENTRY_PLANNED → ENTRY_WORKING → ACTIVE/PARTIAL → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. 미정 spread identity, 같은 계약의 반대 leg, unavailable cost/multiplier는 fail-closed한다.

## 4. 필수 데이터
Spread 구성식과 timestamp alignment; z-score window/mean/std/warmup/outlier; regime enum/source; gap/stability definition; futures symbol-to-identity; multiplier/cost/fees/slippage units; portfolio P&L attribution; run/group/leg provenance; authoritative fills/positions.

## 5. 미결정 항목
1. 실제 spread가 구성되는 instruments와 가격.
2. SHORT_SPREAD/LONG_SPREAD의 정확한 order sides와 leg quantities.
3. HEDGE_LEG의 목적 및 동일 Futures identity를 허용할지.
4. 15,000 profit threshold, 30,000 trailing activation 및 -5,000 exit tolerance의 근거.
5. 300 evaluations를 elapsed time으로 볼지 call count로 유지할지.
6. group_integrity 갱신 주체, partial fill/restart/roll behavior.
7. close cost, current P&L, options P&L, premium_spent의 authoritative source.
8. cutoff/overnight/contract expiry와 account-wide risk.

## 6. 검증 시나리오
z threshold/0.2/3.5 경계, regime별 edge; missing multiplier/cost; spread leg same-identity/opposite-side; _exit_pending path; gap stable/normalizing combinations; entry/exit partial fill; duplicate close; 300th call/cutoff; zero premium; stale analytics; restart/reconciliation.

## 7. 추적/판정
관련 코드: track3_statistical_arbitrage.py, core/analytics/execution_cost.py, resolve_track3/Track3PlanAdapter, Futures identity source, MultiLegBridge.
**BLOCKED** — pending 경로 오류 후보, spread 정의와 Futures leg identity/역할 미확정.