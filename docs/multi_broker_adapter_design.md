# Multi-Broker / Market-Data Adapter 설계안

- 문서 상태: **설계 전용 / 구현 금지**
- 대상 브로커: KIS, LS증권, 향후 제3 증권사 이상
- 기준: Project200 `AGENTS.md`, Notion No.716~717
- 작성일: 2026-09-22

## 0. 범위와 설계 원칙

### 판정
- **확정**: 이번 단계는 문서와 인터페이스 스케치만 작성한다. LS 실제 연동 코드, credential 처리, 네트워크 호출은 하지 않는다. 기존 KIS 구현도 수정하지 않는다.
- **확정**: Standard Core는 증권사 내부 구현을 직접 호출하지 않고 broker-agnostic contract를 소비한다.
- **확정**: authoritative identity가 없는 값은 추정하거나 synthetic/fallback으로 채우지 않고 `UNKNOWN`/`BLOCKED`로 남긴다.
- **추가 확인 필요**: 실제 제3 증권사 선정과 각 증권사의 상품별 API 제한은 구현 전에 별도 조사한다.
- **미정**: 향후 지원할 제3 증권사의 정확한 목록.

## 1. Broker-neutral Canonical Schema

### 1.1 Identity 계층

하나의 `instrument_id`에 두 의미를 섞지 않는다.

| 필드 | 의미 | 상태 |
|---|---|---|
| `broker_id` | 데이터/주문을 제공한 증권사 식별자. 예: `KIS`, `LS`, `NH_FUTURES` | **확정** |
| `broker_instrument_id` | 해당 증권사가 실제 API에서 사용하는 고유 종목코드 | **확정** |
| `canonical_instrument_id` | 증권사와 무관한 상품 식별자. `underlying + expiry + option_type + strike`를 정규화한 ID | **확정** |
| `underlying` | 기초자산의 canonical 식별자. 예: KOSPI200 | **확정** |
| `expiry` | 만기 | **확정** |
| `option_type` | CALL/PUT | **확정** |
| `strike` | 행사가 | **확정** |
| `contract_multiplier` | 계약승수 | **확정** |
| `identity_source` | KRX/증권사 Option Master 등 authoritative source | **확정** |
| broker symbol aliases | 증권사별 단축코드/표시코드 및 alias 집합 | **확정** |

`canonical_instrument_id`는 사람이 읽는 문자열 조합에 의존하기보다, 구현 시 expiry/option_type/strike/underlying의 정규화 규칙을 하나의 contract로 고정한다. broker code는 alias이며 canonical identity의 대체물이 아니다.

### 1.2 Market Observation

| 필드 | 의미 | 상태 |
|---|---|---|
| `broker_id` | 관측 출처 증권사 | **확정** |
| `broker_instrument_id` | 증권사 수단코드 | **확정** |
| `canonical_instrument_id` | 공통 상품 ID | **확정** |
| `price` | 해당 옵션의 canonical last/mark 후보 가격 | **확정** |
| `bid[1..5]`, `ask[1..5]` | 최대 5단계 호가 | **확정** |
| `bid_qty[1..5]`, `ask_qty[1..5]` | 각 단계 호가잔량 | **확정** |
| `collected_at` | 시스템이 데이터를 수집/수신한 시각 | **확정** |
| `observed_at` | 거래소 체결/호가 시각. 원본이 제공하지 않으면 `null` | **확정** |
| `provenance` | `ORIGINAL / SCENARIO / SYNTHETIC` | **확정** |
| `source_schema_version` | 원본/정규화 스키마 버전 | **확정** |
| `raw_payload_ref` | 원본 payload 및 hash를 찾는 증거 참조 | **확정** |
| `volume` | 거래량 등 공통 선택 필드 | **추가 확인 필요** |
| `underlying_price` | 기초자산 가격 | **추가 확인 필요**; 옵션 가격과 혼용 금지 |

호가 단계가 5보다 적은 증권사는 존재하는 단계까지만 채우고 나머지는 `null`로 둔다. 5단계로 맞추기 위해 값을 복제하거나 계산하지 않는다.

### 1.3 현재 Project200과의 대응

현재 `contracts/types.py`의 `MarketObservation`은 `observed_at`, `collected_at`, `contract`, `quote`, `order_book`, `provenance`, `raw_reference`, `underlying_*`를 이미 보유한다. `OptionInstrumentIdentity`에는 `instrument_id`, `symbol`, `expiry`, `option_type`, `strike`, `contract_multiplier`, `identity_source`가 있다. `MarketQuote`는 `last/bid/ask/volume`, `MarketOrderBook`은 level별 price/quantity를 보유한다.

- **확정**: 현재 계약은 broker-neutral 설계의 기반으로 재사용할 수 있다.
- **추가 확인 필요**: `broker_id`, `broker_instrument_id`, canonical instrument identity를 명시적으로 분리하는 최종 필드명과 backward-compatibility 전략.
- **미정**: 최대 5단계 호가를 현재 `Sequence[OrderBookLevel]`에서 어떻게 엄격한 canonical 5-slot 구조로 표현할지.

## 2. Broker Adapter Interface 설계

### 2.1 공통 Port

모든 증권사 Adapter는 다음 의미의 포트를 구현한다. 실제 Python 구현은 승인 후 작성한다.

| 메서드 | 입력/출력 의미 | 상태 |
|---|---|---|
| `authenticate()` | 증권사 인증/세션 준비 | **확정** |
| `refresh_token()` | 만료 전 인증 토큰 갱신 | **확정** |
| `get_option_master()` | broker instrument code ↔ canonical instrument identity 매핑 테이블 | **확정** |
| `get_quote(instrument_id)` | canonical identity 기준 옵션 Quote Observation 반환 | **확정** |
| `get_orderbook(instrument_id)` | canonical identity 기준 OrderBook Observation 반환 | **확정** |
| `subscribe_realtime(instrument_ids, callback)` | 실시간 frame을 canonical observation으로 전달 | **확정** |
| `get_capabilities()` | REST/WS, VTS, 호가 단계, rate limit 등 capability 반환 | **확정** |
| `submit_order(command)` | 향후 broker-specific order translation 및 전송 | **추가 확인 필요**; 이번 문서에서는 상세 구현 보류 |
| `cancel_order/query_order` | 향후 주문 상태/취소 경계 | **추가 확인 필요** |

### 2.2 WebSocket 미지원 처리

- **확정**: `subscribe_realtime()`은 지원하지 않는 증권사에서 성공처럼 동작해서는 안 된다.
- **확정**: capability가 `realtime_websocket=false`이면 `NotImplemented` 또는 명시적 `UNSUPPORTED_CAPABILITY` 상태를 반환한다.
- **확정**: 상위 orchestrator가 해당 capability를 보고 REST polling scheduler로 전환한다.
- **확정**: REST fallback은 WebSocket과 동일한 latency/semantics라고 주장하지 않는다.
- **추가 확인 필요**: polling interval은 broker별 rate limit 및 상품별 제한을 보고 계산한다.

### 2.3 Capability 구조

`BrokerCapabilities` 개념 필드:

- `broker_id`
- `rest_market_data`
- `websocket_realtime`
- `paper_trading`
- `live_trading`
- `max_orderbook_levels`
- `rate_limits` (endpoint/group별 요청 한도와 window)
- `supported_asset_types`
- `supported_option_markets`
- `authentication_mode`
- `token_refresh_supported`

- **확정**: capability는 코드의 if/else로 흩어지지 않고 Adapter가 구조화된 값을 반환한다.
- **추가 확인 필요**: 각 broker의 실제 수치와 상품별 capability.
- **미정**: rate limit을 단일 숫자로 저장할지 endpoint/group 단위 map으로 저장할지.

## 3. 현재 KIS 구현과의 정합성 점검

### 3.1 `contracts/broker.py`

현재 `BrokerAdapter`는 `submit`, `cancel`, `query` 중심의 environment-side broker boundary다.

- **확정**: 주문 경계로서는 존재한다.
- **추가 확인 필요**: 이번 설계의 market-data/auth/master capability까지 포함한 broker-neutral adapter port와 역할을 분리하거나 확장해야 한다.
- **미정**: 기존 주문 `BrokerAdapter`를 그대로 확장할지, `BrokerTradingPort`와 `BrokerMarketDataPort`를 분리할지. 설계상으로는 분리된 두 port와 이를 조합하는 `BrokerAdapterBundle`을 권장한다.

### 3.2 `environments/live/broker/kis_live_broker.py`

현재 `LiveBrokerAdapter`는 `connect()`에서 transport authentication을 수행하고, risk/idempotency gate 후 주문을 transport로 전달한다.

- **확정**: 인증과 주문 전송의 실제 경계는 존재한다.
- **추가 확인 필요**: 공통 `authenticate()/refresh_token()/get_capabilities()` port를 직접 구현하는 broker-neutral adapter가 아니다.
- **추가 확인 필요**: KIS-specific futures command translation과 Live safety policy가 broker-neutral contract와 분리되어야 한다.
- **미정**: KIS 주문 adapter를 향후 새 broker adapter bundle의 `trading` component로 감쌀지, 기존 live composition을 점진적으로 교체할지.

### 3.3 `infrastructure/kis/*`

- `auth.py`: KIS VTS/REAL base URL, token cache, env 기반 KIS credential 처리 → **추가 확인 필요**: 공통 credential interface와 분리.
- `kis_rest_market_observation_collector.py`: Price + OrderBook REST 수집, 1 req/sec limiter, raw/canonical 저장, KIS Option Master identity reconcile → **확정**: market-data adapter의 실제 기능을 상당 부분 수행. **추가 확인 필요**: KIS-specific TR/transport와 canonical port의 분리.
- `kis_realtime_collector.py`: raw WebSocket frame capture → **확정**: raw-frame 경계. **추가 확인 필요**: canonical adapter의 `subscribe_realtime()`와 raw collector의 역할 분리.
- `instrument_master_provider.py`: 현재 구현은 KIS domestic index-futures master 중심 → **추가 확인 필요**: KOSPI200 index-option master를 broker-neutral mapping으로 공급하는 별도 경계.
- `option_orderbook_source.py`: KIS-specific option orderbook source → **추가 확인 필요**: broker-neutral `get_orderbook()` port 뒤의 infrastructure implementation으로 배치.

- **확정**: 현재 KIS 코드를 이번 작업에서 수정하지 않는다.
- **미정**: 기존 KIS 파일의 최종 이동/래핑 방식은 구현 단계에서 별도 승인 후 결정한다.

## 4. Multi-Broker Collection Orchestration

### 4.1 실행 구조

`BrokerRegistry → BrokerAdapterSession(KIS) / BrokerAdapterSession(LS) / BrokerAdapterSession(B3) → Broker-local Scheduler → Canonicalizer → Shared Historical Store`

각 broker session은 독립 task/process와 독립 rate limiter를 갖는다.

- **확정**: KIS의 1 req/sec 제한이 LS의 rate limit을 소비하지 않는 구조로 만든다.
- **확정**: broker별 인증, reconnect, rate-limit state, error budget, health state는 독립적이다.
- **확정**: shared store에는 `broker_id`를 포함한 canonical Observation을 저장한다.
- **추가 확인 필요**: 프로세스와 asyncio task 중 최종 배치 방식은 실제 latency/운영 규모 검토 후 결정.

### 4.2 저장 구조

`data/<market-data-root>/<broker_id>/YYYY-MM-DD/`

예:

- `data/<market-data-root>/KIS/2026-09-22/`
- `data/<market-data-root>/LS/2026-09-22/`
- `data/<market-data-root>/NH_FUTURES/2026-09-22/`

각 broker 날짜 partition에는 raw payload, canonical observation, manifest/status/audit를 둔다.

- **확정**: No.716~717의 날짜별 저장 원칙을 broker dimension으로 확장한다.
- **확정**: broker별 파일을 물리적으로 분리하되, 분석/Replay 계층에서는 공통 Historical Store index를 통해 합칠 수 있다.
- **추가 확인 필요**: 현재 Project200의 기존 `data/kis_market_data...` root와의 migration/compatibility 정책. 이번 작업에서는 기존 경로를 변경하지 않는다.

### 4.3 동일 instrument 중복

같은 `canonical_instrument_id`를 KIS와 LS가 동시에 수집하면 **중복이 아니라 서로 다른 source observation**이다.

최소 event identity는 다음 조합을 권장한다:

`broker_id + canonical_instrument_id + observed_at + collected_at + source_sequence/raw_hash`

- **확정**: `canonical_instrument_id`만으로 unique key를 만들지 않는다.
- **확정**: 같은 계약의 KIS/LS observation을 각각 보존한다.
- **확정**: 동일 broker의 동일 raw payload 반복은 raw hash/dedup 정책으로 판별하되, 실제 서로 다른 `collected_at` 관측 이벤트를 임의 삭제하지 않는다.
- **추가 확인 필요**: cross-broker 비교용 `observation_group_id` 도입 여부.

## 5. Multi-Broker Execution / Position / PnL

### 5.1 모델 A — 계좌별 독립 원장

각 broker/account마다 Position, Margin, Cash, Realized/Unrealized PnL을 독립적으로 유지한다.

- 전략이 KIS와 LS에 동시에 주문하면 두 계좌에 별도 lot/execution/provenance가 생긴다.
- 집계 화면에서는 read-only aggregation view로 합산한다.

- **확정**: 실제 주문 원장과 책임 소재를 보존하는 기본 모델로 채택한다.
- **추가 확인 필요**: broker/account별 수수료·증거금·환산 규칙.

### 5.2 모델 B — 개념적 합산 원장

동일 `strategy_id + canonical_instrument_id`를 기준으로 broker별 Position/PnL을 가상으로 합산한 전략-level view를 별도로 만든다.

- 실제 broker account ledger는 삭제하지 않는다.
- 합산은 분석/리스크/대시보드용 derived view다.

- **확정**: 합산은 실제 계좌 원장을 대체하지 않는다.
- **미정**: 합산 Position을 Risk 입력으로 사용할지 여부. 실제 주문 가능 수량은 반드시 계좌별 원장에서 다시 확인해야 한다.

### 5.3 주문 broker 선택 위치

추천 책임 위치는 `Strategy`가 아니라 `Order Router / Broker Allocation Policy`다.

입력 후보:

1. 증거금/주문가능금액 여유
2. 수수료/거래비용
3. 현재 bid/ask 및 유동성
4. broker capability/시장 지원 여부
5. rate-limit/health 상태
6. 장애 시 failover 정책

- **확정**: Strategy는 특정 증권사 API를 직접 선택하지 않는다.
- **확정**: Broker allocation은 application/OMS 계층의 명시적 policy로 둔다.
- **추가 확인 필요**: 실제 allocation scoring/priority 규칙.
- **절대 조건**: AGENTS.md의 실주문 금지 원칙을 유지하며, 이 설계 단계에서는 어떤 주문도 전송하지 않는다.

## 6. LS증권 OPEN API 문서 기반 적용 가능성 검토

### 6.1 공식 문서 확인 범위

2026-09-22 기준 LS증권 공식 OPEN API 포털에서 다음 사실을 확인했다.

- OPEN API는 OAuth 2.0 기반 접근토큰 발급을 제공하며 appkey/appsecretkey를 사용한다.
- 공식 API 목록에 선물/옵션 시세의 `t2111`, `t2112`, 그리고 API용 `t8433`(지수옵션마스터), `t8434`(선물/옵션멀티현재가), `t8435`(파생종목마스터)가 명시되어 있다.
- 공식 실시간 시세 목록에 `OC0`(KOSPI200옵션체결)와 `OH0`(KOSPI200옵션호가)가 명시되어 있다.
- 공식 WebSocket 예제는 `wss://openapi.ls-sec.co.kr:9443/websocket` 연결 및 subscription 메시지를 사용한다.
- 공식 포털은 테스트베드 개발자 콘솔과 xingACE 모의투자 기반 테스트 환경을 제공한다고 설명한다.

출처는 문서 하단에 기록한다.

### 6.2 LS 항목별 판정

| 요구 항목 | 공식 문서 확인 | 판정 |
|---|---|---|
| LS 증권사 수단코드 형식 | 현재 검색/페이지에서 t8433/t8435 명칭은 확인했으나 상세 response field가 업스트림 오류로 표시되지 않음 | **UNKNOWN** |
| t8433 필드 → canonical expiry/type/strike/multiplier | 상세 필드표 확인 불가 | **UNKNOWN** |
| t8434 현재가 → price/bid/ask 등 | TR 존재는 확인. 상세 field mapping은 미확인 | **UNKNOWN** |
| t8435 파생 master → identity mapping | TR 존재는 확인. 상세 field mapping은 미확인 | **UNKNOWN** |
| OC0 실시간 옵션 체결 | 공식 목록에 명시 | **확정** |
| OH0 실시간 옵션 호가 | 공식 목록에 명시 | **확정** |
| WebSocket subscribe 구조 | 공식 WebSocket endpoint 및 subscription 예제가 존재 | **확정** |
| REST polling fallback 가능성 | REST 선물/옵션 시세 TR 존재 | **확정** |
| 모의투자/테스트베드 | 테스트베드 및 xingACE 설명 확인 | **확정** |
| 실전/모의 API key 분리 발급 | 공개 문서에서 이 질문에 대한 명시적 문구를 확인하지 못함 | **UNKNOWN** |
| KIS와 동일한 credential 구조 | OAuth/token/appkey 구조의 일부 유사성은 확인되지만 동일성은 공식 문서로 확정할 수 없음 | **UNKNOWN** |
| 상품별 rate limit | API 목록 일부에 초당 전송 건수가 표시되나 t8433/t8434/t8435 상세 수치는 현재 페이지에서 확인 불가 | **UNKNOWN** |

### 6.3 LS Adapter 설계 결론

- **확정**: LS는 공식 문서상 REST + WebSocket 기반의 선물/옵션 시장데이터 경계를 제공하므로 본 설계의 Adapter 형태와 구조적으로 맞출 수 있다.
- **확정**: `OC0/OH0`는 각각 체결/호가 실시간 source로 분리할 수 있다.
- **추가 확인 필요**: t8433/t8434/t8435의 실제 response fields를 공식 상세 문서에서 확보한 뒤 canonical field-by-field mapping table을 작성해야 한다.
- **추가 확인 필요**: 실전/모의 endpoint 및 credential 발급 정책을 구현 전에 공식 문서로 재확인해야 한다.
- **미정**: LS의 실제 canonical identity를 어떤 필드 조합으로 구성할지. 실제 master field 확인 전에는 정하지 않는다.
- **금지**: LS 계정/credential이 없는 현재 단계에서 실제 API 호출이나 주문 테스트를 하지 않는다.

## 7. 권장 최종 구조

```text
                    +---------------------------+
                    | Standard Core Contracts   |
                    | Canonical Instrument      |
                    | Canonical Observation     |
                    +-------------+-------------+
                                  |
                    +-------------v-------------+
                    | Broker Registry / Router |
                    +------+------+-------------+
                           |      |
              +------------+      +-------------+
              |                                 |
       +------v------+                    +-----v------+
       | KIS Adapter |                    | LS Adapter |
       | auth/master |                    | auth/master|
       | quote/OB/WS |                    | quote/OB/WS|
       +------+------+                    +-----+------+
              |                                 |
              +----------------+----------------+
                               |
                    +----------v----------+
                    | Historical Store    |
                    | broker-separated    |
                    | date partitions     |
                    +----------+----------+
                               |
                    +----------v----------+
                    | Replay / Analytics  |
                    | broker-aware        |
                    +---------------------+
```

- **확정**: Standard Core에는 KIS/LS TR 코드나 credential field를 넣지 않는다.
- **확정**: broker-specific identity는 adapter 내부에서 canonical identity로 reconcile한다.
- **확정**: broker별 raw evidence와 canonical observation을 보존한다.
- **추가 확인 필요**: 주문까지 포함한 최종 `BrokerAdapterBundle` composition은 향후 implementation design에서 확정한다.

## 8. 구현 전 승인 게이트

이 문서는 승인 전까지 **구현하지 않는다**.

승인 후 구현 시 최소 순서는 다음과 같다.

1. canonical identity/observation contract 확정
2. market-data port와 trading port 분리 확정
3. KIS adapter를 기존 구현과 비파괴적으로 연결하는 composition 설계
4. LS 공식 master 상세 field 확보 후 mapping contract 작성
5. broker별 독립 scheduler/rate limiter 구현
6. broker-separated Historical Store 구현
7. synthetic 없이 fixture/실데이터 기반 adapter contract test
8. Virtual 환경에서 multi-broker closed-loop 검증
9. Live는 각 broker의 credential과 실제 frame 증거가 준비된 후 별도 검증

### 최종 상태

- **확정**: 이번 작업의 산출물은 설계 문서 1개뿐이다.
- **확정**: 기존 KIS 코드 변경 없음.
- **확정**: LS credential/네트워크 호출 없음.
- **확정**: 실제 주문 없음.
- **추가 확인 필요**: LS 상세 TR field mapping 및 credential 운영정책.
- **미정**: 제3 증권사 및 최종 broker allocation policy.

## 공식 출처

1. LS증권 OPEN API 소개: https://openapi.ls-sec.co.kr/about-openapi
2. LS증권 OPEN API 가이드/선물옵션 목록: https://openapi.ls-sec.co.kr/apiservice
3. LS증권 OPEN API 선물/옵션 시세 및 master TR 목록: https://openapi.ls-sec.co.kr/apiservice?api_id=9f467798-6ce6-4d31-ab93-5a0e2860f89f&group_id=2f1eea77-5606-4512-93c6-31b21d2ece90
4. LS증권 API 투자전략센터 소개/샘플: https://openapi.ls-sec.co.kr/howto-use
5. LS증권 xingAPI/테스트 환경 안내: https://openapi.ls-sec.co.kr/howto-sample
