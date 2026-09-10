## 목적

KIS 실전 브로커 주문 계층에서 사용하는 종목 식별자 공급 경계를 정리한다.

## 실제 Exp_Detail_1 대조 결과

- shared/contracts/option_master.py는 KIS 공식 fo_idx_code_mts.mst.zip을 다운로드하고 파싱한다.

- 원본 MST 파싱 단계에서 symbol과 standard_code를 모두 읽는다.

- 그러나 현재 Master 구현은 최종적으로 {symbol: expiry}와 {standard_code: expiry} 형태의 만기 조회 정보만 보존한다.

- 따라서 현재 OptionContractMaster는 만기일 공급원이지, instrument_id를 포함한 완전한 Standard Instrument Identity 공급원으로 사용할 수 없다.

- option_program/broker/real_broker_adapter.py의 _map_instrument_code()는 CanonicalOrderCommand.symbol을 KIS SHTN_PDNO로 그대로 전달한다.

- 현재 program_runtime.py에서 CanonicalOrderCommand를 만들 때 symbol을 명시하지 않으므로 Canonical 기본값 KOSPI200이 그대로 남을 수 있다.

- 결과적으로 현재 경로는 실제 KIS 상품코드가 명시적으로 공급되지 않은 주문이 SHTN_PDNO=KOSPI200으로 전달될 위험이 있다.

## 안전한 Standard 연결 기준

```plain text
KIS 공식 Contract/Product Master
        ↓
검증된 Instrument Identity
        ↓
Strategy Signal / Position Logic
        ↓
OptionIdentityResolver
        ↓
OrderIntentFactory
        ↓
Environment / Broker
```

## 금지

- symbol + expiry + strike + option_type 임의 조합으로 상품코드 생성 금지

- KOSPI200을 실제 KIS 상품코드로 간주 금지

- Market Tick의 symbol을 검증 없이 Contract Master ID로 승격 금지

- standard_code의 의미를 공식 계약 확인 없이 instrument_id로 단정 금지

## 다음 연결 조건

KIS MST의 standard_code가 실제 주문용 SHTN_PDNO인지 공식 계약/실제 데이터 구조로 확인한 뒤, 그 값과 symbol, expiry, option_type, strike의 관계를 완전한 Instrument Identity 공급계약으로 확정한다.

그 전까지 OrderIntentFactory의 instrument identity 연결은 보류한다.