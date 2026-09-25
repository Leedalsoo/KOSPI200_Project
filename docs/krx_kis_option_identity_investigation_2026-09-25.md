# 작업 지시 G — 옵션 identity 결정에서 KRX 교차검증 생략 가능성 조사

- 조사일: 2026-09-25
- 범위: 조사·비교 문서만
- 구현 변경: 없음
- 기준: Project200 AGENTS.md §4, §10, §16, §18 및 Notion No.753~754
- 실데이터 기준일: 2026-09-22 KIS VTS 실제 수집 원본

## 0. 사전 감사

### 현재 구조

**확정**

- `infrastructure/kis/krx_kis_option_identity_resolver.py`의 현재 표준 경로는 KRX 계약 identity를 입력으로 받고, KIS Index Option Master의 `stnd_iscd`로 broker `shrn_iscd`를 reconcile한다.
- 반환 identity의 `instrument_id`는 KRX identity의 `shrn_iscd`, `symbol`은 KIS Master의 `shrn_iscd`, expiry/option_type/strike는 KRX와 KIS가 일치할 때만 채택한다.
- `contract_multiplier`는 KRX identity 값이며 provenance는 `KRX_MARKETPLACE+KIS_INDEX_OPTION_MASTER`다.
- 따라서 현재 구조에서 계약 identity의 authoritative source는 KRX, broker symbol의 authoritative source는 KIS Index Option Master다.
- AGENTS.md §10도 동일하게 명시한다.
- 현재 로컬 working tree에는 이번 조사와 무관한 기존 변경 5개가 이미 존재했다. 이번 조사에서는 기존 파일을 수정하지 않았다.

### KIS 자체 master의 실제 성격

**확정**

- 현재 코드가 사용하는 것은 REST 조회 endpoint가 아니라 KIS가 제공하는 종목정보 master 파일 `fo_idx_code_mts.mst.zip`이다.
- KIS 공식 개발자센터는 국내파생의 지수선물옵션 종목정보 파일을 제공하며, 해당 master 파일은 매일 업데이트된다고 명시한다.
- 공식 페이지의 업데이트 시각은 06:00, 06:55, 07:35, 07:55, 08:45, 09:46, 10:55, 17:10, 17:30, 17:55, 18:10, 18:30, 18:55이다.
- 현재 코드 parser는 이 파일에서 short/standard code, expiry, option type, strike를 읽고 있으며 multiplier는 현재 코드에서 250000으로 설정한다.

**추가 확인 필요**

- KIS 공식 공개 문서에서 master의 각 필드가 KRX의 expiry/strike/option type/multiplier와 동일한 의미라고 보증하는 상세 field-level contract는 확인하지 못했다.
- 따라서 실제 파일 파싱 가능성과 공식 계약 보증을 동일시하지 않는다.

## 1. KIS 자체 master 신뢰성 조사

### 신규 상장 / 만기소멸 반영 시점

**확정**

- KIS 공식 문서는 master 파일을 매일 여러 차례 업데이트한다고 명시한다.

**미정**

- 거래소 신규 상장/효력 시각과 KIS master 갱신 시각이 항상 동일한지 공식 보증은 확인되지 않았다.
- 신규 상장 또는 만기소멸이 특정 지연시간 이내에 반드시 반영된다는 보증도 확인되지 않았다.

### Weekly 옵션을 포함한 전체 만기

**미정**

- KIS 공식 공개 문서에서 지수선물옵션 master가 모든 월물과 모든 Weekly 만기를 빠짐없이 포함한다고 명시한 문구는 확인하지 못했다.
- 국내선물옵션의 지수옵션 실시간 시세와 옵션 전광판 API가 존재하는 사실만으로 master의 전체 만기 포괄성을 보증할 수 없다.

### multiplier / strike / expiry / option type

**확정**

- 실제 현재 KIS master 파일은 현재 코드 parser가 short/standard code, expiry, option type, strike를 구성할 수 있는 데이터를 제공한다.
- 2026-09-22 실제 수집 1,293건의 canonical observation에는 multiplier 250000.0이 기록되어 있다.

**미정**

- 공식 문서에서 multiplier, strike, expiry, option type 각각의 field-level 의미와 정확성 보증을 확인하지 못했다.
- 특히 현재 코드의 multiplier 250000은 KIS master에서 읽어 검증하는 값이 아니라 parser에서 고정한 값이다.

### 정확성 / 장애율 보증

**확정**

- KIS 공식 개발자센터는 master 파일의 제공 및 업데이트 일정을 명시한다.

**미정**

- 공식 문서에서 master 데이터의 정확성 보증 수준, 허용 오류율, 장애율/SLA, 누락률에 대한 수치적 보증은 확인하지 못했다.

## 2. 2026-09-22 실제 1,293건의 KIS-only 재구성 검증

### 방법

**확정**

- 코드 변경 없이 임시 검증 스크립트를 작업폴더에서 생성·실행 후 삭제했다.
- 입력은 `data/kis_market_data_restart/2026-09-22/historical_market_observations.jsonl.observations.jsonl`이다.
- 실제 파일에는 정확히 1,293건의 observation이 있다.
- 고유 KIS short symbol은 26개다.
- 현재 KIS Index Option Master는 7,128개 레코드로 파싱되었고 9/22의 26개 short symbol이 전부 존재했다.

### 필드 비교

**확정**

KIS master만으로 26개 고유 symbol의 다음 계약 필드를 9/22 observation과 일치하도록 재구성할 수 있었다.

- short symbol: 26/26 존재
- expiry: 26/26 일치
- option type: 26/26 일치
- strike: 26/26 일치(1090.0 vs 1090.00 같은 표현 차이는 정규화 시 동일)
- KIS master의 stnd_iscd: 전부 존재

**추가 확인 필요**

- canonical `instrument_id`는 9/22 observation에서 KRX short code(예: `B016AA32`)이고 KIS broker short symbol은 `B01610A32`처럼 별도 값이다.
- 따라서 KIS master만 사용하면 expiry/strike/type/symbol은 재구성할 수 있지만 현재 표준 identity의 KRX authoritative instrument_id를 동일하게 재현할 수 없다.
- 현재 observation의 identity_source도 KRX+KIS provenance다.
- multiplier는 실제 observation에서 250000.0이지만 현재 KIS parser가 고정값을 사용하므로 KIS master 단독 공급 여부는 미확정이다.

### 판정

**확정 — PASS (조사 목적)**

- 9/22 1,293건에서 KIS master만으로 broker-facing 계약 필드(symbol/expiry/type/strike)를 재구성할 수 있었다.
- 그러나 현재 표준 identity 전체(KRX instrument_id + KIS broker symbol + provenance)를 동일하게 재구성할 수는 없었다.
- 따라서 이 결과는 KRX 교차검증 제거의 완전한 근거가 아니다.

## 3. 옵션 A — 현행 유지 + KRX 다운로드 자동화

### 자동화 가능성

**확정**

- KRX Data Marketplace는 공식적으로 Excel/CSV/PDF 다운로드 기능을 제공한다.
- 공식 사이트에는 로그인 페이지가 존재한다.
- 과거 공개된 KRX 다운로드 구조는 OTP 생성 → download endpoint 제출 방식이었다.

**추가 확인 필요**

- 현재 2026년 사이트의 정확한 옵션 master OTP payload, endpoint, 로그인 세션/권한 요구사항은 공식 문서에서 확인하지 못했다.
- 따라서 현재도 동일한 OTP HTTP 자동화가 안정적으로 동작한다고 확정할 수 없다.
- 자동화 시에는 인증/session 변화와 schema 변경을 감지하고 fail-closed해야 한다.

### 장점

**확정**

- KIS 단일 장애/누락에 대비해 독립된 거래소 source로 계약 identity를 교차검증할 수 있다.
- 현재 AGENTS.md의 authoritative-source 및 fail-closed 원칙을 그대로 유지한다.
- 수동 다운로드만 자동화하면 identity resolver 구조를 변경하지 않고 운영 부담을 줄일 수 있다.

### 단점

**확정**

- KRX 다운로드 인증/OTP/session 흐름을 별도로 유지해야 한다.
- 사이트 구조 변경에 따른 유지보수 위험이 있다.
- KIS와 KRX의 갱신 경계가 다를 경우 날짜별 snapshot 관리가 필요하다.

## 4. 옵션 B — KIS 단독 사용 + 최소 안전장치

### 최소 안전장치

**확정**

1. 전일 대비 종목 수 급증/급감 sanity check → 실패 시 fail-closed
2. symbol, expiry, strike, option type, multiplier 누락 → fail-closed
3. Weekly 만기 교체 여부와 예상 만기군 변화 확인 → 불일치 시 fail-closed
4. 동일 standard/short code의 conflicting identity 검출 → fail-closed
5. master update timestamp와 수집시각 기록 → provenance 보존

**추가 확인 필요**

- 전일 대비 급증/급감 임계값은 충분한 장기 KIS master 시계열 축적 후 정해야 한다.
- Weekly 교체를 KIS master 자체만으로 완전하게 판정할 공식 기준은 현재 확인되지 않았다.

### 장점

**확정**

- KRX 수동 다운로드 절차를 제거할 수 있다.
- KIS master의 broker short symbol과 직접 연결되어 broker adapter 관점은 단순해진다.

### 단점

**확정**

- KIS master가 계약 identity와 broker symbol을 동시에 잘못 제공하는 경우 독립적인 거래소 source로 검출할 수 없다.
- 현재 표준 identity의 KRX instrument_id와 provenance를 그대로 유지할 수 없다.
- multiplier의 KIS-authoritative 공급 계약도 아직 공식적으로 확인되지 않았다.

## 5. 옵션 A/B 비교 및 권고

| 기준 | 옵션 A: KRX 유지 + 자동화 | 옵션 B: KIS 단독 + 안전장치 |
|---|---|---|
| 실거래 안전성 | 독립된 KRX/KIS 교차검증 유지 | KIS 단일 source 의존 |
| 유지보수 부담 | KRX 자동화 유지 필요 | 상대적으로 낮음 |
| 구현 난이도 | 인증/OTP 자동화가 필요 | sanity/fail-closed 구현이 필요 |
| 현재 authoritative 계약과의 일치 | 현재 구조 그대로 유지 | instrument_id/provenance 변경 필요 |
| 9/22 실제 검증 | 전체 identity 유지 가능 | broker-facing 필드는 재구성 가능하지만 전체 identity 동일 재현 불가 |

### 권고

**확정**

- 현재 AGENTS.md의 authoritative-source 원칙과 9/22 실제 데이터 검증 결과를 기준으로는 **옵션 A를 권고**한다.
- KIS-only는 broker-facing 필드 대부분을 재구성할 수 있지만 현재 표준 identity의 KRX instrument_id, 독립 교차검증, provenance를 동시에 유지하지 못한다.
- 이번 작업에서는 어떤 구조도 구현하지 않는다.

**추가 확인 필요**

- 옵션 A 자동화 전 현재 KRX Data Marketplace의 로그인/OTP/다운로드 흐름을 실제 인증 세션에서 검증해야 한다.
- KIS master의 field-level 공식 명세와 multiplier 공급 여부도 추가 확인해야 한다.

## 6. 결론

**확정**

- 현재 구조에서 KRX를 제거해야 할 근거는 이번 조사에서 확보되지 않았다.
- KIS master만으로 2026-09-22의 1,293개 observation에서 26개 고유 broker symbol의 expiry/type/strike를 재구성할 수 있었지만 현재 표준 identity 전체를 동일하게 재구성할 수는 없었다.
- identity resolver 구조는 변경하지 않는다.

**미정**

- KIS master의 Weekly 전체 만기 포괄성
- KIS master의 field-level 정확성/정확성 보증 및 장애율
- KRX의 현재 인증 세션 + OTP 자동 다운로드 계약
- KIS master에서 multiplier를 공식적으로 authoritative하게 공급하는지 여부

## 출처

1. 한국투자증권 KIS Developers — Open API 서비스 소개 / 종목정보 파일
   https://apiportal.koreainvestment.com/apiservice-summary
2. 한국투자증권 KIS Developers — 종목정보파일 / 국내파생 지수선물옵션
   https://apiportal.koreainvestment.com/apiservice-category
3. 한국투자증권 KIS Developers — API 문서 / 국내선물옵션
   https://apiportal.koreainvestment.com/docs
4. 한국투자증권 공식 Open API GitHub
   https://github.com/koreainvestment/open-trading-api
5. 한국거래소 KRX Data Marketplace — 이용안내
   https://data.krx.co.kr/contents/MDC/INFO/informationController/MDCINFO002.cmd
6. 한국거래소 KRX Data Marketplace — 로그인
   https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc
7. KRX OTP/download 방식의 과거 공개 구현 사례는 현재 공식 계약을 의미하지 않으며 기술적 참고자료로만 사용했다.
