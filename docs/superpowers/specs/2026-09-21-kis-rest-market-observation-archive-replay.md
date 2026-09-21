# KIS REST Market Observation → Archive → Replay 설계 사양

## 1. 목적
현재 MarketDataHub → Historical Store → Replay 계약을 보존하면서 KIS VTS REST 응답을 표준 시장관측 구조로 저장한다.
REST snapshot을 WebSocket tick으로 가장하지 않고, 원본 payload와 정규화 데이터의 provenance를 함께 보존한다.
기존 ReferenceCanonicalMarketTick 기반 Replay 호환성을 깨지 않는 것을 우선한다.

## 2. 범위
포함:
- KIS REST 옵션 시세 응답 정규화
- KIS REST 옵션 호가(OrderBook) 응답 정규화
- 동일 관측의 Quote/OrderBook/Contract Identity 결합
- observed_at / collected_at 분리
- raw payload archive와 canonical observation archive
- 기존 HistoricalMarketStore/Replay 경계와의 연결
- 원본/가공 Scenario 데이터 provenance 분리

제외:
- KIS 실계좌 주문
- Live WebSocket 성공 판정
- REST를 실제 tick stream으로 간주하는 기능
- Strategy 자체의 규칙 변경
- UI 변경

## 3. 현재 계약과의 관계
표준 흐름은 다음과 같이 유지한다.

KIS Provider / Historical Provider
→ MarketDataHub
→ Canonical Market Observation
→ HistoricalMarketStore
→ Replay
→ Runtime

기존 ReferenceCanonicalMarketTick 및 `reference-canonical-market-tick-v1` 저장 형식은 기존 Replay를 위해 유지한다.
새 Observation은 기존 tick 계약을 대체하는 것이 아니라 더 풍부한 원본 보존 경계를 제공한다.
## 4. 표준 Observation 구조
Canonical Market Observation은 최소 다음 논리 영역을 가진다.
- `observation_id`: 하나의 Quote + OrderBook + 부가시장정보 묶음의 고유 ID
- `observed_at`: KIS가 제공한 시장 관측 시각. 제공되지 않으면 임의 생성하지 않고 null/UNAVAILABLE
- `collected_at`: 로컬 수집기가 응답을 받은 시각
- `source`: `kis_vts_rest` 등 명시적 source
- `provider`: KIS adapter 식별자
- `schema_version`: canonical observation schema 버전
- `run_id`: 수집/Replay 실행 단위
- `contract`: authoritative contract identity
- `quote`: last/bid/ask/volume 등
- `order_book`: bid/ask levels 및 수량
- `analytics`: KIS가 직접 제공한 IV/Greeks 등
- `provenance`: endpoint/TR/request/원본 관계
- `raw_payload_ref` 또는 동등한 raw archive 연결 정보

## 5. Contract Identity
Contract identity는 KIS 응답에서 확인 가능한 authoritative 값을 우선한다.
최소 보존 항목은 broker symbol, expiry, strike, option type이며 실제 응답이 제공하지 않는 값은 추정하지 않는다.
KIS symbol과 canonical contract identity 사이의 매핑은 별도 명시적 normalizer 책임으로 둔다.
동일 observation의 Quote와 OrderBook은 동일 contract identity를 참조해야 한다.

## 6. Quote / OrderBook / Analytics
`quote`는 last, bid, ask, cumulative volume 등 KIS REST가 실제 제공한 값을 보존한다.
`order_book`은 가능한 범위에서 각 level의 price/quantity와 total bid/ask quantity를 보존한다.
`analytics`에는 KIS 응답에서 직접 제공된 implied volatility, delta 등만 넣는다.
응답에 없는 값은 0, False, synthetic 값 또는 다른 필드로 추정하지 않는다.
Quote와 OrderBook의 시점이 동일하다는 보장은 없으므로 각 source timestamp/collection timestamp가 필요할 경우 하위 provenance에 보존한다.
## 7. Raw Archive
KIS REST의 원본 응답은 정규화 과정에서 버리지 않는다.
Raw record에는 최소 endpoint, TR ID, request 식별정보(credential 제외), HTTP status, KIS response metadata, payload, collected_at, run_id를 보존한다.
App Key, App Secret, access token 등 credential/secret은 raw archive에 저장하지 않는다.
원본 payload의 hash를 저장할 수 있으며 hash는 원본 동일성 검증 용도로만 사용한다.

## 8. Canonical Archive
Canonical record는 Replay가 직접 소비할 수 있도록 source-neutral 구조로 저장한다.
저장 단위는 한 observation을 원칙으로 하며 Quote와 OrderBook을 별도 무관 tick으로 분리하지 않는다.
저장 포맷은 명시적인 schema version을 가진다.
기존 store가 JSONL 기반이라면 기존 레코드와 신규 observation의 schema를 명확히 구분한다.

## 9. MarketDataHub 연결
MarketDataHub는 KIS REST의 원시 응답 형식을 Runtime에 노출하지 않는다.
KIS adapter/normalizer가 canonical observation을 만들고 Hub는 표준 계약만 전달한다.
기존 Hub 소비자가 ReferenceCanonicalMarketTick을 요구하는 경우 호환 projection을 제공할 수 있다.
Projection 과정에서도 원본 observation의 contract identity와 provenance를 잃지 않는다.

## 10. Replay 규칙
REST observation은 `source=kis_vts_rest` 및 snapshot 성격을 유지한 채 Replay한다.
Replay engine은 observation의 `collected_at`을 임의의 거래소 체결시각으로 승격하지 않는다.
KIS가 authoritative observed timestamp를 제공한 경우 이를 replay time-axis의 우선 기준으로 사용하고, 없으면 collection time을 사용한다는 규칙을 명시적으로 계약화한다.
1x Replay는 원본 observation 순서와 시간축을 최대한 보존한다.
가속 Replay는 시간축만 압축하며 시장 값 자체를 임의 변경하지 않는다.
## 11. Scenario / 변형 데이터
원본과 변형 데이터는 동일 record로 덮어쓰지 않는다.
Scenario record에는 원본 observation의 ID/hash/reference, scenario_id, transformation metadata, run_id를 별도로 기록한다.
변형된 가격·호가·변동성·체결 패턴은 `scenario` 또는 동등한 명시적 provenance로 표시한다.
변형 데이터를 실제 KIS/실제 KRX 관측값으로 표현하지 않는다.

## 12. Failure / missing-data 정책
필수 contract identity가 없으면 canonical 정상 관측으로 저장하지 않고 명시적 unavailable/blocked 상태로 남긴다.
Quote 또는 OrderBook의 일부 level이 없으면 존재하는 authoritative 값만 저장하고 누락을 0으로 채우지 않는다.
KIS REST 호출 실패는 raw/canonical 정상 데이터로 간주하지 않는다.
동일 observation을 구성할 수 없는 별도 응답은 각각의 provenance를 보존하고 결합하지 않는다.

## 13. 기존 Replay 호환성
기존 `ReferenceCanonicalMarketTick` 소비 경로를 먼저 깨뜨리지 않는다.
새 canonical observation에서 기존 tick projection이 필요한 경우 명시적인 adapter/projection을 사용한다.
기존 `reference-canonical-market-tick-v1` fixture와 Replay 회귀 테스트는 계속 통과해야 한다.
새 schema 도입만으로 기존 historical 데이터 재작성이나 일괄 migration을 요구하지 않는다.
## 14. 테스트 수용 기준
단위 테스트:
1. 실제 KIS REST fixture가 canonical contract identity로 정규화된다.
2. Quote와 OrderBook이 동일 observation/contract identity로 결합된다.
3. observed_at과 collected_at이 서로 덮어쓰지 않는다.
4. IV/Greeks가 실제 응답 값으로 보존된다.
5. 누락 필드는 synthetic fallback 없이 None/UNAVAILABLE 처리된다.
6. raw payload와 canonical record의 provenance 연결이 보존된다.
7. REST snapshot이 기존 Replay 호환 projection으로 변환된다.
8. scenario 변형은 원본과 provenance가 분리된다.

통합 테스트:
- MarketDataHub → Store → Replay → Runtime 경계를 실제 표준 계약으로 검증한다.
- 기존 historical/replay 회귀 테스트를 유지한다.
- credential 또는 실제 Live frame 없이 Live PASS를 만들지 않는다.

## 15. 구현 순서
1. 현재 contracts/application/store/replay의 실제 타입과 serialization 경계를 확정한다.
2. canonical observation contract와 raw/provenance contract를 추가한다.
3. KIS REST normalizer를 구현한다.
4. HistoricalMarketStore에 신규 schema 저장 경로를 추가한다.
5. MarketDataHub와 Replay의 호환 adapter를 연결한다.
6. fixture 기반 단위 테스트를 먼저 통과시킨다.
7. 실제 VTS REST 응답으로 integration verification을 수행한다.
8. 전체 pytest 및 project200 gate를 실행한다.
## 16. 비목표와 안전 경계
이 사양은 KIS REST 기반 데이터 수집·보관·Replay의 계약을 정의하는 것이며 실제 주문을 추가하지 않는다.
REST polling 결과를 WebSocket 실시간 체결 stream으로 표현하지 않는다.
VTS 검증 결과를 Live E2E 검증 결과로 승격하지 않는다.
Live credential과 실제 market-data frame 증거가 준비되기 전에는 Live runtime evidence를 BLOCKED로 유지한다.

## 17. 완료 정의
계약이 코드에 구현되고 fixture/실데이터 기반 테스트가 통과하며 기존 Replay 회귀가 유지되어야 한다.
Raw → Canonical → Store → Replay → MarketDataHub 경계에서 provenance와 contract identity가 추적 가능해야 한다.
실제 VTS REST 데이터로 최소 Quote + OrderBook + contract identity + 시간축을 재현할 수 있어야 한다.
검증 결과는 명령, exit code, commit SHA와 함께 Notion `질문과답변`에 기록한다.
