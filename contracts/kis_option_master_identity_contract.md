No.140의 후속 설계. 기존 option_master.py의 만기 조회 기능을 유지하면서 KIS 공식 Master의 상품 식별정보를 shrn_iscd(단축코드)와 stnd_iscd(표준코드)로 분리 보존하고, 이후 Broker의 SHTN_PDNO 공급까지 연결할 수 있는 최소 계약을 정의한다.

## 현재 구현의 문제

현재 parse_kis_fo_idx_mst()는 다음과 같이 Dict[str, str]만 반환한다.

```plain text
symbol -> expiry
standard_code -> expiry
```

이 구조에서는 동일 계약의 symbol/shrn_iscd와 standard_code/stnd_iscd 관계가 사라진다. 또한 두 코드가 모두 동일한 만기 lookup key가 되어 식별자 의미를 구분할 수 없다.

## 설계 원칙

1. 기존 get_expiry(symbol) / register_contract(symbol, expiry) 의미를 유지한다.

1. 기존 호출자가 문자열 key를 사용해도 동작하도록 compatibility lookup을 유지한다.

1. 새로운 identity 레코드에서는 KIS 공식 필드 의미를 명시적으로 분리한다.

1. shrn_iscd는 KIS Broker 주문상품코드 SHTN_PDNO 공급 후보로 명시한다.

1. stnd_iscd는 별도 표준코드로 보존하며 SHTN_PDNO로 사용하지 않는다.

1. expiry/option_type/strike도 같은 계약 레코드에 보존한다.

1. Broker가 identity를 추측하거나 생성하지 않는다.

1. synthetic instrument_id를 만들지 않는다.

## 최소 데이터 계약

```python
@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: str | None
    expiry: str
    option_type: str | None
    strike: Decimal | None
    info_type: str | None
```

의미:

- shrn_iscd: KIS Master 단축코드. 주문 경계에서 SHTN_PDNO로 전달할 수 있는 authoritative 후보.

- stnd_iscd: KIS Master 표준코드. 주문상품코드와 별도 보존.

- expiry: 기존 만기 조회값.

- option_type: KIS info_type의 명시적 Call/Put 매핑 결과만 보존. 파싱/매핑할 수 없으면 임의 추론하지 않고 None.

- strike: Master acpr 원본에서 검증 후 보존. 파싱할 수 없으면 임의 추론하지 않고 None.

- info_type: KIS Master 원본 코드를 그대로 보존하여 원본 의미를 잃지 않는다.

## Lookup 구조

기존 호환 map과 identity map을 분리한다.

```plain text
_legacy_contracts: Dict[str, str]
    └─ 기존 symbol/standard_code → expiry

_contract_identities: Dict[str, KisOptionContractIdentity]
    └─ shrn_iscd → 전체 authoritative 후보 identity
```

Master load 시 하나의 원본 레코드에서 identity를 먼저 만들고,

_legacy_contracts[shrn_iscd] = expiry를 등록한다. 필요하면 기존 호환성을 위해 stnd_iscd도 expiry alias로 등록하되, identity의 primary key는 반드시 shrn_iscd로 유지한다.

## API 최소 확장

기존 API를 제거하거나 의미를 변경하지 않고 다음을 추가하는 방향으로 설계한다.

```python
def get_contract_identity(self, shrn_iscd: str) -> KisOptionContractIdentity | None:
    ...

def register_contract_identity(
    self,
    identity: KisOptionContractIdentity,
) -> None:
    ...
```

기존:

```python
get_expiry(symbol)
register_contract(symbol, expiry)
```

은 그대로 유지한다.

register_contract()는 identity 전체를 알지 못하는 기존 호출자를 위해 legacy-only 등록으로 남기고, 새 KIS Master loader는 register_contract_identity()를 사용한다.

## info_type → CanonicalOptionType 명시적 매핑 경계

KIS 공식 info_type 의미와 현재 Canonical enum을 대조한 결과:

- Canonical: CALL, PUT

- KIS: 5/D/L = Call 계열, 6/E/M = Put 계열

따라서 다음과 같은 KIS Master 전용 adapter 경계에서만 변환한다.

```plain text
KIS raw info_type
    ↓ explicit mapping
CanonicalOptionType.CALL / PUT
```

허용 매핑:

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

주의:

- 이 매핑은 KIS Master adapter에서만 수행한다.

- Canonical 자체가 KIS 코드를 알면 안 된다.

- 미지원 info_type은 매핑하지 않고 fail-closed 또는 None으로 남긴다. 주문 identity를 위해 필요한 경우 None 상태를 허용하지 않고 검증 단계에서 차단한다.

- info_type의 상품군 차이를 없애기 위해 Call/Put만 남기는 것이 목적이 아니라, 원본 info_type도 identity에 함께 보존한다.

- shrn_iscd/stnd_iscd 의미는 이 매핑과 무관하며 계속 분리한다.

## Parser 경계

현재 parser의 반환형 Dict[str, str]을 즉시 깨뜨리는 변경은 피한다. 먼저 내부적으로 원본 레코드를 identity로 파싱하는 별도 함수/계층을 설계하고, 기존 parse_kis_fo_idx_mst()는 compatibility wrapper로 유지하는 것이 안전하다.

권장 흐름:

```plain text
raw MST line
  ↓
KisOptionContractIdentity parser
  ↓
identity registry
  ├─ shrn_iscd → identity
  └─ legacy expiry aliases
```

## 중요 보류

현재 remote option_master.py가 실제로 option_type과 strike를 parts[4:]에서 어떻게 안정적으로 읽을지에 대한 고정 필드 위치는 아직 이 단계에서 코드로 확정하지 않는다. KIS Master의 공식 column order와 현재 raw line parser를 추가 대조한 뒤 구현한다.

즉 이번 단계는 데이터 계약 설계 단계이며 원격 코드를 수정하지 않는다.

## 이후 Runtime 연결 조건

```plain text
KIS Master identity
  shrn_iscd
       ↓
verified Instrument Identity
       ↓
CanonicalStrategySignal / Position Logic
       ↓
CanonicalOrderCommand.symbol = verified shrn_iscd
       ↓
Real Broker SHTN_PDNO
```

CanonicalOrderCommand.symbol의 기본값 KOSPI200을 즉시 변경하지 않는다. 실제 Strategy/Position 공급경로가 identity를 전달할 때 fail-closed 검증을 추가하는 것이 다음 후속 단계다.

## No.152 실제 구현 반영

설계 계약을 OptionProject/core/oms/option_master.py에 실제 코드로 반영했다. shrn_iscd를 identity primary key로 사용하고 stnd_iscd는 별도 보존 및 legacy expiry alias로만 사용한다. Standard instrument_id 생성과 stnd_iscd → SHTN_PDNO 변환은 구현하지 않았다.