"""Track 1~9의 기존 Strategy signal dictionary에서 CanonicalStrategySignal이 담당하는 표준 필드와 전략 고유 provenance를 분리하여 함께 운반하는 최소 Intermediate Wrapper 계약을 정의한다.
- CanonicalStrategySignal은 변경하지 않는다.
- ExecutionProvenance는 관찰·보존 데이터이며 실행 의미를 결정하지 않는다.
- declared_order_purpose와 declared_order_type은 원본 signal에 실제 명시된 경우에만 보존한다.
- 누락된 값은 None으로 유지한다.
- action, track_id, tag_id, side, Position 방향으로 order_purpose를 추론하지 않는다.
- pricing_mode, limit_offset_ticks, fallback_market_timeout_sec, strike/leg 구조 등 전략별 데이터는 metadata에 보존할 수 있다.
# - Risk 승인 수량은 이 wrapper에서 변경하지 않는다."""

## 목적


## 설계 원칙








## 코드
