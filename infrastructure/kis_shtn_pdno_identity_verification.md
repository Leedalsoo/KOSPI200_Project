No.137의 후속 작업으로 KIS 공식 주문 API의 SHTN_PDNO 의미와 원격 Exp_Detail_1의 standard_code를 동일한 authoritative 상품식별자로 연결할 수 있는지 검증한다.

## 검증 결과

### 1. KIS 공식 주문 API

KIS Developers 공식 Open Trading API의 국내선물옵션 주문 예제에서 shtn_pdno는 [필수] 단축상품번호이며, 설명은 선물 6자리·옵션 9자리 종목번호 예시를 명시한다.

- 선물 예: 101W09

- 옵션 예: 201S03370

따라서 SHTN_PDNO는 단순 표시용 symbol이 아니라 KIS 주문 API가 요구하는 실제 종목/상품의 단축번호다.

### 2. 원격 Exp_Detail_1의 KIS Master parser

shared/contracts/option_master.py의 parse_kis_fo_idx_mst()는 KIS 공식 fo_idx_code_mts.mst 원본에서 다음 필드를 읽는다.

- symbol

- standard_code

- name

- 상품 타입

현재 parser는 옵션에 대해 symbol과 standard_code를 모두 동일한 expiry lookup key로 저장한다.

즉 standard_code가 현재 Master 내부의 조회키로 사용되는 사실은 확인된다.

### 3. 동일성 판단

현재 확보된 authoritative 자료만으로는 KIS MST의 standard_code라는 필드명이 곧 주문 API의 SHTN_PDNO와 동일하다고 명시적으로 증명할 수 없다.

확인된 사실은 다음 두 가지다.

1. SHTN_PDNO = KIS 주문 API가 요구하는 단축상품번호.

1. standard_code = KIS MST 원본 레코드에서 제공되는 코드이며 현재 프로젝트 parser가 보존한다.

그러나 standard_code == SHTN_PDNO라는 직접적인 KIS 공식 필드 매핑 문서는 현재 확인되지 않았다.

따라서 Standard instrument_id로 승격하거나 주문상품코드로 확정하는 작업은 보류한다.

## 안전한 결론

```plain text
KIS MST standard_code
    ↓
[현재: authoritative 후보 코드]
    ↓  직접 동일성 증거가 추가되기 전까지 승격 금지
Standard Instrument Identity / KIS SHTN_PDNO
```

KOSPI200을 주문상품코드로 사용하지 않는다.

symbol + expiry + strike + option_type 조합으로 synthetic ID를 만들지 않는다.

standard_code를 단순히 instrument_id로 이름만 변경하지 않는다.

## 다음 연결 경계

```plain text
KIS official Contract/Product Master
→ verified product-code mapping
→ Instrument Identity
→ Signal / Position Logic
→ OptionIdentityResolver
→ OrderIntentFactory
→ Environment / Broker
```

Runtime의 CanonicalOrderCommand.symbol 기본값을 standard_code로 치환하는 변경은 아직 수행하지 않는다.