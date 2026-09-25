# KIS-first 개발 → KRX 교차검증 → Multi-Broker 확장 설계안

작성일: 2026-09-25

## 1. 설계 목적

실전투자 전 개발·검증 단계에서는 실제 사용 중인 KIS VTS 데이터를 프로그램의 운영 기준으로 단순화하고, 실전투자 전 KRX와의 대규모 교차검증을 수행한 뒤, 다중증권사 단계에서 broker-agnostic Common Identity 구조로 확장한다.

이 문서는 설계안만 정의하며 production code의 authoritative-source 정책이나 resolver를 아직 변경하지 않는다.

## 2. 확인된 현재 기준

- Project200 AGENTS.md §4: authoritative source가 없으면 fail-closed.
- §6: KIS는 현재 broker adapter이며 향후 제3 증권사를 동일 Standard Port 뒤에 연결.
- §8/§17: broker별 raw/canonical evidence를 분리하고 broker_instrument_id와 broker-independent canonical_instrument_id를 함께 유지.
- §10: 현재 REST 수집 경계는 KRX 계약 identity + KIS master broker symbol 조합.
- §20: Multi-Broker 구현은 사용자 명시 승인 후에만 시작.
- §21: 2026-09-22 KIS VTS 실제 수집 데이터가 현재 실데이터 검증 기준.

## 3. 현재 실제 코드의 Identity 구조

현재 resolver는 KRX Marketplace identity를 계약 identity의 기준으로 받고, KIS Index Option Master의 standard code(stnd_iscd)를 통해 KIS short code(shrn_iscd)를 연결한다.

현재 반환되는 OptionInstrumentIdentity는 instrument_id=KRX short code, symbol=KIS short code, identity_source=KRX_MARKETPLACE+KIS_INDEX_OPTION_MASTER 구조다.

현재 KIS parser는 expiry/option_type/strike를 파싱하지만 contract multiplier는 250000을 코드에서 부여한다. 따라서 KIS master 자체가 multiplier의 authoritative 공급원이라는 것은 추가 검증 대상이다.

## 4. 제안하는 단계 구조

### Phase 1 — 개발/백테스트/모의투자: KIS-first

KIS Option Master + KIS VTS 실제 데이터를 운영 기준으로 사용한다.

KIS Master → KIS 기준 Option Identity → Quote → OrderBook → Execution → Replay/Strategy

이 단계에서 KRX Excel은 런타임 필수 의존성으로 요구하지 않는다. 단, 실제 시장 검증에서 KRX가 필요하다고 정의된 항목은 검증 데이터로 별도 보존한다.
## 5. Phase 1 Identity 설계 원칙

KIS-only 단계에서도 broker code와 canonical identity의 개념을 처음부터 분리한다.

- broker_id = KIS
- broker_instrument_id = KIS short code(shrn_iscd)
- broker_standard_code = KIS stnd_iscd는 별도 필드/매핑 후보
- canonical_instrument_id는 최종 Multi-Broker 공통 ID로 별도 정의

현재 OptionInstrumentIdentity에 이 필드들이 모두 존재하지 않으므로 즉시 코드 변경하지 않고 계약 변경안을 별도로 승인한다.

KIS stnd_iscd를 최종 canonical ID로 확정하는 것은 아직 미정이다. 장기 교차검증에서 KRX ISU/standard identity와의 안정적인 일대일 관계를 확인한 후 결정한다.

## 6. Phase 2 — 실전투자 전 KRX 교차검증

KIS-first로 축적한 실제 데이터를 KRX Master와 날짜별로 대조한다.

검증 범위:

1. 신규 상장/삭제
2. 월물 및 Weekly 만기
3. expiry
4. CALL/PUT
5. strike
6. contract multiplier
7. KIS standard/short code mapping
8. KRX identity와 KIS identity의 일대일 대응
9. 당일 Master boundary와 fail-closed 동작

판정 규칙:

- 필수 Identity 불일치 → PASS 금지, 해당 범위 BLOCKED/FAIL
- KIS에만 존재 → 원인 분류 후 교차검증 완료 전 실전 기준 승격 금지
- KRX에만 존재 → KIS master 반영 지연/범위 차이 여부 확인
- multiplier 등 authoritative source가 불명확한 필드 → UNKNOWN 유지

## 7. Phase 3 — Multi-Broker 확장

최종 구조:

KRX / Exchange Validation
        ↕
Common Canonical Identity
   ↙         ↓         ↘
KIS Adapter  Broker B  Broker C
   ↓           ↓         ↓
broker_instrument_id별 독립 market observation

Common Identity는 Strategy/Runtime가 사용하고, broker symbol은 Adapter/Router 경계에서만 사용한다.

Broker별 authentication, rate limit, transport, symbol은 Adapter 내부에 격리한다.

동일 canonical instrument를 여러 broker가 관측해도 broker별 raw/canonical evidence는 각각 보존한다.
## 8. 단계 전환 Gate

### Phase 1 → Phase 2

- KIS Master 필수 field 공급성 확인
- KIS VTS 실제 observation 축적
- Option Master → Quote → OrderBook → Execution identity 연속성 PASS
- 신규/Weekly/만기 rollover edge case 확보
- 실제 KIS 데이터가 없으면 BLOCKED

### Phase 2 → Phase 3

- 정의된 기간의 KIS↔KRX 교차검증 완료
- 필수 Identity field에 미해결 불일치 없음
- 신규/만기/Weekly 경계에서 fail-closed PASS
- canonical ID와 broker ID의 계약 분리 확정
- Multi-Broker 구현에 대한 사용자 명시 승인

## 9. 기존 기준과의 관계

No.758의 조사 결과는 현재 구조를 유지할 경우 KRX authoritative source를 제거할 충분한 근거가 없다는 것이었다.

이번 설계안은 그 결론을 즉시 뒤집어 production code를 변경하는 것이 아니다. 개발 단계의 운영 기준을 KIS로 단순화하고, KRX의 역할을 실전 전 독립 검증축으로 이동할 수 있는지에 대한 후속 설계안이다.

따라서 현재 resolver, AGENTS.md의 §10 authoritative-source 문구, 기존 5개 미커밋 파일은 이번 문서 작성으로 변경하지 않는다.

## 10. 구현 범위 — 현재는 문서만

이번 단계에서 변경하지 않는 파일:

- infrastructure/kis/krx_kis_option_identity_resolver.py
- contracts/types.py
- infrastructure/kis/kis_rest_market_observation_collector.py
- 기존 사용자 미커밋 5개 파일

향후 구현 승인 시 우선 검토할 범위:

1. OptionInstrumentIdentity의 broker/canonical identity 계약
2. KIS-first Option Master provider
3. KIS-first resolver
4. KRX validation adapter/validator
5. KIS↔KRX mapping evidence 저장
6. Multi-Broker Adapter Port와 Router mapping

## 11. 상태

- 설계 방향: 추가 검토 후 승인 필요
- Phase 1 KIS-first 운영: 설계상 가능
- Phase 2 KRX 교차검증: 필수 검증 단계로 유지
- Phase 3 Multi-Broker: AGENTS.md §20에 따라 사용자 승인 전 구현 금지
- KIS multiplier authoritative 여부: UNKNOWN
- KIS stnd_iscd의 최종 canonical ID 채택: 미정
- production code 변경: 없음
