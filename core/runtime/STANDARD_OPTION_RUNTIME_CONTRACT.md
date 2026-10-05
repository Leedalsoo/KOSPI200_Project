# Standard Option Runtime Contract

## 목적
`core/runtime/standard_option_runtime.py`의 현재 Runtime tick 경계를 설명한다.

## 현재 구현
`StandardOptionRuntime.process_tick()`은 하나의 authoritative tick을 Strategy evaluation seam으로 전달하기 전에 다음을 검증한다.
- `source_sequence`가 존재하고 양수여야 한다.
- tick의 timestamp가 제공된 경우 `observed_at.isoformat()`과 일치해야 한다.
- Runtime은 sequence, timestamp, option identity, price 또는 execution field를 임의 생성하지 않는다.

검증을 통과한 tick만 `RuntimeTickStrategySeam.evaluate_tick()`으로 전달한다.

## 책임 경계
Runtime은 tick 수용 및 Strategy evaluation seam 연결을 담당한다. Strategy의 고유 판단, Risk 승인, OMS/Broker 실행 의미를 Runtime이 추론하거나 합성하지 않는다.

## 현재 검증 원칙
pytest의 Runtime contract PASS는 실제 REAL_VTS Strategy lifecycle PASS와 동일하지 않다. 실제 lifecycle 검증은 `verification/current_strategy_replay.py`와 현재 REAL_VTS 데이터로 별도 판정한다.

과거 Reference Runtime의 구조나 Notion 작업번호는 현재 계약의 근거가 아니다.
