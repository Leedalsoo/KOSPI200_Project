# Strategy 1~9 신규 명세 — 작업 인덱스 v0.2

- 상태: 초안 / 미검증 / 미승인
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 이 인덱스는 기존 비교형 표를 주 설계표로 취급하지 않는다. 판단요소별 통합설계의 기준 문서는 02_decision_factor_integrated_design_matrix_v0.3.md 이다.

## 문서 역할

1. 02_decision_factor_integrated_design_matrix_v0.3.md — 주 설계표. 동일한 판단요소를 행으로, Strategy 1~9를 열로 구성해 전략 목적부터 신호·계약·수량·주문·체결·헤지·청산·만기·손익·계좌위험·오류복구·검증까지 통합한다.
2. strategy_1_tail_defense_spec_v0.2.md — Strategy 1 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인. 
   - strategy_1_tail_defense_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
3. strategy_2_asymmetric_trap_spec_v0.2.md — Strategy 2 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_2_asymmetric_trap_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
4. strategy_3_statistical_arbitrage_spec_v0.2.md — Strategy 3 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_3_statistical_arbitrage_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
5. strategy_4_gamma_scalping_spec_v0.2.md — Strategy 4 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_4_gamma_scalping_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
6. strategy_5_gap_divergence_spec_v0.2.md — Strategy 5 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_5_gap_divergence_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
7. strategy_6_daily_tail_insurance_spec_v0.2.md — Strategy 6 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_6_daily_tail_insurance_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
8. strategy_7_weekly_volatility_skew_insurance_spec_v0.2.md — Strategy 7 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_7_weekly_volatility_skew_insurance_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
9. strategy_8_macro_regime_monthly_strangle_spec_v0.2.md — Strategy 8 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_8_macro_regime_monthly_strangle_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
10. strategy_9_event_overnight_insurance_spec_v0.2.md — Strategy 9 판단요소별 상세 명세(주 초안, F01~F29/상태 전이/수용 게이트 포함). 미승인.
   - strategy_9_event_overnight_insurance_spec_v0.1.md — 이전 초안 및 조사 이력(역사적 참고 전용).
11. 01_strategy_1_to_9_consistency_review_v0.1.md — 기존 정적 코드 사실 및 미결정/검증 이슈 기록(역사적 참고). 주 설계표가 아니다.
12. 03_requirements_spec_code_test_traceability_v0.1.md — 261 strategy factor rows + C01~C14 + G01~G12 추적 skeleton. Test ID/evidence mapping pending.
13. 04_strategy_1_to_9_scenario_test_plan_v0.1.md — strategy normal/boundary/exception/recovery 36 groups + cross-strategy 16 scenarios. Not run.

## 작업 원칙

- 기존 Strategy 1~9 비교표는 현재 동작을 요약한 역사적 분석 자료일 뿐, 신규 전략 설계 기준이 아니다.
- 전략별 문서는 현재 코드의 사실과 설계 미결 항목을 분리한다.
- 공통 lifecycle/state machine, authoritative source, per-leg fills, group risk, actual P&L/cost, expiry, restart/reconciliation을 모든 전략에 적용한다.
- 빈칸 대신 미정/BLOCKED를 기록한다. 승인되지 않은 수치·구조를 가정으로 확정하지 않는다.
- 검증 완료와 사용자 승인은 별개다. 승인 전 전략 코드 변경, commit/push는 하지 않는다.
- Strategy 5의 과거 No.1168 옵션 BUY 2안은 폐기됨 상태이므로 현재 승인 설계로 사용하지 않는다.
- KIS Live 주문은 별도 명시적 승인 없이는 금지한다.

## 현재 상태

- 전략별 상세 문서 9개: 초안. Strategy 1~9는 v0.2 판단요소별 상세본 작성. 모두 초안/미검증/미승인 상태.
- 판단요소별 통합설계표 v0.3: 초안 작성 완료, 상호작용/충돌 검증 초안 추가, 완전성 검증 미완료.
- 명세 완전성 게이트: 아직 Strategy 1~9 각각 PASS 판정을 받지 않음. Strategy 1~9 v0.2는 F01~F29를 매핑했으나 source/정책/시나리오 검증은 미완료.
- 전략 코드 변경: 없음.
- 테스트 실행: 이 문서 재구성 단계에서는 실행하지 않음.
- Commit/push: 하지 않음.
- 다음 단계: v0.3 통합표의 추적표 skeleton과 scenario test plan은 작성됨. 다음은 exact Test ID/log/evidence mapping, 미결정 정책 보고, 승인 후 Virtual scenario execution이다.
- 이전 통합표 v0.2는 역사적 초안으로 보존한다. v0.3은 Strategy 1~9 상세 명세 v0.2와 대조한 상호작용/충돌 검증 초안이다.