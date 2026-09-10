1. Factory는 네 가지 EnvironmentType 각각에 대해 Bundle을 반환한다.

1. Bundle은 필수 Contract를 모두 제공한다.

1. 한 Runtime Controller에 active Environment가 둘 이상 존재할 수 없다.

1. 이미 실행 중인 Runtime에 두 번째 Environment를 start하면 거부한다.

1. stop/shutdown 후에만 다음 Environment를 활성화할 수 있다.

1. Controller가 KIS/VMS/VSSF 구체 구현체를 직접 import하지 않는다.

1. High-Speed는 Virtual과 동일 Core Contract를 사용하고 Clock/Replay Policy만 가속한다.

1. Live Bundle은 allow_live_orders 같은 명시적 안전 정책 없이 실주문을 허용하지 않는다.

현재 상태: TEST SPEC READY / 실제 실행 BLOCKED.