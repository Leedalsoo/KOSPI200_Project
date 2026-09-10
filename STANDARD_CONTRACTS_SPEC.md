## Contract ownership

contracts/ owns interfaces and DTOs.

core/ owns domain rules and order intent semantics.

application/ owns orchestration use-cases.

environments/ and infrastructure/ implement contracts.

## Required Contracts

### MarketDataProvider

- snapshot()

- subscribe()

- health()

Output: CanonicalMarketTick / MarketState.

### ClockProvider

- now()

- monotonic()

- sleep_policy() where required

Clock implementation must be injected.

### BrokerAdapter

- submit(BrokerOrderCommand)

- cancel(order_id)

- query(order_id)

Broker command is not Core OrderIntent.

### ExecutionProvider

- reports()

- query_execution()

Returns canonical ExecutionReport.

### AccountProvider

- snapshot()

Returns AccountSnapshot + freshness.

### PositionProvider

- snapshot()

Returns PositionSnapshot + freshness.

### EnvironmentLifecycle

- initialize

- connect

- start

- stop

- restart

- shutdown

### EnvironmentStatusProvider

Returns environment-neutral Runtime/Connection/Safety status.

## Option Instrument Identity 전달 원칙

- instrument_id는 주문의 기본 식별자다.

- 옵션 주문은 필요한 경우 OptionInstrumentIdentity를 함께 전달하여 symbol / expiry / option_type / strike의 권위 정보를 보존한다.

- identity는 Market Data 또는 Option Contract Master에서 authoritative하게 공급한다.

- Core → OMS → Environment Adapter 경계에서 identity를 임의 기본값으로 재생성하지 않는다.

- BrokerOrderCommand는 Core OrderIntent의 domain identity를 보존한 뒤 환경별 broker symbol/API 형식으로만 변환한다.

- VSSF 등 특정 실행환경 전용 필드는 Standard Core Contract에 직접 노출하지 않는다.

## OrderIntent 실행 의미 보존 규칙

- OrderIntent는 client_order_id / instrument_id / side / quantity와 함께 intent_type을 유지한다.

- 실제 주문 실행에 필요한 환경중립 의미가 소실되지 않도록 다음 additive 필드를 보존한다: asset_type / requested_price / order_type / order_purpose / strategy_id / track_id / tag_id.

- requested_price는 주문 요청가격이며 ExecutionReport.execution_price와 동일시하지 않는다.

- OrderIntent 생성 시 quantity, order_type, order_purpose, asset_type, instrument_id 등 실행에 필요한 값은 명시적으로 공급되어야 하며 synthetic default를 사용하지 않는다.

- OPTION identity는 OptionIdentityResolver를 통해 확정한다. 이미 확정된 instrument_id에 다른 option_type/strike를 임의로 덧붙이지 않는다.

## BrokerOrderCommand 전달 규칙

- BrokerOrderCommand는 위 환경중립 실행 의미와 확정 identity를 보존하여 환경 Adapter로 전달한다.

- broker_symbol 및 session/API 표현은 환경 Adapter가 결정한다.

- mapping validation 실패 시 Broker 호출을 수행하지 않는다.