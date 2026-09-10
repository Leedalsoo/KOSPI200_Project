## 목적

KIS 공식 Master의 info_type과 Standard Core의 CanonicalOptionType 사이의 의미 변환을 KIS 전용 adapter 경계로 고정한다.

## 확인된 양쪽 계약

### Canonical

원격 Exp_Detail_1의 shared/contracts/canonical.py에서 CanonicalOptionType은 정확히 다음 두 값이다.

- CALL = "CALL"

- PUT = "PUT"

### KIS Master

공식 Master의 info_type 의미:

- 5 = 지수 콜옵션

- 6 = 지수 풋옵션

- D = 미니 콜옵션

- E = 미니 풋옵션

- L = 위클리 콜옵션

- M = 위클리 풋옵션

## 명시적 매핑

```python
KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": CanonicalOptionType.CALL,
    "D": CanonicalOptionType.CALL,
    "L": CanonicalOptionType.CALL,
    "6": CanonicalOptionType.PUT,
    "E": CanonicalOptionType.PUT,
    "M": CanonicalOptionType.PUT,
}
```

## 매핑 위치

매핑은 KIS Master adapter / parser layer에 둔다.

금지:

- Canonical contract가 KIS info_type을 직접 해석

- Broker가 info_type을 해석

- Strategy가 KIS 코드를 보고 Call/Put을 추론

- action, track_id, tag_id, side 등으로 option_type 생성

권장 흐름:

```plain text
KIS raw MST
  ↓
KIS Master Record
  ├─ shrn_iscd
  ├─ stnd_iscd
  ├─ info_type (원본 보존)
  ├─ acpr
  └─ expiry (기존 계산/조회 의미)
       ↓
KIS-specific explicit adapter
  ├─ info_type → CanonicalOptionType
  └─ acpr → validated strike
       ↓
verified OptionInstrumentIdentity
       ↓
Standard Signal / Position Logic / OMS
```

## Fail-closed 규칙

1. 지원하지 않는 info_type은 Call/Put으로 임의 분류하지 않는다.

1. 옵션 주문에 option_type이 필요하지만 명시적 매핑 결과가 없으면 Resolver/validation에서 차단한다.

1. 원본 info_type은 가능한 한 identity record에 보존한다.

1. shrn_iscd는 KIS short code이며 SHTN_PDNO 공급 후보이고, stnd_iscd와 혼동하지 않는다.

1. instrument_id는 이 매핑만으로 생성하지 않는다.

1. KOSPI200을 상품 ID 또는 KIS short code로 보완값 사용하지 않는다.

## Strike / Expiry 경계

- acpr는 Master의 행사가 원본이며 검증 후 strike로 공급한다.

- expiry는 Master에 독립 컬럼으로 존재한다고 가정하지 않고 기존 프로젝트의 월물/위클리 만기 계산 및 lookup 의미를 유지한다.

- option_type은 info_type의 명시적 매핑으로만 생성한다.

## 현재 상태

이번 단계에서는 원격 Exp_Detail_1 코드를 수정하지 않는다. 다음 구현 단계에서 이 adapter를 실제 Master identity parser/registry에 연결하되, 기존 get_expiry() / register_contract() 호환 API와 분리하여 기능을 보존한다.