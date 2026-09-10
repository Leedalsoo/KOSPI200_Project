# Control Tower 통합 검증 Spec

## No.074 Core/Strategy 동일성

- 4개 Environment 선택에 따라 core/와 core/strategy/ 코드가 달라지지 않는다.

- 동일 Strategy Registry/호출 계약을 사용한다.

- Environment 차이는 Adapter/Execution 영역에서만 발생한다. fileciteturn111file0L1-L10

## No.075 High-Speed ↔ Virtual

- 동일 Scenario를 Virtual 1x와 High-Speed 가속 정책에서 비교한다.

- 시간 경계 및 floating-point 차이를 별도 기록한다. fileciteturn111file3L32-L39

## No.076 Contract compatibility

- Virtual/Paper/Live가 동일 MarketDataProvider Contract를 만족한다.

- Core 변경 없이 Adapter 교체가 가능한지 확인한다. fileciteturn112file0L1-L10

## No.077 Environment isolation

- 다른 Environment의 Broker/VMS/VSSF 객체가 생성·공유되지 않는지 정적 import 및 객체 생성 경계를 검사한다.

- 특히 Live에서 VSSF 객체 생성이 없어야 한다. fileciteturn111file1L11-L19

## No.078 Lifecycle/Recovery

- 4개 Environment 각각 Start/Stop/Restart 경계를 확인한다.

- 실행 중 환경 전환은 거부하거나 안전하게 중지 후 전환한다.

- 정상 Stop/강제 종료/Restart 후 상태 복구를 별도 검증한다. fileciteturn111file4L41-L50

## 현재 검증 한계

실제 브로커·브라우저·외부 API 실행은 현재 환경에서 수행할 수 없으므로 정적 구조/계약/테스트 설계까지만 PASS로 기록하고 실제 실행 증거는 BLOCKED로 분리한다.

## No.528 Technical lifecycle status

- RuntimeStatus.technical_state는 Control Tower의 기술적 lifecycle 상태 전용 필드다.

- shutdown cancellation drain timeout은 technical_state="STOP_TIMEOUT"으로 표현한다.

- STOP_TIMEOUT을 주문 상태, 체결 상태, 포지션 상태, Risk Domain 상태와 합치지 않는다.

- timeout 상태에서는 shared execution ownership을 release/reuse하지 않는 fail-closed 계약을 유지한다.

- 검증: RuntimePolicy custom timeout → cancellation capability/fallback → unresolved drain → LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT + STOP_TIMEOUT 분리.