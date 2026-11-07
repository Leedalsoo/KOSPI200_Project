# 기준 데이터 목록표 초안

- 작성일: 2026-10-13
- 상태: 초안 / TTL·담당·최종 저장 정책 UNSET
- SHA-256은 2026-10-13 로컬 파일에서 계산. 해시는 최신성·진실성의 증명은 아니다.

| 데이터명 | 용도 | 출처 | 갱신 | 주기/TTL | 저장 위치 | 기준일·수신 증거 | SHA-256 / 범위 | 담당 | 검증/비고 |
|---|---|---|---|---|---|---|---|---|---|
| KRX 휴장일 2024 | 거래일 판단 전반 | KRX Holiday OTP→JSON | 자동 구현 존재 | 연도별; TTL UNSET | data/calendar/krx/2024.json | fetched_at 2026-10-08T13:11:34.705884Z | cb14b8b8… | KRXHolidayProvider | 2024 연간 목록 |
| KRX 휴장일 2025 | 거래일 판단 전반 | KRX Holiday OTP→JSON | 자동 구현 존재 | 연도별; TTL UNSET | data/calendar/krx/2025.json | 2026-10-10T06:43:46.294478Z | c6e99730… | KRXHolidayProvider | 2025 연간 목록 |
| KRX 휴장일 2026 | 거래일 판단 전반 | KRX Holiday OTP→JSON | 자동 구현 존재 | 연도별; TTL UNSET | data/calendar/krx/2026.json | 2026-10-12T15:00:23.046399Z | 04f34419…; 17일 | KRXHolidayProvider | source/year/fetched_at 확인 |
| KRX 휴장일 2027 | 거래일 판단 전반 | KRX Holiday OTP→JSON | 자동 구현 존재 | 연도별; TTL UNSET | data/calendar/krx/2027.json | 2026-10-11T08:24:18.488702Z | 2f8e647f…; 16일 | KRXHolidayProvider | source/year/fetched_at 확인 |
| KRX 휴장일 2028 | 거래일 판단 전반 | KRX Holiday OTP→JSON | 자동 구현 존재 | 연도별; TTL UNSET | data/calendar/krx/2028.json | 2026-10-11T08:24:18.921445Z | 4076a06c…; 17일 | KRXHolidayProvider | source/year/fetched_at 확인 |
| KRX 옵션 일별 JSON 2026-09-18 | 옵션 종목/가격 관측 | KRX Open API /drv/opt_bydd_trd | 자동 수집 경로 존재 | 거래일별; TTL UNSET | data/historical/krx_raw/20260918_options_daily.json | 기준일 20260918 | 6865992c…; 16,292행 | 기존 KRX 수집기 | BAS_DD, PROD_NM, RGHT_TP_NM, ISU_CD, ISU_NM, TDD_*; exact expiry 필드 없음 |
| KRX 선물 일별 JSON 2026-09-18 | 선물 종목/가격 | KRX Open API /drv/fut_bydd_trd | 자동 수집 경로 존재 | 거래일별; TTL UNSET | data/historical/krx_raw/20260918_futures_daily.json | 기준일 20260918 | 8b99eb3a…; 385행 | 기존 KRX 수집기 | 계약 명세 전체를 대체하지 않음 |
| KRX 옵션 일별 JSON 2026-10-08 | 옵션 종목/가격 관측 | KRX Open API /drv/opt_bydd_trd | 자동 수집 경로 존재 | 거래일별; TTL UNSET | data/historical/krx_raw/20261008_options_daily.json | 수집 2026-10-09T12:49:43.851099Z; basDd 20261008; HTTP 200 | e770a22a…; 16,292행 | 기존 KRX 수집기 | manifest hash 일치; exact expiry 필드 없음 |
| KRX 선물 일별 JSON 2026-10-08 | 선물 종목/가격 | KRX Open API /drv/fut_bydd_trd | 자동 수집 경로 존재 | 거래일별; TTL UNSET | data/historical/krx_raw/20261008_futures_daily.json | 동일 acquisition manifest; basDd 20261008 | 16cc2a91…; 385행 | 기존 KRX 수집기 | manifest hash 일치 |
| KIS 선물 마스터 | 선물 identity | KIS 배포파일; 공식 갱신 출처 UNSET | 경로/주기 UNSET | TTL UNSET | fo_idx_code_mts.mst | 기준일 UNSET | c6cd3a4c…; 619,046 bytes | UNSET | identity/만기 범위 추가 검증 필요 |
| KIS 주식선물 마스터 | 주식선물 identity | KIS 배포파일; 공식 갱신 출처 UNSET | 경로/주기 UNSET | TTL UNSET | fo_stk_code_mts.mst | 기준일 UNSET | 557f780b…; 1,528,887 bytes | UNSET | mini/family coverage 검증 필요 |
| KRX exact expiry XLSX | 월물·위클리 만기 YYYYMMDD | KRX 정보데이터시스템 XLSX | 현재 자동 다운로드 미입증; 수동 필요 | UNSET | 현재 data 내 없음; 과거 Git history tests/fixtures/krx | 파일명 20260919; 실제 수신 시각 UNSET | 과거 6개 파일, 현재 작업트리 없음 | 사용자 + KRXOptionExpiryMaster | G열 최종거래일, A 표준코드=KIS stnd_iscd |
| KRX 상품 명세 | 승수/tick/행사가 간격/일반 만기 규칙 | https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp | 공식 변경 시 확인 | revision 확인 주기 UNSET | 문서/코드 위치별 | 확인일 2026-10-13 | N/A | UNSET | 일반 규칙은 개별 계약 exact expiry 대체 불가 |
| 월/목 위클리 만기 | S7 contract selection | KRX exact master + 상품 명세 | 현재 exact master는 수동 XLSX | 신규 상장/매주; 정책 UNSET | registry path UNSET | 과거 스냅샷에서 2026-09-21, 2026-09-23만 확인 | 과거 옵션 master SHA 6865992c… | 사용자 수동/자동 경로 미입증 | 월요일 휴장 시 뒤로, 목요일 휴장 시 앞으로 조정. 계약별 증거 필요 |
| Mini/정규 선물 마스터 | 선물 종목·승수·tick·만기 | KRX master/API + KIS master | XLSX 자동 취득 미입증 | UNSET | UNSET | UNSET | UNSET | UNSET | exact identity/조인 키 필요 |
| 승수·tick·행사가 간격 | 주문 가격·수량 정규화 | KRX 상품 명세 및 마스터 | 공식 변경 시 | UNSET | 기존 contracts/config 매핑 미완료 | UNSET | UNSET | UNSET | 정책 충돌 시 fail-closed |

## 전체 인벤토리 확인 범위
2026-10-13 읽기 전용 검색에서 data/calendar/krx 5개 연도 파일, data/historical/krx_raw의 4개 일별 JSON 및 2개 manifest, data/kis_market_data_restart 하위 날짜별 manifest/status, KIS REST/realtime/backfill manifest와 fo_idx_code_mts.mst, fo_stk_code_mts.mst를 확인했다. 조사한 JSON/MST/Excel/CSV 범위의 파일 수는 65개이며, data 하위 XLSX/XLS/CSV는 0개였다. 토큰 캐시 파일은 존재 여부만 확인했고 내용을 열람하지 않았다.

## 전체 SHA-256 (핵심 파일)
- data/calendar/krx/2024.json — cb14b8b8416d4e0f91ebe5c42e4f3658c7911a912ee33cd126aa8cf6db7fdeea
- data/calendar/krx/2025.json — c6e99730c744f4d067217428d63f4008cd7dac6378b2e9bef389e81960cc4a13
- data/calendar/krx/2026.json — 04f3441911ab3fd6fd9030f469d16104ff23853a8d205faa0c6e2f297f09e2ec
- data/calendar/krx/2027.json — 2f8e647feefab763aba111e99abfad8e2389e458c3a248b8f7d02884e575162c
- data/calendar/krx/2028.json — 4076a06c2438aba2cc8c394fd0d9c1e5084fb2eb3ff7d0be39a6c8ed8bfb14ac
- data/historical/krx_raw/20260918_options_daily.json — 6865992c451b6ada3f8a6ab21980e789765908262542d119655a1463b96d77b1
- data/historical/krx_raw/20260918_futures_daily.json — 8b99eb3a83379f407668745d63a57169892fa0d0fe58ac3c8e60fc6846d75201
- data/historical/krx_raw/20261008_options_daily.json — e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9
- data/historical/krx_raw/20261008_futures_daily.json — 16cc2a913f7e7b02dfb5a82c859ff01e7ed028e005de76751047e3644af8d9ec
- fo_idx_code_mts.mst — c6cd3a4c33faeca578dfd0a07dad40b08318254827c78545fbe6b50fee83b253
- fo_stk_code_mts.mst — 557f780b6b91e22a2681a7a1a81b8eed060412ba3a47dc593635ce6536f6003c

## 프로그램 판독 registry 제안
JSON registry를 메타데이터 카탈로그로 둔다. 예시 필드: schema, updated_at_utc, items[{id,data_type,path,source_url,source_as_of,fetched_at_utc,sha256,schema_version,coverage,refresh_mode,refresh_interval,max_age,status}]. 구현 시 schema 미지원, hash mismatch, path traversal, 필수 필드 누락, coverage 부족, TTL 초과는 fail-closed. Registry metadata만으로 원본이 최신/권위 있다고 간주하지 않는다.

## 미해결
- 각 데이터 유형의 TTL, 보존 기간, 운영 담당자 UNSET.
- 공식 KRX marketplace XLSX의 자동 다운로드 endpoint·약관·호출 제한은 이번 조사에서 입증되지 않음.
- 사용자 수동 파일은 사용자가 넣을 예정. 제안 landing path는 data/reference/krx/incoming/이나 이 단계에서 폴더 생성/파일 이동은 하지 않았다.
- 백업 위치/클라우드 서비스는 사용자 지정 및 승인 필요.


## 사용자 승인 기본값 (2026-10-13)

아래 값은 사용자가 이번 지시에서 명시적으로 승인한 기본값이다. 구현·스케줄러 활성화·백업 복사는 별도 작업이며 이번 단계에서는 수행하지 않았다.

| 데이터 유형 | 사용자 승인 갱신 정책 | 신선도/차단 기준 | 보관·백업 |
|---|---|---|---|
| KRX 휴장일 | 연 1회 해당 연도 목록 갱신 + 30일마다 공식 출처로 확인 | 마지막 성공 확인 시각을 기록. 30일 확인이 실패하면 확인 불가로 표시하고, 캐시만으로 최신이라고 간주하지 않음 | 원본/버전 보존, 별도 폴더 또는 클라우드에 독립 사본 1벌 |
| KRX/KIS 종목·계약 마스터 | 매 거래일 장 시작 전 갱신 | 마지막 성공 갱신으로부터 1일(24시간) 초과 시 해당 계약을 차단(fail-closed). 갱신 실패·필수 필드 누락·해시 불일치도 해당 계약 차단 | 원본/버전 보존, 별도 폴더 또는 클라우드에 독립 사본 1벌 |

- 정확한 백업 경로/클라우드 제공자, 보존 기간, 백업 자동화 방식: UNSET (이번 승인에는 구체 위치가 포함되지 않음).
- 휴장일의 30일 확인은 새 원본을 반드시 덮어쓴다는 뜻이 아니다. 확인 시각과 확인 결과를 별도로 기록하며, 원본 버전은 append-only로 보존한다.
- 종목 마스터의 “하루 초과”는 이 초안에서 경과 24시간 초과로 표현했다. 운영 구현 시 fetched_at_utc와 checked_at_utc를 분리한다.
- 이 정책은 데이터 기준 정책이며, 전략 로직이나 주문 경로를 변경하는 승인이 아니다.
- Notion Decision Log의 사용자 승인 확정 기록: No.1170 (2026-10-13), https://app.notion.com/p/3f85f4f6eaa1811d940aed923ded0907


## 2026-10-13 historical XLSX recovery status

Six historical KRX XLSX files were extracted from the Git tree immediately before c989c0c into data/reference/krx/_recovered_20260919/. All six have the Windows read-only attribute. Source: c989c0c^:tests/fixtures/krx/. These are historical schema/join validation artifacts only; do not use them as current contract master or as the sole basis for live exact-expiry decisions.

| File | Data rows | SHA-256 |
|---|---:|---|
| data_0841_20260919.xlsx | 2,524 | 07648b1009e125210d4bce69cc2e10a86bfa99203d81e6c92f1cbed01ff89657 |
| data_0900_20260919.xlsx | 13 | 5bd20b18224ca354b7efa9f6e70fc7adf741d9d116bd059087672e36ecb9ca69 |
| data_2801_20260919.xlsx | 4,600 | 7b54079c62c3414eae82a4127261a3510339f244c4af078192c1c12c0304a445 |
| data_2836_20260919.xlsx | 11 | 365c1c0f92f1387ddb2d38b8ad0405c59b235032308c1b294bca51e5eefd3b86 |
| data_2923_20260919.xlsx | 196 | dee41a33f0d343145b0da4efbad0ae548798a9596f838b2c8ff4f08eed4b0e02 |
| data_2935_20260919.xlsx | 232 | 6096dadca2c100b47bd2b5ff4968e6617e167ef8dcdcaa71bd5beae8e1d8e463 |

XLSX container integrity and read-only attribute: PASS. No existing file was overwritten and no file was deleted.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — KIS 단독 기준 재정렬(초안)

> 상태: 초안 / 사용자 승인 전. 기존 KRX 항목과 과거 해시는 삭제하지 않는다. 아래 표가 런타임 권위 출처를 재정의한다.

| 데이터 항목 | 런타임 권위 출처 | 저장/검증 | 현재 상태 |
|---|---|---|---|
| KOSPI200 옵션·선물 마스터 | KIS 공식 마스터 다운로드 | `data/reference/kis/index_master/`; KST 날짜·SHA-256·행 수 manifest; append-only; 거래일별 1회 refresh; 24시간 초과 차단 | PASS(원본 7,713행); KOSPI200 옵션 계약 행 6,976; 위클리 474 |
| 계약별 exact 만기 | KIS REST `output1.futs_last_tr_date`, TR `FHMIF10000000` | `data/reference/kis/option_expiry/`; 단축코드→YYYYMMDD, 요청/응답 시각, 응답 필드, TR, endpoint, raw-response hash, master hash; append-only | PARTIAL: 23개 성공 레코드 보존; 월물 15/15, 목요일 위클리 5/5, 월요일 위클리 3/5 성공 |
| 거래일·휴장일 | 완전한 연간 범위가 검증된 KIS 결과; 실패 시 명시적 사용자 승인 목록 | 승인 목록은 source reference, 확인일, 승인 시각/근거, holidays hash 필요 | BLOCKED: VTS CTCA0903R HTTP 500 이력; 연간 커버리지 미입증; 승인 목록 없음 |
| 계약 승수 | KIS에서 확인 가능한 권위 필드/문서만 허용 | 마스터에 승수 필드가 없으면 값 추정 금지 | BLOCKED / UNSET |
| D-4 / DTE10 | exact KIS 만기 + KIS/사용자 승인 연간 달력 | 공통 거래일 계산기, 경계 테스트 | 코드 단위 검증 PASS; 운영 계산 BLOCKED(달력 미확정) |

기존 `data/calendar/krx/*.json`, `data/historical/krx_raw/`, 복구된 KRX XLSX 및 KRX 관련 문서는 역사적 참고·fixture 전용이다. 런타임 공급, fallback, 보정 또는 기준 날짜 결정에 사용하지 않는다.

마스터 행 수 구분: 전체 7,713행, 넓은 의미의 option-like 행 7,058개(다른 기초자산의 주간 상품 유형 포함), KOSPI200 옵션 계약 유형 코드 5/6/D/E/L/M/N/O는 6,976행, 그중 위클리 L/M/N/O는 474행이다. 유형 코드는 KIS 원본 행의 코드·ASCII 계약 라벨과 함께 검증하며, 라벨 불일치 행은 제외한다.

 
## Directive F registry addendum (2026-10-14; draft / not approval)
- KIS master archive SHA-256 f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e; 7,713 rows.
- Actual offline join with 23 immutable cached exact-expiry records produced 23 identities: MONTHLY=15, THURSDAY_WEEKLY=5, MONDAY_WEEKLY=3. Mini-option exact-expiry samples are absent.
- Code/label mapping is row-corroborated but the independent official type-code dictionary is not located; mapping state PARTIAL, unknown/mismatched rows blocked.
- Contract multiplier/tick, max_quote_age and quote freshness remain UNSET.
- Annual holiday files 2026/2027 are DRAFT_USER_REVIEW_REQUIRED only, not runtime eligible. D-4/DTE10 table v4 is candidate-only and requires calendar approval.
- Greeks normalization maps KIS source keys gama/theta/vega to canonical gamma/theta/vega; full source timestamp is still absent.
- Subscription plan is pure dry-run only; no collector integration.