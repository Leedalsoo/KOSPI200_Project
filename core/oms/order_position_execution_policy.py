"""No.006의 표준 흐름 Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent를 기준으로, 현재 Exp_Detail_1의 기존 주문 동작을 유지하면서 order_purpose의 권위 있는 공급 경계를 분리한다.
- Position Logic은 Strategy action을 단순 문자열 변환하는 계층이 아니라 실제 포지션 상태와 명시된 실행 의도를 근거로 Order Intent에 필요한 실행 의미를 공급하는 책임 경계다.
- 현재 Exp_Detail_1에는 이 책임을 수행하는 authoritative Position Logic의 order_purpose 공급 필드/구현이 확인되지 않았다.
- 따라서 지금 단계에서 실제 purpose 값을 만들거나 action→purpose 매핑을 추가하지 않는다.
# - order_type과 order_purpose는 분리한다."""

## 목적


## 핵심 원칙








