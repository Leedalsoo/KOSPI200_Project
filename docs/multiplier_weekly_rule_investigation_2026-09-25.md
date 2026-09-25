# Multiplier·Weekly 만기 규칙 문서 조사 및 미커밋 파일 정리 결과

- 작업 지시: H
- 기준: Project200 AGENTS.md §4/§10, Notion No.758, No.760~763
- 범위: 문서 조사 + 기존 미커밋 파일 diff 확인
- production 코드 수정: 없음
- 주문 endpoint 호출: 없음

## 1. KIS Contract Multiplier authoritative 근거 조사

### 조사 대상
- KIS 공식 Option Master 원본: fo_idx_code_mts.mst
- 현재 parser: infrastructure/kis/krx_kis_option_identity_resolver.py
- 2026-09-22 실제 observation 원본
- KRX 공식 KOSPI200 Option 상품명세
- 기존 KRX Weekly Master Excel 2종

### 확인 결과
**판정: 확정**

현재 로컬에 보존된 KIS fo_idx_code_mts.mst는 pipe 구분 9개 필드 구조다.
필드는 info_type, shrn_iscd, stnd_iscd, name, atm_cls_code, acpr, mmsc_cls_code,
unas_shrn_iscd, unas_kor_name 순서이며 multiplier 필드는 없다.

현재 parser도 이 구조에서 multiplier를 읽지 않으며,
KisOptionContractIdentity 생성 시 contract_multiplier를 Decimal("250000")으로 직접 부여한다.

따라서 KIS Master 자체에서 250000을 multiplier field 값으로 확인할 수 없다.
### 2026-09-22 실제 원본 대조
**판정: 확정**

2026-09-22 observation 원본에는 contract.contract_multiplier="250000.0"이 기록되어 있다.
그러나 해당 observation의 identity_source는 KRX_MARKETPLACE+KIS_INDEX_OPTION_MASTER이며,
이 값만으로 KIS 원본 응답이 multiplier를 공급했다고 입증할 수 없다.

관측된 26개 KIS short symbol은 KIS Master에서 모두 발견되었지만,
KIS Master의 해당 raw record에는 multiplier field가 없다.

### KRX 공식 자료 대조
**판정: 확정**

KRX 공식 KOSPI200 Options 상품명세는 거래단위를
"코스피200옵션가격 × 25만(거래승수)"로 명시한다.
기존 KRX Weekly Master Excel data_2923_20260919.xlsx와
data_2935_20260919.xlsx도 실제 거래승수 column에 250000을 가진다.

따라서 현재 프로젝트에서 250000의 authoritative 근거는 KRX 상품명세/마스터에 있다.
이번 작업에서는 코드의 250000 hard-code를 수정하지 않는다.

### KIS 공식 문서 field-level 결론
**판정: 추가 확인 필요**

KIS 공식 개발자센터에서 현재 Master의 multiplier 공급을 명시하는 field-level 근거는
이번 조사에서 확보하지 못했다. KIS Master 원본 구조와 현재 프로젝트의 공식 구조 기록에는
multiplier field가 없으므로 KIS multiplier authoritative source로 승격하지 않는다.

## 2. Weekly 만기 규칙 조사
### KRX 공식 규칙
**판정: 확정**

KRX 공식 KOSPI200 Options 상품명세는 Weekly를 다음과 같이 규정한다.
- 월요일 만기: 매주 월요일, 휴장일이면 순연
- 목요일 만기: 매주 목요일, 단 둘째 목요일은 제외
- 목요일 만기일이 휴장일이면 순차적으로 앞당김

따라서 Weekly 코드만 보고 단순히 "W번호 = 해당 주의 특정 요일"로
고정 날짜를 추정해서는 안 되며, 휴장일 규칙을 반영해야 한다.

### 기존 KRX Weekly Master 실제 대조
**판정: 확정**

data_2935_20260919.xlsx의 2609W3 레코드는 최종거래일 2026/09/21,
최종결제일 2026/09/22로 기록되어 있다.
이는 2026-09-21 월요일 만기 규칙과 일치한다.

data_2923_20260919.xlsx의 2609W4 레코드는 최종거래일 2026/09/23,
최종결제일 2026/09/28로 기록되어 있다.
2026-09-23은 수요일이므로, 목요일 만기 주간상품이 휴장일 규칙에 따라
2026-09-24 예정일에서 2026-09-23으로 앞당겨진 실제 사례와 일치한다.

### 2026-09-22 KIS VTS observation 대조
**판정: 확정**

2026-09-22 실제 observation 원본의 고유 KIS short symbol은 26개다.
이 26개를 현재 fo_idx_code_mts.mst와 대조한 결과 26개 모두 Master에 존재했지만,
Master name에 Weekly 코드(예: 2609W4)가 포함된 관측 symbol은 0개였다.

즉, 9/22 실제 VTS observation 자체에는 Weekly contract sample이 없다.
따라서 9/22 observation만으로 Weekly identity/expiry를 직접 검증했다고
선언할 수 없다.

## 3. 미커밋 5개 파일 정리 방침

**판정: 추가 확인 필요 — 사용자 승인 대기**

현재 working tree에는 다음 5개 파일이 미커밋 상태다.
1. infrastructure/kis/kis_vts_weekday_collector.py
2. infrastructure/kis/krx_kis_option_identity_resolver.py
3. tests/unit/test_kis_daily_session_orchestrator.py
4. tests/unit/test_kis_weekday_collection_plan.py
5. tests/unit/test_krx_kis_option_identity_resolver.py

현재 HEAD와 origin/Project200은 모두 587d532b3fb3249420e85b20ee289d60c3bc05a9이다.
따라서 이 5개 변경은 원격 HEAD 이후의 로컬 working-tree 변경이다.

### 파일별 내용
- kis_vts_weekday_collector.py: 수집 시작/종료시각을 08:29/16:01로 변경하고,
  PROJECT200_MARKET_DATA_DIR 환경변수 기반 저장 경로 선택을 추가했다.
- krx_kis_option_identity_resolver.py: 중복 KIS standard code를 fail-closed 처리하고
  KIS-only resolver의 find_contract_identity 반환 경로를 보완했다.
- test_kis_daily_session_orchestrator.py: 08:29/16:01 경계와 저장경로 환경변수를 검증한다.
- test_kis_weekday_collection_plan.py: 2026-09-23 Weekly expiry 기대값을 검증한다.
- test_krx_kis_option_identity_resolver.py: 중복 standard code fail-closed 테스트를 추가한다.

### 정리 권고
**권고: 보류**

5개 변경은 현재 구현과 테스트에 각각 의미가 있고, 특히 resolver fail-closed와
수집 저장경로 변경은 이미 별도 구현 commit에 포함된 변경과 중복 여부를 파일별로
더 세밀하게 판단해야 한다. 사용자 승인 없이 commit하거나 삭제하지 않는다.

이번 작업에서는 stash/commit/reset/delete를 수행하지 않았다.

## 4. 9/28 이후에만 가능한 항목

**판정: 추가 확인 필요**

- 실제 KIS VTS Weekly contract observation 확보
- Weekly rollover의 날짜별 연속 검증
- 신규상장/삭제의 날짜별 검증
- KIS Master 갱신 경계와 실제 관측의 관계 검증
- 여러 거래일에 걸친 KIS↔KRX identity 1:1 교차검증
- 9/28 실제 KIS Futures/Options 데이터 기반 후속 검증

위 항목은 이번 작업에서 실행하지 않았다.

## 5. 종합 판정

- Multiplier 250000의 KIS authoritative 근거: **UNKNOWN**
- Multiplier 250000의 KRX authoritative 근거: **확정**
- Weekly 공식 만기 규칙: **확정**
- 9/21 W3 및 9/23 W4 KRX Master 실제 대조: **확정**
- 9/22 KIS VTS observation의 Weekly sample: **없음**
- 9/22 단일 데이터로 KIS Weekly authoritative expiry 검증 완료: **BLOCKED**
- 미커밋 5개 파일: **보류, 사용자 승인 전 변경 없음**
- production code 변경: **없음**
- 주문 endpoint 호출: **없음**
