## 목적

외부 authoritative source가 제공한 옵션 계약 identity를 Standard Core의 OptionInstrumentIdentity로 주입하는 최소 경계를 고정한다.

## 최소 입력

외부 공급자는 다음 5개 값을 모두 포함한 OptionInstrumentIdentity를 공급해야 한다.

- instrument_id

- symbol

- expiry

- option_type

- strike

실제 Core 입력 인터페이스는 core/oms/option_identity_resolver.py의 OptionIdentityResolutionInput.instrument_identity이다.

## 책임 경계

- 외부 source/selector가 authoritative identity의 조회·선택 책임을 가진다.

- Core Resolver는 공급된 identity를 검증하고 immutable identity로 확정한다.

- Core는 외부 source의 식별자 형식을 알지 않는다.

- KIS shrn_iscd, stnd_iscd 등 broker/master-specific key를 Standard instrument_id로 변환하지 않는다.

- symbol + expiry + option_type + strike로 instrument_id를 합성하지 않는다.

- identity가 없거나 필수 값이 비어 있으면 fail-closed 한다.

- 실제 계약을 변경하는 option_type/strike override는 authoritative Contract Master/selector가 없으면 fail-closed 한다.

## 공급 형태

현재 production source가 확정되지 않았으므로 source adapter/selector를 구현하거나 Runtime에 연결하지 않는다. 향후 실제 공급원이 확보되면 그 source 전용 adapter가 완전한 OptionInstrumentIdentity를 만들어 OptionIdentityResolutionInput으로 전달한다.

## 보존 규칙

instrument_id / symbol / expiry는 공급 identity를 그대로 보존한다. Resolver 이후 OMS/Risk/Router가 identity를 재작성하지 않는다.

## 금지

- shrn_iscd -> instrument_id

- stnd_iscd -> instrument_id

- strike/type 역산

- composite key의 authoritative ID 승격

- legacy default 또는 synthetic fallback