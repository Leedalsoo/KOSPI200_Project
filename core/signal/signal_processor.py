"""Standard Core Signal 계층 — 검증/중복제거 Responsibility.

Legacy option_program/strategy/signal_generator.py의 환경 독립 기능을
Standard Core Signal 계층으로 이식한다.

이식 범위:
- signal 필수 필드 검증
- qty > 0 검증
- price > 0 검증
- track_id / tag_id 필수 검증
- OPTION일 때 strike / option_type 검증
- fingerprint 기반 debounce 중복 제거
- clear_history

경계: Signal 계층은 KIS/VMS/VSSF/Broker/UI를 호출하지 않는다.
주의: CanonicalStrategySignal → CanonicalOrderCommand 직접 변환은 Core Signal 책임과
OMS/Position 책임을 섞으므로 그대로 복사하지 않는다.

독립 테스트 기준:
- qty <= 0 신호 거부
- price <= 0 신호 거부
- track_id 누락 거부
- tag_id 누락 거부
- OPTION의 strike <= 0 거부
- OPTION의 option_type 누락 거부
- 동일 fingerprint의 debounce window 내 중복 억제
- debounce 이후 동일 신호 재허용
- clear_history() 후 재허용
- 주문 실행/브로커 호출이 발생하지 않는지 경계 검증

기능 이식 기준은 수립했다. 실제 terminal pytest를 실행하지 못했으므로 실행 PASS는 아니다.
"""
