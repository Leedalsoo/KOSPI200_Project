"""Signal Processor — Canonical Strategy Signal 검증 계층.

역할:
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

경계:
    Signal 계층은 KIS/VMS/VSSF/Broker/UI를 호출하지 않는다.
    주문 실행도 담당하지 않는다. 검증 통과 결과는 표준 Signal/후속 Order Intent
    계층에서 소비한다.

주의:
    Legacy의 CanonicalStrategySignal → CanonicalOrderCommand 직접 변환은
    Core Signal 책임과 OMS/Position 책임을 섞으므로 그대로 복사하지 않는다.
    주문 명령 생성은 Standard Core Pipeline의 후속 단계로 분리한다.

검증 상태:
    Notion 작업대에 기능 이식 설계를 기록했으며 실제 terminal pytest는 현재
    실행할 수 없어 PASS로 판정하지 않는다.

No.085 Identity 전달 규칙:
    - Signal Processor는 Signal.instrument_identity를 fingerprint/검증 과정에서
      제거하거나 재생성하지 않는다.
    - 옵션 선택 변경은 option_type_override / strike_override처럼 명시적 주문
      의도로만 표현한다.
    - Signal 계층은 authoritative symbol/expiry를 legacy 기본값으로 채우지 않는다.
    - 최종 immutable OptionInstrumentIdentity 확정은 OMS/OrderIntent 직전
      Resolver가 담당한다.
"""
