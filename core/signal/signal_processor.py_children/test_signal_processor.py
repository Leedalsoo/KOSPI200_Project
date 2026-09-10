"""Signal Processor 독립 테스트 기준.

Legacy SignalGenerator의 검증/중복제거 책임을 Standard Core Signal 계층에서 검증한다.

테스트 항목:
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
