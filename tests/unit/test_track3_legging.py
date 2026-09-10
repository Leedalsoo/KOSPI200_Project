"""Test Track3 Legging — 테스트 사양 문서.

테스트 기준
- 정상적인 2-leg Plan은 first leg OrderIntent를 생성한다.
- first leg의 ExecutionReport 이후에만 second leg OrderIntent가 생성된다.
- 다른 group/leg ID의 fill은 second leg를 생성하지 않는다.
- group_id와 leg_id가 모든 intent purpose에 보존된다.
- quantity <= 0 또는 group identity 불일치 PositionGroup은 Registry 등록을 거부한다.
- duplicate group_id 등록은 거부한다.
- Coordinator는 Broker/VMS/VSSF/UI/TimeService를 import하지 않는다.
- 지정가/시장가와 timeout/fallback은 Strategy/Coordinator가 임의 실행하지 않고 Environment Execution 계층에 남겨야 한다.
실제 terminal pytest는 현재 실행 환경에서 수행하지 않았으므로 실행 PASS로 판정하지 않는다.
- OrderIntent.group_id/leg_id는 Environment BrokerOrderCommand까지 lossless하게 전달되어야 한다.
- 단일 주문은 group/leg 값이 None인 기존 의미를 그대로 유지해야 한다.
- 이번 계약 변경의 독립 임시 pytest 검증: 2 passed (group/leg lossless transport, single-leg backward compatibility).
"""
