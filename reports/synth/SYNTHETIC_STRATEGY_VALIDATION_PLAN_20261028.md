# 합성 데이터 기반 Strategy 1~9 임시 검증·보완 계획

- 작성일: 2026-10-28
- 상태: 계획 v1.0 / 다음 구현·테스트 단계 승인 대기
- 범위: DERIVED_SCENARIO/SYNTHETIC 데이터만 사용하여 전략 코드의 구조·입력·상태전이·주문수명주기 결함을 찾고 보완한다.
- 금지: KIS Live/실제 주문, KIS 계좌 API, REAL_VTS 원본 접근, collector/scheduler 변경, 임의 계약 identity를 production ID로 승격, 수익성 주장의 근거로 합성 P&L 사용.

## 1. 임시 기준 원칙

합성 검증 결과는 `SYNTHETIC_PASS`, `SYNTHETIC_FAIL`, `BLOCKED_REAL_DATA`, `BLOCKED_SPEC`로 분류한다. `SYNTHETIC_PASS`는 명시된 합성 fixture와 가정 아래의 로직·계약 통과만 뜻하며 운영 적합성이나 수익성을 뜻하지 않는다. 실제 API가 확보되면 동일한 요구사항·경계·상태전이 규칙을 REAL_VTS evidence로 재검증한다.

각 임시 값에는 `candidate_id`, 값/단위, 적용 범위, 근거, fixture 해시/seed, 경계값, 예상 결과, 위험, 운영 검증 전환 조건을 기록한다. 전략 파라미터는 수익률을 높이기 위해 합성 데이터에 맞춰 튜닝하지 않는다. 우선 안전·논리·상태 일관성·입력 누락 처리를 검증한다.

## 2. 검증 단계

### P0 — 안전·기준 동기화
- 시작 시 AGENTS.md, Current Baseline, 최신 확정 Decision Log, 공식 과제 큐를 확인한다.
- 작업트리 dirty/untracked를 보존한다. 기존 파일을 덮어쓰거나 정리하지 않는다.
- 합성 데이터셋의 manifest, `synthetic=true`, `generator_version`, `seed`, `validation_only=true`, `production_runtime_eligible=false`를 확인한다.

### P1 — 전략별 입력·경로 준비도 감사 (다음 단계)
- Strategy 1~9 각각에 대해 전략 구현, Runtime Input/Analytics, contract/identity source, resolver, 테스트 파일, 시나리오 계획, 정확한 Test ID, 실행 evidence를 추적한다.
- 결과 열: 전략 ID, authoritative inputs, synthetic inputs, missing fields, known blockers, test IDs, expected lifecycle, status, 수정 후보 파일.
- 코드나 데이터는 수정하지 않는 읽기 전용 감사부터 수행한다.

### P2 — 합성 시나리오·임시 임계값 설정
- 공통 시나리오: 정상/상승추세/하락추세/횡보/고변동/저변동/급락·반등/갭/휘프소/호가 공백/거래량 부족/지연·미래시각/중복·역순 이벤트/identity 충돌/만기·세션 경계/재시작/부분체결/취소 경쟁.
- 임계값은 후보 집합으로 민감도 비교하고, 경계 직전·동일·직후 케이스를 포함한다.
- Freshness 예비 후보 300/600/900/1800초는 기존 5분 합성 관측 가정에 대한 민감도 후보일 뿐이다. 600초를 확정 운영값으로 취급하지 않는다. 미래시각 허용치 0초는 fixture 조건일 뿐이며 실시간 시계 허용오차로 승격하지 않는다.
- 경제적 전략 파라미터는 사용자의 승인된 명세가 없으면 임의로 결정하지 않는다. 후보별 결과를 보고하고 명세가 필요한 결정은 `BLOCKED_SPEC`로 분리한다.

### P3 — 공통 계약·런타임 가드 검증
- 누락·stale·identity mismatch·invalid quote·volume/depth insufficiency·unknown expiry/multiplier는 안전하게 BLOCKED/UNAVAILABLE이어야 한다.
- `synthetic=true` provenance가 source→runtime→decision→order→execution→position/PnL까지 보존되는지 확인한다.
- 한 번에 한 주문, 가격 도달+거래량 조건의 limit fill, 취소 완료 전 대체 주문 금지, 부분체결 잔량 추적, 레그별 상태 및 execution/position provenance를 보존한다.
- High-speed와 상세 로그 모드의 동등성은 상세 로그 모드 계약이 실제로 존재하고 정의된 뒤에만 검증한다.

### P4 — Strategy 1~9 개별 시나리오
- 각 전략별 정상 진입, 진입 거절, 경계 임계값, 청산/stop/trailing, 시간·만기 경계, 부분체결, cancel race, stale/missing input, restart/reconcile, config version, account risk를 테스트한다.
- 신호가 발생하지 않은 경우 `NO_SIGNAL_OBSERVED`를 명시하고 signal-driven lifecycle PASS를 주장하지 않는다.
- 양성 lifecycle은 합성 fixture가 명시된 테스트 전용 근거로 확인한다. fixture resolver나 테스트용 FRESH를 production 경로의 증거로 혼용하지 않는다.

### P5 — 다중 전략·계좌 위험·통합 Replay
- 전략별 run/state를 격리하고 Strategy 1~9 개별 결과와 통합 결과를 별도 보고한다.
- 겹치는 헤지, 계약/만기 충돌, premium/margin/quantity caps, 미체결 레그, 중복 execution, 포지션 복구, P&L provenance를 검증한다.
- 기존 P5 합성 데이터셋은 구현 결함 발견용으로 사용한다. 무신호 재생은 이벤트 처리·결정성만 증명하며 주문 lifecycle을 증명하지 않는다.

### P6 — 결함 수정 루프
- 각 결함에 `Finding ID → 재현 fixture/seed → 요구사항 → 최소 수정 파일 → 회귀 테스트 → 결과 → 잔여 위험`을 기록한다.
- 한 번에 하나의 논리적 결함군을 수정하고 focused test, 관련 회귀, 전체 suite, diff/status를 확인한다.
- 전략/아키텍처/데이터 기준 변경은 구현 전 명세 충돌과 필요한 승인 범위를 명시한다. commit/push는 별도 승인 전 금지.

### P7 — 실계좌 API 확보 후 비교 검증
- 현재 임시 기준과 동일한 테스트 케이스를 REAL_VTS/KIS VTS 실제 frame·source timestamp·received timestamp·master/capability evidence로 재실행한다.
- 임시값별로 `유지/조정/폐기`를 근거와 함께 판정한다. KIS Live 자격/실제 frame과 별도 승인이 없으면 Live E2E라고 부르지 않는다.

## 3. 공통 합격 기준

1. 테스트 fixture의 provenance와 seed가 재현 가능하다.
2. 필수 authoritative input이 없으면 주문을 만들지 않고 명시적인 BLOCKED/UNAVAILABLE 이유를 남긴다.
3. 경계값과 실패 주입 결과가 기대값과 일치한다.
4. 신호→Decision→Risk→OMS/Router→Virtual Broker/Execution→Position/PnL의 각 단계별 evidence가 존재한다. 관찰되지 않은 단계는 PASS로 승격하지 않는다.
5. 고속·상세 로그 결과 비교는 동일한 입력/seed/run context 및 명시된 모드 계약이 있을 때만 수행한다.
6. synthetic P&L은 엔진 회계 일관성 검사에만 사용하며 수익성 근거로 사용하지 않는다.
7. 수정 후 회귀 테스트가 통과하고 기존 사용자 변경이 보존된다.

## 4. 현재 확인된 준비도·제약

- `docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.4.md`는 261개 전략 요소의 skeleton을 포함하지만, 파일 헤더에 정확한 Test ID/evidence 매핑 미완료 및 검증 미통과라고 명시되어 있다.
- `docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.4.md`에는 다수 NOT_RUN/BLOCKED 시나리오가 존재한다. 계획에 기록된 것은 실행 evidence가 아니다.
- `tests/application/test_quote_only_strategy_evaluation.py`는 quote-only evaluation이 거래량/last price를 추정하지 않고 routing하지 않는 경계를 다룬다.
- `tests/application/test_track3_spread_leg_definition_block.py`는 Track3 spread leg 정의 미해결 시 계획 생성을 차단한다. 최신 확정 Decision Log No.1176과 일치하게 S3/S4 mini-Futures identity/fields가 확보되기 전에는 production resolver를 만들지 않는다.
- R4 freshness 임계값 실험은 `reports/synth/R4_SYNTHETIC_FRESHNESS_THRESHOLD_SWEEP_20261028.json`에 있다. 현재는 계약 경계 fixture 실험일 뿐 production freshness producer가 연결되었다는 증거가 아니다.
- 현재 working tree에 다수의 수정·미추적 파일이 존재하므로 모든 작업은 파일별 범위를 확정하고 unrelated 변경을 보존해야 한다.

## 5. 다음 실행 항목과 승인 경계

**다음 실행 항목: P1 읽기 전용 Strategy 1~9 입력·경로 준비도 감사.** 결과를 `reports/synth/STRATEGY_1_9_SYNTHETIC_READINESS_20261028.md`에 기록하고 Notion `질문과답변`에 연결한다. 이 감사에서는 테스트 실행, 전략 코드 수정, 데이터 변경, collector/scheduler 변경, Git stage/commit/push를 하지 않는다.

감사 결과를 기준으로 가장 안전하고 근거가 명확한 공통 계약/입력 결함부터 순서를 제안한다. 전략 코드·테스트 실행으로 넘어갈 때는 공식 과제 큐의 해당 Q 항목과 명시적 승인 문구를 먼저 확정한다.
