## 목적

Virtual Scenario와 Replay가 실제 KIS 계약 identity를 추론 없이 명시적으로 참조할 수 있게 하는 최소 configuration/data contract를 정의한다.

이 계약은 새로운 KIS 종목 identity를 생성하지 않는다. 이미 authoritative registry에 존재하는 shrn_iscd만 참조한다.

## 최소 구조

VirtualContractMapping

- scenario_contract_key: str

- shrn_iscd: str

### 필드 의미

- scenario_contract_key: Virtual Scenario 또는 Replay가 거래 대상으로 사용하는 외부 key. Scenario source가 명시적으로 공급한다.

- shrn_iscd: KIS Option Master registry에 이미 존재하는 authoritative short code reference.

expiry, option_type, strike는 mapping 자체에 중복 저장하지 않는다. 필요 시 registry lookup 결과에서 읽는다.

## 해석 흐름

Scenario/Replay input

→ scenario_contract_key

→ exact mapping lookup

→ shrn_iscd

→ exact authoritative registry lookup

→ KisOptionContractIdentity

→ validation

→ OptionInstrumentIdentity

## Validation

1. 빈 scenario_contract_key 금지

1. 빈 shrn_iscd 금지

1. 동일 scenario_contract_key의 중복 mapping 금지

1. mapping의 shrn_iscd가 authoritative OptionContractMaster registry에 없으면 fail-closed

1. strike/type/expiry fallback lookup 금지

1. registry가 없거나 identity가 검증되지 않으면 Virtual Environment 구성 중단

## Scenario 입력 규칙

Scenario가 계약 단위를 표현하려면 각 거래 대상에 scenario_contract_key를 명시해야 한다.

Replay도 동일 key를 보존하거나 입력 이벤트에 직접 shrn_iscd authoritative reference를 제공할 수 있다. 두 경우 모두 Builder의 역할은 해석과 검증뿐이다.

## 배치 위치

KIS Master identity를 소유하는 core/oms와 Virtual input을 직접 결합하지 않는다.

권장 경계:

- mapping contract: contracts

- mapping resolver/validation: application 또는 environment composition

- authoritative identity registry: core/oms

- Scenario/Replay source: environments/virtual

## 금지사항

- scenario_contract_key를 KIS 코드 형식으로 변환하거나 추측하지 않는다.

- symbol + expiry + strike + option_type 조합으로 shrn_iscd를 찾지 않는다.

- 임의 KOSPI200_VIRTUAL identity를 생성하지 않는다.

- mapping에 실제 계약 속성을 복제해 별도 authoritative source로 만들지 않는다.

## 다음 구현 조건

이 계약 자체는 안전하게 구현 가능하지만 실제 mapping 데이터 source가 아직 없다. 다음 단계에서는 기존 Virtual Scenario 입력 형식에 scenario_contract_key를 명시적으로 공급할 수 있는 최소 확장 지점이 있는지 확인한다. 없으면 configuration source를 새로 만들되 실제 KIS 종목코드 값은 authoritative data가 제공될 때까지 포함하지 않는다.