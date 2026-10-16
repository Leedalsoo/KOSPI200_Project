# Strategy 2 — Asymmetric Trap 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 현 코드: core/strategy/track2_asymmetric_trap.py v1.0
- 연결: automated_virtual_runtime_factory.py resolve_track2, Track2PlanAdapter, Option Contract Source, common Analytics, MultiLegBridge.

## 1. 목적 — 미확정
현재 구현은 변동성·거래량·미세구조·IV skew를 사용해 short strangle과 더 안쪽 long option을 조합하는 4-leg trap을 시사한다. 최종 목적, 방향별 위험, 손익 목표, premium-neutral 조건은 사용자 확인 전 확정하지 않는다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- 필수 analytics: volatility.bbw, volume.z_score, microstructure.obi, futures.basis, options.put_iv, options.call_iv, volume_profile.poc, volatility.active/base. 누락/unavailable이면 신호 없음.
- 진입 게이트: bbw truthy, volume z-score >3, abs(OBI)>0.5, basis>0.3, abs(price-POC)>1.0.
- 가격이 POC 위면 PUT IV < CALL IV, 아래면 CALL IV < PUT IV 조건을 사용한다.
- active_vol <= base_vol*0.85: short CALL/PUT ATM±10, long CALL/PUT ATM±5. 그 외 short ATM±7.5, long ATM±2.5. 기본 수량 1씩이며 resolver가 4-leg plan을 구성한다.
- 일일 entry cap=2, 손실 후 cooldown=15분. cutoff 시 evaluate_trap을 호출하지만 cutoff만으로 강제청산하지 않는다.
- STOP_LOSS_RATIO=-30%는 underlying current_price/entry_price 변화 기준이며 actual option-pair P&L이 아니다.
- trailing activation +30%; high-watermark tier 50%/100%에 따라 85/88/90% 유지.
- state는 진입 체결 전 _trap_active로 바뀐다. 진입의 partial/reject 결과를 동기화하는 명시적 callback 경로가 부족하다.
- TRAP_CLOSE는 open lots로 종료 plan을 만든다. 만기/expiry 정책은 없다.
- trailing close 후 short-switch timer가 일부 경로에서 초기화되지 않아 다음 lifecycle에 잔존할 수 있다.

## 3. 목표 lifecycle
DISABLED → DATA_WARMUP → PRE_ENTRY_CHECK → ENTRY_PLANNED → ENTRY_WORKING → PARTIALLY_EXPOSED/ACTIVE → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. Partial, reject, timeout, cancel-race, restart는 RECONCILIATION_REQUIRED로 분기한다.

## 4. 필수 데이터와 주문 계약
- underlying/POC/volume/OBI/basis/BBW/IV source, units, timestamps, freshness.
- Option Master의 일반 KOSPI200 option, exact YYYYMMDD, type, strike, instrument ID, multiplier.
- 각 leg의 bid/ask, depth, tick, premium, fill, fees/slippage.
- 4-leg별 독립 주문/체결 상태와 group 전체 net premium, max loss, Greeks/exposure.
- order type, mid-price offset 1 tick, reprice interval, timeout, cancel/replace 규칙은 새로 승인한다.

## 5. 미결정 항목
1. zero-cost wide/narrow trap의 실제 경제적 정의와 선택 목적.
2. 4-leg 유지 여부, 각 leg의 역할/ratio/strike rounding.
3. OBI/basis/IV skew 방향과 결합 논리.
4. STOP_LOSS가 underlying move인지 actual net P&L인지.
5. trailing을 actual option pair MTM 기준으로 바꿀지.
6. daily 2회 카운트 기준, cooldown 시작/손실 판정 source.
7. expiry, cutoff, overnight 규칙.
8. partial entry 후 wait/cancel/reprice/hedge/rollback/close 우선순위.
9. premium budget, max loss, margin, fee/slippage gate와 account risk.
10. pre-fill state를 authoritative fills로 전환하는 방법.

## 6. 검증 시나리오
Feature unavailable/stale/threshold 경계; OBI±0.5, basis 0.3, POC 거리 1.0; wide/narrow 경계; 모든 4-leg fill/partial/reject/timeout/cancel-race; stop/trailing tiers; 15분 cooldown, 날짜 변경, daily cap; expiry; restart; stale quote와 contract identity mismatch; actual flat 전 중복 close 방지.

## 7. 추적/판정
관련 코드: track2_asymmetric_trap.py, build_trap_plan, resolve_track2, Option Contract Source/Track2PlanAdapter, MultiLegBridge/PositionLotStore.
**BLOCKED** — P&L proxy, pre-fill state, expiry 및 partial-fill risk policy 미확정.