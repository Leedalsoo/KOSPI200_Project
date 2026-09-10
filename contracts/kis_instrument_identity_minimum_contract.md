# No.140 보강 — KIS 공식 Master 필드 정의 확인

KIS 공식 종목마스터정보(지수선물옵션).h에서 shrn_iscd는 단축코드, stnd_iscd는 표준코드로 별도 정의된다. KIS 공식 domestic_index_future_code.py 역시 fo_idx_code_mts.mst를 상품종류 / 단축코드 / 표준코드 / 한글종목명 / ATM구분 / 행사가 / 월물구분코드 / 기초자산 단축코드 / 기초자산 명으로 정제한다.

따라서 standard_code를 KIS 주문 API의 SHTN_PDNO로 사용하는 것은 금지한다. 주문 API의 SHTN_PDNO는 단축상품번호이므로 Master의 단축코드(shrn_iscd) 측과 연결하는 것이 의미상 올바른 경계다.

현재 프로젝트의 symbol이 실제로 shrn_iscd를 보장하는지는 별도 검증이 필요하다. 따라서 Runtime 코드는 아직 변경하지 않는다.

No.138의 후속으로 KIS Master / Market Data / Runtime / Real Broker 사이에서 실제로 어떤 값이 Instrument Identity 후보로 이동하는지 대조하고, 현재 구조에서 확정 가능한 최소 계약과 미확정 영역을 분리한다.

## 1. KIS Master

shared/contracts/option_master.py의 parse_kis_fo_idx_mst()는 원본 레코드에서 symbol, standard_code, name, prod_type을 읽는다.

현재 구현은 옵션의 symbol과 standard_code를 모두 {code: expiry} lookup key로 저장한다.

중요한 점은 현재 Master의 책임이 만기 조회라는 것이다. standard_code와 symbol의 상품식별 의미를 별도의 InstrumentIdentity 객체로 보존하지 않는다.

## 2. Market Data

option_program/market_data/market_data_adapter.py는 외부 패킷의 symbol / stck_shrn_iscd / shrn_iscd 중 하나를 CanonicalMarketTick.symbol로 전달하고, expiry도 별도로 전달한다.

그러나 이 symbol은 현재 Market Data Adapter에서 KIS Master와의 authoritative identity 일치 검증을 거치지 않는다.

따라서 CanonicalMarketTick.symbol을 자동으로 SHTN_PDNO 또는 Standard instrument_id로 승격할 수 없다.

## 3. Runtime

option_program/runtime/program_runtime.py에서 Strategy signal을 CanonicalStrategySignal로 만들 때 symbol과 expiry를 CanonicalStrategySignal에 보존하지 않는다.

이후 CanonicalOrderCommand 생성에서도 symbol을 명시하지 않는다.

결과적으로 CanonicalOrderCommand.symbol의 기본값 KOSPI200이 유지될 수 있다.

이는 No.137에서 확인한 실제 주문 경계와 연결되어, Real Broker의 SHTN_PDNO가 KOSPI200으로 전달될 수 있는 구조적 단절이다.

## 4. Real Broker

option_program/broker/real_broker_adapter.py의 _map_instrument_code()는 상품코드를 조합하지 않고 CanonicalOrderCommand.symbol을 그대로 KIS SHTN_PDNO에 전달한다.

따라서 Broker는 identity를 해결하는 계층이 아니다. 상위 계층에서 검증된 주문상품코드를 받아야 한다.

또한 현재 execution/open-order/status 조회에는 101V3000 같은 fallback symbol이 존재한다. 이는 authoritative Instrument Identity로 사용할 수 없는 호환/방어값이다.

## 5. KIS 공식 API 대조

KIS 공식 Open Trading API의 국내선물옵션 주문 계약은 SHTN_PDNO를 필수 단축상품번호로 정의하며 선물 6자리, 옵션 9자리 예시를 제공한다.

공식 예제의 주문 payload도 SHTN_PDNO를 직접 사용한다.

따라서 현재 프로젝트에서 CanonicalOrderCommand.symbol은 단순 내부 symbol이 아니라 실제 Broker 경계에서는 검증된 KIS 단축상품번호 역할을 해야 한다.

다만 KIS MST의 standard_code와 주문 API SHTN_PDNO가 동일 필드라는 직접적인 공식 매핑은 여전히 확보되지 않았다.

## 최소 계약

현재 단계에서 확정할 수 있는 최소 계약은 다음과 같다.

```plain text
Authoritative Contract/Product Master
    ↓
Instrument Identity Candidate
    ├─ broker_product_code (KIS SHTN_PDNO 후보)
    ├─ symbol
    ├─ expiry
    ├─ option_type
    └─ strike
    ↓
Identity validation / verified mapping
    ↓
Canonical Signal / Position Logic
    ↓
Canonical Order Command
    ↓
Real Broker passthrough → SHTN_PDNO
```

## 금지사항

- KOSPI200을 실제 KIS SHTN_PDNO로 사용하지 않는다.

- 101V3000 등의 fallback을 authoritative identity로 사용하지 않는다.

- standard_code를 확인 없이 instrument_id 또는 SHTN_PDNO라고 이름만 바꾸지 않는다.

- symbol + expiry + strike + option_type을 조합해 synthetic instrument_id를 만들지 않는다.

- Broker Adapter에서 identity를 추측하거나 생성하지 않는다.

- Market Data의 symbol을 검증 없이 주문상품코드로 승격하지 않는다.

## 다음 단계

KIS Master 원본의 실제 레코드 필드 정의를 확인할 수 있는 공식 자료 또는 프로젝트에 이미 저장된 원본/샘플을 확보하여 symbol, standard_code, SHTN_PDNO의 1:1 관계를 증명한다. 그 증거가 확보되기 전에는 Runtime Canonical 계약을 변경하지 않는다.