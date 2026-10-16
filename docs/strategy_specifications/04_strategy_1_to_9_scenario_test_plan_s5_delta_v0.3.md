# Strategy 5 시나리오 테스트 계획 S5 delta v0.3

- 상태: draft / unverified / unapproved
- 작성일: 2026-10-12
- 기존 `04_strategy_1_to_9_scenario_test_plan_v0.2.md` 보존. 본 파일은 S5 시나리오 추가안이다.
- 실행 금지 범위: 본 작업에서는 어떤 테스트도 실행하지 않는다. 시나리오 설계만 한다.

| ID | 시나리오 | 입력/경계 | 기대 상태/안전 기준 |
|---|---|---|---|
| S5-T01 | 갭 없음 | abs(open-prev_close) < min_gap_pt | NO_TRADE_TODAY, 주문 없음 |
| S5-T02 | 갭 임계값 하한 | gap=min_gap_pt-ε | 거래 없음 |
| S5-T03 | 갭 임계값 정확 경계 | gap=min_gap_pt | 명세의 inclusive `>=` 기준으로 갭 방향 ATM 옵션 BUY 계획; authoritative gap input이 유효하지 않으면 BLOCKED |
| S5-T04 | 갭 임계값 상한 | gap=min_gap_pt+ε | ATM 갭 방향 옵션 BUY 계획 |
| S5-T05 | 갭 상승 | positive gap, valid CALL ATM ask | CALL BUY, qty/contract identity 검증 |
| S5-T06 | 갭 하락 | negative gap, valid PUT ATM ask | PUT BUY, qty/contract identity 검증 |
| S5-T07 | advance 전 반전 | favorable move < advance_pt, reverse >= hedge_reversal_pt | 반대 옵션 1계약 hedge 계획 |
| S5-T08 | advance 경계 | move=advance_pt±ε | 전/후 상태가 결정론적으로 분기 |
| S5-T09 | advance 후 이익 청산 | move >= advance_pt, peak retracement >= gap×ratio | hedge 신호가 아니라 profit exit |
| S5-T10 | reversal minimum | ratio-derived retracement vs reversal_min_pt | max 조합은 검증 후보로 비교, 확정 전 실행 금지 |
| S5-T11 | 재반전 | hedge open, direction returns | hedge close, original option P&L/fills reconcile |
| S5-T12 | 휩소 첫 회 | whipsaw count=1 | 정책에 따른 관찰/대사; count definition 미확정이면 BLOCKED |
| S5-T13 | 휩소 두 번째 회 | count=whipsaw_limit=2 | 당일 신규 거래 전면 중단 및 청산 계획 |
| S5-T14 | 30분 종료 직전 | elapsed=session_minutes-ε | 세션 종료 action 미실행 |
| S5-T15 | 30분 종료 경계 | elapsed=session_minutes | session_end_action null이면 BLOCKED; 후보별 테스트 |
| S5-T16 | 30분 종료 이후 | elapsed=session_minutes+ε | 신규 진입 금지; 종료 정책 적용 후 잔여 노출 대사 |
| S5-T17 | session_end_action 후보 | close_all / hold / close_hedge_only 각각 독립 시나리오 | 결과 비교만 수행; 어떤 후보도 현재 확정하지 않음 |
| S5-T18 | 손절 비활성 | stop_loss_enabled=false 명시 | 손절 trigger 없음, 나머지 위험 한도 유지 |
| S5-T19 | 손절 설정 누락/null | key absent or null | fail-closed, 신규 주문 없음 |
| S5-T20 | 손절 활성 | enabled=true, valid stop_loss_pt | 설정된 손절 trigger와 close lifecycle |
| S5-T21 | 헤지 부분체결 | 1계약 요청, partial fill/remaining qty | 실제 filled qty만 노출, retry 전 reconciliation |
| S5-T22 | 원 옵션만 체결 | hedge group 중 한 leg만 filled | PARTIALLY_EXPOSED, 추가 신규 진입 차단 |
| S5-T23 | 헤지 주문 거절/미체결 | reject, timeout, no fill | 포지션 flat 확인 전 reset 금지 |
| S5-T24 | 취소 경합 중 체결 | cancel requested then fill arrives | fill 반영, remaining qty reconcile |
| S5-T25 | 호가 공백/오래된 호가 | quote missing/stale/wide | fail-closed, 주문 없음 |
| S5-T26 | 계약/승수/만기 불일치 | identity/multiplier/expiry missing or conflicting | BLOCKED/UNAVAILABLE |
| S5-T27 | config PROVISIONAL/null | status PROVISIONAL or required null | 신규 주문 없음 |
| S5-T28 | S1/S9와 premium·margin 합산 | shared contract/exposure; open lots | duplicate-free account risk; cap breach blocks |
| S5-T29 | 재시작 | open order/partial fill/position exists | reconciliation before any new signal/order |
| S5-T30 | 실제 옵션 P&L/비용 | fills, premium, multiplier, fees/slippage | underlying proxy를 option P&L로 사용하지 않음 |
| S5-T31 | REAL_VTS 검증 분리 | tuning/holdout windows | time separation, provenance, no tuning leakage |
| S5-T32 | 데이터 누락/시각 불일치 | official open, prev close, quote as-of invalid | BLOCKED/UNAVAILABLE, no order |
| S5-T33 | 당일 중단 후 재시도 | whipsaw_limit reached | same-day entry blocked; next session requires clean reconciliation/config |


## S5-U namespace decision amendment (2026-10-12)
- User decision: preserve S1 U-ID values; namespace S5-specific new items as S5-U16 through S5-U20. This appendix controls references in this S5 delta document.
- Documentation-only resolution; no code, test, Git, or Live order action is authorized.
