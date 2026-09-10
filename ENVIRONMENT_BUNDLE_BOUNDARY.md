## 공통 Bundle Shape

EnvironmentBundle

├─ market_data

├─ clock

├─ broker

├─ account

├─ execution

└─ runtime_policy

## High-Speed Test

- deterministic/replay 가능한 입력

- accelerated clock

- fast execution policy

- Virtual Domain Contract 사용

## Virtual Trading

- virtual market

- virtual broker/account/execution

- real-time 또는 simulated time policy

## Paper Trading

- 실제 증권사 모의 API

- 실제 시간

- 실제 API 응답 Contract 변환

## Live Trading

- 실제 증권사 실전 API

- credential isolation

- kill switch

- order safety guard

- reconciliation

- restart/recovery safety

원칙: 단순 endpoint/API 주소 교체가 아니라 Bundle 전체 교체다.