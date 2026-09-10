Baseline HEAD: 51c57c1f88035523db9491fa56bbc52bcad9b20f

주요 Reference 자산:

- option_program: Option Runtime/Strategy/Sensor/Decision/Risk/OMS

- virtual_market_simulator: Virtual Market

- virtual_securities_firm: Virtual Broker/Account/Position/Margin/Ledger/Recovery

- infra/shared: 시간·telemetry·persistence·공통 모델 후보

- web_interface: 기존 UI

- config/tests/docs/.github: 설정·검증·증거

새 구조에서는 파일 전체 복사가 아니라 KEEP / REFACTOR / REBUILD / MERGE / DELETE 판정 후 필요한 기능만 이식한다.

구조 위험:

- Runtime/entrypoint 책임 집중

- Real/Paper/Virtual 경로 혼재

- Legacy/backup 후보

- UI/환경 구현체 중복 가능성.