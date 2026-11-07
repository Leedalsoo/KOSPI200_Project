# 기준 데이터 보호 규칙 초안 — AGENTS.md 추가 후보

- 작성일: 2026-10-13
- 상태: 초안 / 사용자 검토 전 / AGENTS.md 미반영

## 1. Append-only 보관
1. 기준 데이터 폴더(data/reference, data/calendar, data/historical/krx_raw 등)의 파일은 삭제·덮어쓰기 금지.
2. 신규 버전은 원본기본명_수신일YYYYMMDD_SHA256앞8자리.확장자 형식으로 추가 보관한다. 같은 이름이 있으면 덮어쓰기 대신 충돌 오류를 낸다.
3. 정리가 필요하면 삭제하지 않는다. _to_delete 격리 제안과 보고만 하고, 이동은 별도 승인 후 수행한다.
4. manifest에는 경로, 원본 기준일, 실제 수신 시각(UTC), 출처 URL/메뉴/API endpoint, SHA-256, schema version, row count, coverage, 검증 상태를 기록한다.
5. SHA-256은 무결성 식별자이지 출처의 진실성이나 최신성을 단독 증명하지 않는다.

## 2. 데이터 부재 보고 전 검색 순서
1. 기준 데이터 목록표
2. Notion의 현재 PHASE·최근 20개·관련 항목 및 필요한 과거 근거
3. 작업 폴더 data 전체와 관련 코드/manifest
4. 필요한 경우 Git 이력의 추가·이동·삭제 커밋
현재 경로에서 못 찾은 사실과 과거 이력에도 없다는 결론을 구분한다. 검색 경로·패턴·결과를 보고한다.

## 3. Provenance와 fail-closed
모든 소비 경로는 출처, 기준일, 수신 시각, SHA-256, schema/version, coverage를 검증한다. 필수 필드 누락, schema drift, hash/join mismatch, coverage gap, timeout 또는 freshness TTL 초과 시 BLOCKED/UNAVAILABLE로 종료하고 누락된 항목을 명시한다. 요일 규칙으로 거래일이나 exact 만기를 추정하지 않는다.

## 4. 읽기 전용과 백업 제안
- 운영 프로세스는 수집 폴더에만 쓰기 권한을 갖고 전략 런타임은 읽기 전용으로 분리하는 방안을 권고한다. Windows Read-only 속성만으로 보안을 보장할 수 없으므로 NTFS ACL/권한 분리도 검토한다.
- 속성/ACL 변경 및 백업 실행은 사용자 승인 후에만 한다.
- 백업 후보는 사용자가 지정한 다른 물리 드라이브 또는 승인된 클라우드다. 경로·서비스·보존 기간은 UNSET. 승인 전 복사/업로드 금지.
- 복구 검증은 파일 수, SHA-256 및 샘플 복원 검사를 포함한다.

## 5. 자동 수집본과 수동 파일 우선순위
둘 다 append-only로 보관한다. 수신 시각만으로 최신성을 판단하지 않는다. 공식 기준일, coverage, schema, 출처, hash, 검증 상태를 비교한다. 검증 PASS인 최신 공식 기준일을 후보로 하되 충돌·동일 기준일·불명확한 출처는 자동 선택하지 않고 BLOCKED로 처리한다. XLSX와 API JSON은 정규화/동일성 검증 전 서로 덮어쓰지 않는다.

## 6. 정책 미정
TTL, 보존 기간, 담당자, 백업 위치는 UNSET. 본 문서는 AGENTS.md 반영 후보일 뿐이며 AGENTS.md와 파일 권한은 수정하지 않았다.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — append-only / TTL 규칙(초안)

- KIS 마스터 원본은 `data/reference/kis/index_master/`에 KST 날짜 및 SHA-256 기반의 새 파일로만 저장한다. 기존 파일·manifest를 덮어쓰거나 삭제하지 않는다.
- 매 KST 거래일에 refresh를 최대 1회 시도한다. 같은 KST 날짜의 검증된 snapshot은 재사용한다. refresh 실패 시 이전 검증본이 24시간 TTL 안에 있을 때만 임시 사용 가능하며, TTL 초과 또는 해시/manifest 불일치 시 차단한다. 당일 실패 기록이 있으면 반복 다운로드하지 않는다.
- 계약 만기 레코드는 `data/reference/kis/option_expiry/`에 단축코드별 append-only로 저장한다. `futs_last_tr_date`를 exact YYYYMMDD로 검증하고 요청/응답 시각, endpoint, TR, 응답 필드, 응답 SHA-256, 원본 마스터 SHA-256, raw response를 보존한다.
- 기존 단축코드에 다른 만기값이 발견되면 보정·덮어쓰기하지 않고 `BLOCKED` 처리한다. API 실패, 필드 누락, 형식 오류, HTTP 오류 및 EGW00201에는 자동 재시도하지 않는다. 호출 한도 오류는 원인·시각·응답 코드를 기록하고, 동시 수집기의 요청량을 확인한 뒤 운영자가 한 번만 재개한다.
- 승인 휴장일 파일은 `data/reference/kis/approved_holidays/`의 새 버전으로만 추가한다. `approval_state=USER_APPROVED`, 승인 시각/근거, 원천 URL, 확인 시각, 연도 및 휴장일 SHA-256이 모두 검증되어야 한다. 초안·미승인·해시 불일치 파일은 런타임에 사용할 수 없다.
- KRX 캐시 및 KRX 일별 자료는 보존 전용이다. KIS 실패 시 KRX로 전환하지 않는다. 완전한 KIS 연간 달력 또는 사용자 승인 목록이 없으면 거래일 계산과 신규 진입 판단은 `UNKNOWN/BLOCKED`로 처리한다.

 
## Directive F protection addendum (2026-10-14; draft)
- Master snapshot: append-only archive + SHA-256 + KST market date; at most one refresh attempt per KST date; older than 24 hours blocks affected contract. Expiry cache is immutable and keyed by symbol; conflicting exact expiries are not overwritten.
- Retry policy: no automatic retries. Requests run sequentially with at least 2 seconds between REST calls. On EGW00201 stop the batch immediately; any later retry requires a separate scheduled/authorized run after at least 60 seconds, at most one retry per symbol. If the same endpoint operation produces the same error twice consecutively, stop and report instead of trying alternate parameters.
- Holiday draft files are not runtime-eligible unless approval_state=USER_APPROVED, approval reference/time are present, and hash validates. Until a complete KIS annual calendar or user-approved list exists, calendar state is UNKNOWN and trading gates fail closed.
- Subscription plan has a hard 41-registration cap; no collector operation. Position/open-order contracts rank first, index second, active strategy needs next. Capacity-excluded strategy stages are BLOCKED. Rotation threshold settings and quote-age threshold remain UNSET.