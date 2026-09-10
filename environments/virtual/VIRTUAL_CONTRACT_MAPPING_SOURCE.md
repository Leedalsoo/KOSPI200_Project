## 목적

Scenario/Replay configuration이 scenario_contract_key → shrn_iscd의 explicit mapping을 authoritative input으로 공급하는 최소 형식을 고정한다.

## 지원 형식

```plain text
contract_mappings:
  - scenario_contract_key: <Scenario/Replay external key>
    shrn_iscd: <existing authoritative OptionMaster short code>
```

또는 loader에 mapping entry 목록을 직접 전달할 수 있다.

## ownership

- 실제 값의 owner: Scenario/Replay configuration

- materialization owner: Application Composition Root

- identity authority: 동일 composition scope의 OptionMaster registry

- validation: VirtualContractResolver

## 금지

- symbol/expiry/strike/type 기반 추론

- 기본 shrn_iscd

- mapping 자동 생성

- registry 복제

- 존재하지 않는 KIS identity 생성

## composition 흐름

Scenario/Replay configuration

→ VirtualContractMappingLoader

→ dict[str, VirtualContractMapping]

→ VirtualCompositionDependencies.contract_mappings

→ VirtualContractResolver

→ authoritative OptionMaster registry validation

## 현재 상태

실제 production/replay mapping 값은 authoritative source가 제공되지 않았으므로 이 문서는 형식만 정의하며 fixture 또는 가짜 shrn_iscd를 포함하지 않는다.