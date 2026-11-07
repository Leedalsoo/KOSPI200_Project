# G4 Cancel-Race / Recovery Test Specification & Traceability v0.1

작성일: 2026-10-14 KST  
상태: **명세 초안 / 미실행 / 미승인 / 코드 변경 없음**  
범위: G4 승인 게이트에 따른 신규 테스트 설계와 증거 추적. 기존 삭제 테스트는 복원하지 않는다. 이 문서는 실행 또는 구현 승인이 아니다.

## 1. 안전 경계 및 판정 규칙

- 환경은 unit/contract/virtual-replay 우선. VTS API는 명시된 read-only 확인만 별도 증거로 기록한다. Live 주문·정정·취소는 금지.
- CANCEL_REQUESTED는 취소 완료가 아니다. terminal cancel/fill 상태와 실제 포지션 대사가 확인되기 전에는 다음 레그, 대체 주문, reset, 재진입을 금지한다.
- 모든 execution report는 execution ID 기준으로 idempotent하게 적용한다. 중복·역순·late fill은 누락/중복 노출 없이 재대사한다.
- unknown/stale/missing/conflicting data, source identity 불일치, 계좌/포지션 대사 불일치는 fail-closed.
- 모든 테스트는 spec/config hash, scenario ID, run ID, fixture/replay provenance, 로그, order/fill/position/P&L ledger를 남긴다. Synthetic/replay는 REAL_VTS 증거로 승격하지 않는다.

## 2. 요구사항 → 시나리오 → 테스트 → 호출 경로 → 증거 추적표

| Req ID | G4 요구사항 | Scenario IDs | 신규 테스트 ID(제안) | 후보 호출 경로(정적 추적 필요) | 증거 산출물 | 상태 |
|---|---|---|---|---|---|---|
| G4-01 | 취소 지연/거부/unknown 상태에서 대체 주문 금지 | G4-CAN-01..03 | test_cancel_terminal_gate | contracts/canonical_order_transport.py; core/runtime/reference_execution_pipeline.py; environments/virtual/broker/virtual_broker_api.py | verification/evidence/g4/G4-CAN-01..03/ | SPECIFIED / NOT_RUN |
| G4-02 | 취소 중 부분체결·late fill·역순 이벤트를 정확히 반영 | G4-FILL-01..04 | test_late_fill_idempotency | environments/virtual/broker/virtual_broker.py; application/composition/virtual_multi_leg_execution.py | verification/evidence/g4/G4-FILL-01..04/ | SPECIFIED / NOT_RUN |
| G4-03 | 다중 레그 일부 체결 후 그룹 위험 재계산 및 안전한 종료 | G4-LEG-01..03 | test_multileg_partial_reconcile | application/composition/virtual_multi_leg_execution.py; environments/virtual/execution/order_intent_adapter.py | verification/evidence/g4/G4-LEG-01..03/ | SPECIFIED / NOT_RUN |
| G4-04 | 재시작/연결 단절 후 주문·체결·포지션·내부 lot 대사 전 재개 금지 | G4-REC-01..04 | test_restart_reconciliation_fence | core/runtime/reference_execution_pipeline.py; contracts/types.py; shared/contracts/canonical.py | verification/evidence/g4/G4-REC-01..04/ | SPECIFIED / NOT_RUN |
| G4-05 | 중복 신호·중복 execution event·재시도에 대한 idempotency | G4-IDEM-01..03 | test_duplicate_event_no_double_apply | contracts/canonical_order_transport.py; broker/event normalization path TBD | verification/evidence/g4/G4-IDEM-01..03/ | SPECIFIED / NOT_RUN |
| G4-06 | 계좌 전체 위험 집계 시 전략별 lot attribution과 계좌 노출 중복/누락 방지 | G4-RISK-01..03 | test_account_risk_aggregate_once | core/risk/option_hedge_risk_config.py; account risk aggregation caller TBD | verification/evidence/g4/G4-RISK-01..03/ | BLOCKED until caller traced |
| G4-07 | S1~S9 충돌·만기·S1/S9 우선순위·S2/S6/S7/S8 재시도 경계 보존 | G4-XSTRAT-01..04 | test_cross_strategy_terminal_priority | application/composition/standard_runtime_input_provider.py; strategy lifecycle/OMS caller TBD | verification/evidence/g4/G4-XSTRAT-01..04/ | BLOCKED for unresolved policies |
| G4-08 | 필수 KIS 데이터 누락/stale/identity conflict 시 fail-closed 및 재개 조건 | G4-DATA-01..04 | test_kis_data_fail_closed_resume | application/composition/virtual_runtime_data_provider.py; infrastructure/kis/kis_rest_market_observation_normalizer.py; contracts/types.py | verification/evidence/g4/G4-DATA-01..04/ | SPECIFIED / NOT_RUN |

**주의:** 호출 경로는 기존 Phase A 정적 조사 및 파일 존재를 바탕으로 한 후보 경로다. 테스트 구현 전 함수/메서드 단위 caller chain을 확인해 정확한 production path를 확정해야 한다. 위 경로만으로 호출 경로 검증 PASS를 의미하지 않는다.

## 3. 시나리오 상세와 기대 결과

| Scenario ID | 조건/이벤트 순서 | 기대 결과 / 차단 조건 | 필수 관측 증거 |
|---|---|---|---|
| G4-CAN-01 | 취소 요청 후 terminal 응답 지연 | 새 레그/대체 주문 금지; RECONCILIATION_REQUIRED | cancel request/state timestamps, order ID |
| G4-CAN-02 | 취소 거부 또는 상태 unknown | 기존 주문 노출을 유지하고 fail-closed | broker state, remaining quantity |
| G4-CAN-03 | cancel terminal 확인 전 다음 후보 선택 시도 | 제출 어댑터에서 차단 | rejected intent, guard reason |
| G4-FILL-01 | 취소 대기 중 부분체결 | 실제 누적 체결 수량 반영, 미체결 잔량 재계산 | execution IDs, cumulative fill/leaves |
| G4-FILL-02 | 취소 요청 이후 terminal cancel 전 late fill | late fill 반영 후 재대사; fallback 금지 | event ordering, fill ledger, position |
| G4-FILL-03 | execution report가 시간 역순 도착 | 정렬/적용 정책에 따라 한 번만 반영; 모순 시 BLOCKED | source/receive times, execution IDs |
| G4-FILL-04 | 동일 execution ID 중복 수신 | 두 번째 적용으로 수량/P&L 중복 증가 금지 | idempotency key and ledger before/after |
| G4-LEG-01 | 4-leg 중 한 레그만 체결되고 나머지 취소 | 실제 포지션 기반 위험 재계산; 가상 페어/flat 금지 | per-leg fills, residual positions |
| G4-LEG-02 | 한 레그 reject, 다른 레그 fill | 사용자 승인된 그룹 정책 없으면 추가 주문 차단 | reject, fills, group state |
| G4-LEG-03 | 청산 그룹 일부체결 후 취소 경합 | 잔여량만 추적; 전체 flat 선언 금지 | close fills and residual lots |
| G4-REC-01 | 주문 pending 상태에서 프로세스 재시작 | 브로커 주문/체결/포지션 대사 완료 전 신규 주문 금지 | pre/post restart snapshots |
| G4-REC-02 | 내부 상태는 flat이나 외부 포지션 존재 | 외부 권위 상태와 불일치로 차단; 내부 reset 금지 | broker position vs internal lots |
| G4-REC-03 | 내부 lot은 open이나 외부 포지션 없음 | 자동 삭제/추정 금지; 조사 상태로 차단 | discrepancy record and provenance |
| G4-REC-04 | 재대사 후 데이터가 여전히 누락/충돌 | resume 금지; block reason 유지 | reconciliation result and resume decision |
| G4-IDEM-01 | 동일 signal ID 재수신 | 중복 주문 생성 금지 | signal ID, order intent IDs |
| G4-IDEM-02 | 프로세스 재시작 후 같은 signal 재생 | persisted idempotency fence 유지 | persisted state/config hash |
| G4-IDEM-03 | 같은 fill이 다른 수신 순서로 재생 | 최종 lot/P&L 동일; 불일치 시 FAIL | deterministic replay outputs |
| G4-RISK-01 | 동일 계약을 두 전략이 소유 | 전략별 attribution은 분리, 계좌 계약 노출은 한 번만 합산 | owner/group IDs, aggregate exposure |
| G4-RISK-02 | pending worst-case와 actual fill 동시 존재 | 이중 계산 또는 누락 없이 위험 상한 계산 | pending leaves + actual lots |
| G4-RISK-03 | 계좌 잔고/증거금/주문가능수량 미확인 | 신규 위험 증가 주문 차단 | source response, block reason |
| G4-XSTRAT-01 | S1 D-4 청산과 S9 DTE7 관리 충돌 | 확정된 우선순위만 적용; 미해결 정책은 BLOCKED | both strategy states and decision trace |
| G4-XSTRAT-02 | S6 zero-fill timeout 후 cancel 미확인 | 같은 날 재시도 금지 | cancel terminal state, daily fence |
| G4-XSTRAT-03 | S7/S8 cutoff 또는 expiry가 calendar 미확정 | 신규 진입/roll 차단 | KIS calendar/expiry provenance |
| G4-XSTRAT-04 | S2/S6/S7/S8 필수 quote missing/stale | 대체 계약 추정 금지; BLOCKED | quote age, identity, guard result |
| G4-DATA-01 | KIS 원본 timestamp 누락 또는 freshness 규칙 미설정 | 신규 주문 차단 | raw payload hash, source/receive timestamp |
| G4-DATA-02 | quote와 master의 contract identity/expiry 불일치 | contract reject, no order | master snapshot hash, quote identity |
| G4-DATA-03 | calendar snapshot 만료/불완전 | calendar-dependent strategy BLOCKED | source, coverage, validity decision |
| G4-DATA-04 | KIS source 복구 후에도 identity/position 재대사 미완료 | 자동 resume 금지 | recovery event, reconciliation proof |

## 4. 실행 순서 및 acceptance criteria

1. 기존 작업트리와 삭제 파일을 보존한다. 테스트 파일 복원·기존 삭제 되돌리기 금지.
2. 위 후보 경로에서 실제 caller chain을 읽기 전용으로 추적하고 표의 TBD를 함수/메서드로 좁힌다.
3. 테스트 ID별 fixture/replay, deterministic clock, event ordering, expected state, evidence path/hash를 확정한다.
4. 승인된 명세에 맞춰 신규 테스트만 작성한다. 테스트 실행 전 테스트 파일 목록과 실행 명령을 기록한다.
5. 각 시나리오 결과는 PASS/FAIL/BLOCKED/NOT_RUN 중 하나만 부여한다. 실행 로그와 증거가 없는 PASS는 금지.
6. Synthetic/replay, KIS VTS read-only, 실제 VTS 주문/체결 증거를 서로 구분한다. Live 주문은 별도 명시 승인 전 금지.

## 5. 현재 작업 범위에서 확인된 상태

- 기존 tests/ 디렉터리는 현재 Git 작업트리에서 삭제 상태다. 복원하지 않는다.
- 기존 문서의 316/316 및 46/46 결과는 과거 실행 증거이며 현재 테스트 상태를 증명하지 않는다.
- 이 파일은 G4 명세/추적표의 신규 초안이다. G4를 위한 신규 테스트 구현/실행 및 G4 관련 코드/Manifest 변경은 수행하지 않았다. 같은 작업에서 별도 사용자 지시에 따른 일일 KIS 거래일 provider/TradingCalendar 연결은 변경했다. Git stage/commit/push 및 주문 API 호출은 수행하지 않았다.
- 연계 기준: Notion No.1265 G4 승인 게이트 및 No.1274 통합 기준표.


## 6. 읽기 전용 정적 추적 체크포인트 — 2026-10-14

확인한 실제 코드 연결:
- Multi-leg entry point: VirtualMultiLegExecutionBridge.execute() in application/composition/virtual_multi_leg_execution.py resolves/validates legs, constructs account/position risk inputs, and uses the bridge-owned StandardOrderRouter.
- Risk boundary: route_after_risk() in core/runtime/reference_execution_pipeline.py calls risk_gate.admit_order(); it invokes order_router.register_and_route() only when approved.
- OMS/router boundary: StandardOrderRouter.register_and_route() in core/oms/order_router.py applies/registers the intent, registers the broker command, submits through the broker adapter, validates the response, then applies the ACK event to OrderStateMachine.
- Virtual broker boundary: VirtualBroker.submit()/cancel()/query() in environments/virtual/broker/virtual_broker.py delegate to VirtualExecutionEngine.execute()/cancel()/query().
- Ambiguous submit recovery: _AckAdapter.submit() in application/composition/virtual_multi_leg_execution.py queries by deterministic client_order_id after a submit exception; if no report is recoverable, it emits UNKNOWN / RECONCILIATION_REQUIRED rather than assuming rejection.
- Order-state guards: OrderStateMachine.apply_intent(), register_broker_order_command(), apply_ack(), resolve_execution_correlation(), and apply_execution() in core/oms/oms_fsm.py validate client/broker correlation and order state before accepting executions.
- Position flatness: VirtualMultiLegExecutionBridge._position_flat_for_plan() checks the execution-created VirtualPositionLotStore for remaining lots; this is virtual position evidence, not proof of KIS VTS account reconciliation.

Not yet proven by this static pass:
- The complete cancel request → terminal broker cancel → late-fill event → authoritative external position reconciliation path.
- Execution-ID idempotency across process restart and durable state restoration.
- Exact production caller for account-wide risk aggregation and S1–S9 cross-strategy priority.
- Current tests do not exist in the worktree; no test execution was performed. These items remain BLOCKED/NOT_RUN and must not be treated as passing.


## 7. 함수·메서드 단위 실제 호출 경로 — 읽기 전용 추적, 2026-10-14

### G4-01/02/03: 주문 제출 및 체결 보고 경로 (Virtual/VSSF 경계)

`VirtualMultiLegExecutionBridge.execute()`
→ 각 레그의 `identity_for_leg()`, `_client_order_id()`, 호가·승수 검증
→ 전체 레그 사전 위험 평가 `RiskGate.admit_order()` 및 그룹 증거금 합산
→ `route_from_runtime_authoritative_sources()` (`application/composition/runtime_authoritative_risk_router_adapter.py`)
→ `RiskGate.admit_order()`
→ `StandardOrderRouter.register_and_route()`
→ `OrderStateMachine.apply_intent()` / `register_broker_order_command()`
→ `_AckAdapter.submit()`
→ `VirtualBroker.submit()`
→ `VirtualExecutionEngine.execute()`
→ `authoritative_execute` 콜백(VSSF 실행 경계)
→ ACK 이벤트는 `StandardOrderRouter`가 `OrderStateMachine.apply_ack()`로 반영
→ 실행 브리지는 `ExecutionReport`를 검사하고 `_applied_execution_fingerprints`로 중복 fingerprint를 확인한 뒤 `VirtualPositionLotStore.apply_execution()`, `VirtualTrack9FeeLedger.record()`, `VirtualPositionFillAdapter.apply()`에 반영한다.

이 경로는 **Virtual/VSSF 실행 증거**다. KIS 실계좌 주문·체결·잔고 대사 경로로 간주할 수 없다.

### G4-01: 취소 경로 — 안전성 BLOCKER 확인

- `StandardOrderRouter`에는 `cancel` 메서드가 없다. 위 다중 레그 실행 경로에서 `OrderStateMachine.apply_cancel()` 호출자도 발견되지 않았다.
- 별도 가상 경로는 `VirtualBroker.cancel()` → `VirtualExecutionEngine.cancel()` → `_authoritative_cancel` 콜백이다.
- `_authoritative_cancel`가 없으면 `VirtualExecutionEngine.cancel()`은 외부 취소 확인 없이 상태 `CANCELLED` 보고서를 만들어 반환한다. 따라서 이 기본 경로는 실제 취소 완료 증거가 아니다.
- 결과: 취소 요청→브로커 terminal cancel 확인→취소 경합 중 late fill 반영→포지션 재대사 흐름은 **BLOCKED**. 신규 G4 테스트는 이 기본 동작을 PASS로 가정하지 말고, 취소 미확인 시 차단을 기대 결과로 고정해야 한다.

### G4-04/05: 체결 중복 및 재시작

- `OrderStateMachine.apply_execution()`은 ACK/PARTIALLY_FILLED 상태, 수량 누적, 잔량 일치, 브로커 주문 ID를 검증한다. 메서드 자체에 execution ID 영속 중복 방지 저장소는 없다.
- `VirtualMultiLegExecutionBridge.execute()`의 `_applied_execution_fingerprints`는 메모리 내 dict다. 동일 프로세스 내 충돌 감지는 있으나 프로세스 재시작 후 복구·영속성은 입증되지 않았다.
- 이 브리지 경로에서 체결 보고가 `OrderStateMachine.apply_execution()`으로 전달되는 호출은 확인되지 않았다. 별도의 실시간 이벤트 수신/정규화 경로와의 연결도 추가 추적이 필요하다.
- 결과: 같은 프로세스의 일부 중복 보호는 확인됐으나 execution-ID idempotency 전체 및 restart recovery는 **NOT_PROVEN / BLOCKED**.

### G4-06: 위험·계좌 집계

- `VirtualMultiLegExecutionBridge.execute()`는 `bundle.account.snapshot()`, `bundle.position`을 사용하고 `account_snapshot_to_risk_input()`, `position_manager_to_risk_input()`으로 Risk 입력을 만든다.
- 각 레그의 위험 평가 후 그룹 필요 증거금을 합산해 그룹 free-margin 및 margin-utilization gate를 적용한다. 이후 라우팅 직전에도 `route_from_runtime_authoritative_sources()`가 위험 평가를 다시 수행한다.
- 확인 범위는 이 브리지에 주입된 account/position snapshot과 한 그룹의 레그 합산이다. 서로 다른 전략 브리지 간 계좌 전체 exposure/lot 중복 집계와 실제 KIS 계좌 잔고·증거금 연결은 입증되지 않았다.
- 결과: 그룹 내 사전 위험 gate는 경로 확인, 계좌 전체 집계 및 KIS 계좌 연결은 **BLOCKED / 추가 caller 추적 필요**.

### G4-07: S1~S9 전략 간 우선순위

- `DecisionArbiter`가 실행 브리지에 import되어 있으나, 현재 확인한 다중 레그 주문 경로에서 S1~S9 전체를 단일 큐로 조정하고 취소·청산 우선순위를 강제하는 호출은 입증되지 않았다.
- `StandardRuntimeInputProvider`는 이번 실행에 선택된 전략의 입력을 생성하는 구조이며, 이것만으로 전략 간 주문 우선순위/상호 배제의 증거가 되지 않는다.
- S1 D-4와 S9 DTE7 충돌, S6 재시도 차단, S7/S8 cutoff 및 공통 계좌 한도는 사용자 확정 정책과 연결된 실제 lifecycle caller를 추가로 특정해야 한다. 그 전까지 관련 케이스는 **BLOCKED**.

### G4-08: KIS 데이터 신선도·정체성

- `KISRestMarketObservationNormalizer.normalize()`는 KIS 응답 성공, 계약 identity lookup, underlying identity, price/order-book timestamp 일치 등을 검증한다.
- `VirtualRuntimeDataProvider.snapshot()`은 주입된 market/analytics source로 Runtime 입력을 조립한다.
- 정적 조사 범위에서 raw payload hash/수신시간/유효기간의 검증 결과가 최종 주문 admission까지 전파되어 stale/missing/conflicting data를 항상 차단하는 전체 caller chain은 아직 입증되지 않았다. `KISRestMarketObservationNormalizer`의 timestamp equality 검증만으로 freshness 보증을 대체하지 않는다.

## 8. 판정표 갱신

| G4 영역 | 현재 판정 | 근거 |
|---|---|---|
| 주문 제출 Risk → OMS → Virtual broker | PATH_CONFIRMED / VIRTUAL_ONLY | 위 함수 연결 확인 |
| 실제 취소 terminal confirmation 및 late-fill reconciliation | BLOCKED | router cancel 경로 미확인, VirtualExecutionEngine 기본 취소가 synthetic CANCELLED 반환 가능 |
| 체결 중복 방지(동일 프로세스) | PARTIAL | 브리지 in-memory fingerprint |
| execution-ID idempotency + 재시작 복구 | BLOCKED / NOT_PROVEN | 영속 저장소/복구 caller 미확인 |
| 한 그룹 내 레그 증거금 합산 | PATH_CONFIRMED / VIRTUAL_ONLY | bridge preflight 합산 |
| 계좌 전체 전략 간 위험 집계 | BLOCKED | 교차 브리지 caller 및 KIS account input 미입증 |
| S1–S9 lifecycle priority | BLOCKED | 통합 주문 큐/우선순위 caller 미입증 |
| KIS data freshness → order admission | BLOCKED / NOT_PROVEN | end-to-end provenance/freshness gate 미입증 |

테스트 구현/실행은 이 추적 이후에도 수행하지 않았다. 위 BLOCKED 항목은 구현 계획에서 먼저 해소해야 하며, 단순히 명세에 테스트 ID가 있다는 이유로 PASS 처리하지 않는다.
