## No.106 추가 계약 테스트 기준

CanonicalStrategySignal의 additive identity 확장에 대해 다음을 검증한다.

1. 기존 Signal 생성 호출은 symbol/expiry 없이도 기존 default로 생성된다.

1. symbol/expiry를 명시한 Signal은 해당 값을 보존한다.

1. Signal → CanonicalOrderCommand 변환은 symbol/expiry를 그대로 전달한다.

1. Runtime Tick의 expiry가 Signal 및 Command까지 유지되는 경로를 검증한다.

1. 기존 validate_signal() reject 규칙(qty/price/track/tag/option strike/type)은 변경하지 않는다.

1. 기존 Legacy debounce fingerprint는 track_id/asset_type/side/strike/option_type/tag_id 의미론을 유지한다.

### 판정 원칙

이 테스트는 주문 identity 전달 계약의 회귀 방지 목적이며, fingerprint 정책 자체를 재설계하는 테스트가 아니다.

### 실행 상태

TEST SPEC READY / EXECUTION BLOCKED.

실제 terminal pytest 실행 전에는 PASS로 판정하지 않는다.