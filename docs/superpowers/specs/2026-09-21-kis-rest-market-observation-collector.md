# KIS REST 실제 시장데이터 수집기 사양

## 1. 목적
VTS에서 실제 KIS REST 선물·옵션 시장데이터를 수집하여 Raw 응답과 Canonical Market Observation을 함께 보관하고, 이후 Historical Store / MarketDataHub / Replay 경로에서 1배속 및 가속 Replay에 사용할 수 있는 실행 가능한 수집기를 구현한다.

## 2. 적용 범위
- VTS REST 인증 및 선물·옵션 Quote / OrderBook 조회
- authoritative Option Master에서 수집 대상 계약 결정
- KIS VTS 1 req/sec 제한을 넘지 않는 요청 스케줄링
- Raw KIS 응답과 Canonical Observation의 원자적 연계 보관
- 수집 실패·identity 불일치·응답 오류의 fail-closed 처리
- 기존 Historical Store 및 Replay와의 연결
- 1배속 Replay와 가속 Replay에서 provenance 보존

실제 KIS 주문은 범위에서 제외한다.

## 3. 수집 대상 계약
수집기는 임의의 행사가나 옵션 코드를 생성하지 않는다. authoritative Option Master가 제공한 계약만 수집한다.

각 대상은 최소한 broker symbol과 canonical contract identity를 가져야 하며, identity가 없거나 불완전하면 수집하지 않고 명시적인 BLOCKED/UNAVAILABLE 결과를 남긴다.

초기 구현은 전략 전체의 모든 계약을 무차별 polling하지 않고, Option Master가 명시한 검증 대상 계약 집합을 입력으로 받는다.

## 4. 요청 예산 및 스케줄
VTS REST의 계좌별 1 req/sec 제한을 안전하게 준수한다.

한 Observation에 필요한 Price와 OrderBook 조회는 각각 API 요청이므로 두 요청 사이에도 rate limiter가 적용된다. 인증 토큰 발급/갱신 요청 역시 동일한 외부 API 예산을 침범하지 않도록 별도 인증 경계에서 관리한다.

수집 주기는 명시적인 scheduler/rate limiter가 보장한다. 요청 실패 시 즉시 재시도하지 않으며 backoff를 적용한다.

수집기에는 run_id, collection cycle id, target symbol, request sequence, requested_at / collected_at, HTTP status / KIS rt_cd, 성공·실패 사유, 저장된 observation_id를 기록한다.

## 5. Raw + Canonical 보관
각 성공한 수집 cycle은 KIS REST Price/OrderBook 원문을 Raw Archive에 보존하고, Raw reference와 content hash를 Canonical Observation에 연결한다.

Price와 OrderBook의 source timestamp가 모두 존재하면 동일성을 검증한다. 서로 다른 source timestamp는 하나의 Observation으로 합치지 않고 fail-closed한다.

Raw 원문은 변경 없이 보존하며 canonical 데이터와 동일한 run_id 및 contract identity provenance를 유지한다.

## 6. 시간 의미
- `observed_at`: KIS가 권위 있게 제공하는 시장 관측 시각이 있을 때만 사용한다.
- `collected_at`: 로컬 수집기가 응답을 확보한 시각이다.
- REST snapshot은 WebSocket tick으로 재해석하지 않는다.
- Replay에서는 authoritative `observed_at`을 우선하고, 없으면 명시적으로 `collected_at`을 시간축으로 사용한다.

## 7. Canonical 변환
기존 `KISRestMarketObservationNormalizer`를 재사용한다.

Normalizer는 Contract Identity, last/bid/ask/volume, 5단계 bid/ask와 수량, total bid/ask quantity, IV/Delta/Gamma/Theta/Vega 등 실제 응답값, source/provider/schema/run_id, source timestamp/provenance, RawMarketDataReference를 보존한다.

KIS 응답에 없는 값은 0, False, 고정값 또는 synthetic 값으로 채우지 않는다.

## 8. 저장 및 중복 방지
Observation ID와 Raw hash를 사용하여 동일 응답의 중복 저장을 식별할 수 있어야 한다. 동일 cycle에서 동일 계약의 Price/OrderBook pair는 하나의 canonical Observation으로 묶는다.

저장 중 일부 단계가 실패하면 완전한 Observation으로 승격하지 않는다. Raw가 먼저 저장되더라도 canonical 저장 실패 상태가 명확히 남아야 하며 이후 재처리 가능한 provenance를 유지한다.

## 9. Replay 연결
수집 완료 후 Historical Market Store에서 Observation을 읽어 기존 Replay 경계로 연결한다.

```text
VTS REST Collector
      ↓
Raw + Canonical Archive
      ↓
HistoricalMarketStore
      ↓
1x Replay / Accelerated Replay
      ↓
MarketDataHub
      ↓
Standard Runtime
      ↓
Option Master → Quote → OrderBook → Virtual Execution
```

1배속 Replay는 원본 시간 간격을 유지한다. 가속 Replay는 시간 간격만 압축하고 계약 identity와 시장값의 의미는 변경하지 않는다.

## 10. Scenario provenance
원본 수집 데이터는 `ORIGINAL` provenance로 보존한다. 가격·호가·변동성·시간축을 변형한 데이터는 별도의 `SCENARIO`/`SYNTHETIC` provenance와 독립 Run ID를 사용한다.

변형 데이터가 원본 archive를 덮어쓰지 않는다.

## 11. 실패 정책
인증 실패, HTTP 오류, `rt_cd != 0`, authoritative Option Master identity 미확인, Price/OrderBook contract identity 불일치, source timestamp 불일치, 필수 시장값 누락, rate-limit 초과 응답은 정상 Observation으로 승격하지 않는다.

실패 원인과 대상 계약을 기록하고 정상 Runtime 입력으로 만들지 않는다.

## 12. 검증 기준
구현 완료 판정은 Collector 단위 테스트 → rate-limit 테스트 → Option Master target selection 테스트 → Raw/Canonical linkage/hash 테스트 → 실제 VTS REST 1 cycle 수집 → Historical Store round-trip → 1배속 Replay → accelerated Replay → 전체 pytest → compileall → diff-check → Project200 gate → 원격 HEAD 확인 순으로 검증한다.

Live credentials가 없는 동안 Live runtime evidence는 계속 BLOCKED이며 VTS 결과로 대체하지 않는다.
