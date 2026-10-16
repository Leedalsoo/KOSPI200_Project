# Trading Day Boundary Table — Strategy 1/S9 D-4 and Strategy 8 DTE10 (draft)

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved. 이 표는 실행용 캘린더가 아니다.
- 목적: S1 전량 청산 및 S9 청산의 D-4 11:00 KST, S8 진입의 DTE10 경계를 한 규약으로 검증하기 위한 후보표.
- 절대 규칙: 만기일을 D=0으로 놓고, 만기일 이전으로 휴장일을 제외한 거래일만 센다. 정확한 만기일은 옵션 마스터의 `YYYYMMDD` 값만 사용한다(No.1119). 실제 옵션 마스터와 공식 거래일 달력이 대조되기 전까지 계산값은 `UNSET`이며 신규 거래·청산 스케줄의 authoritative 입력으로 사용할 수 없다.

## 1. 공식 근거 후보와 신뢰도

| 출처 | URL | 신뢰도 | 사용할 범위 / 제한 |
|---|---|---:|---|
| KRX KOSPI 200 Options 상품 설명 | https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp | 높음 (공식 상품 규칙) | 월물 최종거래일은 계약월 둘째 목요일로 안내. 특정 YYYYMMDD 계약 마스터와 해당일 휴장 조정은 별도 확인 필요. |
| KRX 파생상품시장 휴장일 규정 PDF | https://global.krx.co.kr/contents/GLB/02/0201/0201040901/Derivatives_Market_Business_Regulation%28eng%29.pdf | 높음 (공식 규정) | 시장 휴장일 규칙(12/31 등) 후보. 월별 휴장일 공지/특별휴장은 별도 대조 필요. |
| KRX 파생상품시장 업무규정 PDF | https://global.krx.co.kr/contents/GLB/02/0201/0201040901/Derivatives_Market_Business_Regulation%28eng%29.pdf | 높음 (공식 규정) | 시장 휴장일 규칙 후보. 12개월의 개별 거래일 확인은 별도 필요. |
| 국가법령정보센터 — 관공서의 공휴일에 관한 규정 | https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=285779 | 높음 (법령) | 법정 공휴일 및 대체공휴일 기준. 거래소 임시휴장/연말 일정의 완전한 목록은 아님. |
| 한국천문연구원 월력요항 | https://astro.kasi.re.kr/life/post/calendardata | 높음 (음양력/절기) | 음력 명절 날짜의 달력 후보 확인. 그 자체로 KRX 개장 여부를 확정하지 않음. |
| KRX의 해당 연도 거래일/휴장일 공지 및 Option Master export | 해당 연도 공지 URL과 원본 파일은 작업 시점에 확보하지 못함 | UNSET | 최종 달력의 필수 근거. 확보 전에는 공식 거래일 집합으로 취급 금지. |

## 2. 향후 12개월 월물 후보표

아래 둘째 목요일은 KRX 상품 설명에서 얻은 **월물 만기일 후보**이고, D-4/DTE10은 휴일을 적용하지 않은 월~금 기준 계산 후보이다. 실제 옵션 마스터와 휴장일 공지를 대조하지 못했으므로 모든 `실제 확정일`은 `UNSET`이다. 후보 날짜를 주문 스케줄에 직접 사용하지 않는다.

| 계약월 | 만기일 후보(둘째 목요일) | D-4 후보(S1/S9) | D-4 11:00 KST | DTE10 후보(S8) | 연휴/휴장 확인 | 실제 확정 상태 |
|---|---|---|---|---|---|---|
| 2026-11 | 2026-11-12 | 2026-11-06 | UNSET | 2026-10-29 | KRX 공식 휴장 공지 대조 필요 | UNSET — Option Master 미확보 |
| 2026-12 | 2026-12-10 | 2026-12-04 | UNSET | 2026-11-26 | 연말 거래소 공지 대조 필요 | UNSET — Option Master 미확보 |
| 2027-01 | 2027-01-14 | 2027-01-08 | UNSET | 2026-12-31* | 12/31은 KRX 휴장 규칙상 거래일 아님; 계산 재실행 필요 | UNSET — 달력/Option Master 미확보 |
| 2027-02 | 2027-02-11 | 2027-02-05* | UNSET | 2027-01-28 | 설 연휴와 겹치는지 공식 KRX 달력 확인 필요 | UNSET — 달력/Option Master 미확보 |
| 2027-03 | 2027-03-11 | 2027-03-05 | UNSET | 2027-02-25 | 설 연휴 뒤 거래일 수 확인 필요 | UNSET — Option Master 미확보 |
| 2027-04 | 2027-04-08 | 2027-04-02 | UNSET | 2027-03-25 | 공식 휴장 공지 대조 필요 | UNSET — Option Master 미확보 |
| 2027-05 | 2027-05-13 | 2027-05-07 | UNSET | 2027-04-29 | 노동절·어린이날 등 휴장 공지 대조 필요 | UNSET — Option Master 미확보 |
| 2027-06 | 2027-06-10 | 2027-06-04 | UNSET | 2027-05-27 | 현충일 및 대체휴일 영향 확인 필요 | UNSET — Option Master 미확보 |
| 2027-07 | 2027-07-08 | 2027-07-02 | UNSET | 2027-06-24 | 공식 휴장 공지 대조 필요 | UNSET — Option Master 미확보 |
| 2027-08 | 2027-08-12 | 2027-08-06 | UNSET | 2027-07-29 | 광복절·대체휴일 영향 확인 필요 | UNSET — Option Master 미확보 |
| 2027-09 | 2027-09-09 | 2027-09-03 | UNSET | 2027-08-26 | 추석 연휴가 9월에 있는지 공식 달력 확인 필요 | UNSET — Option Master 미확보 |
| 2027-10 | 2027-10-14 | 2027-10-08 | UNSET | 2027-09-30 | 개천절·한글날 및 대체휴일 영향 확인 필요 | UNSET — Option Master 미확보 |

`*` 휴장일이 겹칠 수 있거나 알려진 휴장 규칙과 충돌하는 weekday-only 후보이다. 이는 확정 날짜가 아니며 계산 검증의 테스트 케이스로만 남긴다.

## 3. 단일 계산 규약

1. 만기 마스터에서 exact expiry `YYYYMMDD`, 상품 종류, 계약 identity를 가져온다. 만기 마스터 누락/중복/불일치는 `UNSET/BLOCKED`.
2. 공식 KRX 거래일 캘린더를 사용한다. 토·일뿐 아니라 KRX 지정 휴장일, 임시 휴장일, 연말 휴장일을 거래일 집합에서 제외한다. 법정 공휴일 표만으로 거래소 개장 여부를 추정하지 않는다.
3. 만기일은 `D=0`; 직전 실제 거래일을 `D-1`, 그 전 실제 거래일을 `D-2`처럼 역산한다. D-4는 네 번째 직전 거래일. DTE10은 만기일 전 열 번째 실제 거래일.
4. S1/S9: D-4 날짜의 11:00 KST 경계에서 S1 청산 완료 확인 → S9 목표 수량 재계산 → S9 대기 매수 취소 완료 및 체결·포지션 대사 → 실제 남은 S9 lot 청산. 11:00 전후 경계 규칙과 주문/체결 지연 처리는 시나리오에서 검증하되, 달력 미확정이면 실행 금지.
5. S8: DTE10 계산이 검증되기 전에는 진입 차단. DTE9/10/11은 정확한 만기 마스터·공식 거래일 캘린더를 사용해 계산한 뒤에만 진입 허용 여부를 평가한다.
6. 만기일 후보가 휴장일이면 둘째 목요일을 그대로 만기일로 가정하지 않는다. KRX가 지정한 실제 최종거래일과 Option Master를 확인하고 새로 계산한다.

## 4. 시나리오 계획에 연결할 경계 벡터 (NOT_RUN)

| ID | 입력 조건 | 기대 결과 | 상태 |
|---|---|---|---|
| CAL-D4-01 | S1/S9 D-4 당일 10:59:59 KST | 승인된 D-4 종료 workflow만 시작 가능; S1 우선순위 유지 | NOT_RUN |
| CAL-D4-02 | S1/S9 D-4 당일 11:00:00 KST | 사용자 확정 11:00 규칙의 포함 여부가 UNSET이면 fail-closed | NOT_RUN / 설정 미확정 |
| CAL-D4-03 | S1/S9 D-4 당일 11:00:01 KST | 신규 S1/S9 entry 금지; 미완료 청산은 RECONCILIATION_REQUIRED | NOT_RUN |
| CAL-DTE10-01 | 실제 거래일 DTE=11 | DTE10 진입 게이트 전 단계; 기타 모든 게이트 필요 | NOT_RUN |
| CAL-DTE10-02 | 실제 거래일 DTE=10 | DTE10 허용 여부는 검증된 만기/달력과 승인 설정으로 판정 | NOT_RUN |
| CAL-DTE10-03 | 실제 거래일 DTE=9 | S8 신규 진입 금지 | NOT_RUN |
| CAL-HOL-01 | 연휴 직전 월물 만기 | KRX 공식 거래일 집합에서만 역산 | NOT_RUN |
| CAL-HOL-02 | 연휴 직후 월물 만기 | 휴장일을 건너뛴 거래일 수가 정확히 일치해야 함 | NOT_RUN |
| CAL-EXP-01 | 옵션 마스터 만기와 둘째 목요일 후보 불일치 | 마스터/공식 공지 확인 전 UNSET/BLOCKED | NOT_RUN |
| CAL-RESTART-01 | D-4 또는 DTE10 경계 직전 재시작 | 저장된 calendar/config hash 및 actual positions 대사 전 신규 주문 금지 | NOT_RUN |

## 5. 갱신 게이트

- 수집 자료: KRX 공식 연간 휴장일/거래일 공지, 해당 날짜의 실제 KOSPI200 옵션 마스터(정확한 YYYYMMDD), source URL 또는 원본 파일, 조회 시각, SHA-256.
- 확인되지 않은 날짜는 계산값으로 채우지 않고 `UNSET`으로 둔다.
- 문서만 작성했다. 테스트·REAL_VTS replay 실행, 코드·설정 변경, commit/push, Live 주문은 하지 않았다.

## Resolution path / evidence requirements (U39)

The dates above are weekday-only candidate calculations, not verified exchange dates. Do not use them for execution or claim that a month is holiday-verified. Resolve this item only after obtaining (1) the applicable official KRX trading/holiday calendar and notices, and (2) the exact KOSPI200 option expiry YYYYMMDD from the authoritative Option Master for each contract. Store retrieval time, source URL, file hash and the resulting session-count trace. Expiry is D=0; count backward only actual KRX trading sessions and exclude official exchange holidays. If the sources disagree or any expiry is absent, keep the month UNSET/BLOCKED. The currently listed 2026-11 through 2027-10 rows remain candidates and the D-4 11:00 KST inclusion boundary still needs explicit confirmation/evidence. CAL-D4-01..03, CAL-DTE10-01..03 and CAL-HOL-01..02 are scenario definitions only (NOT_RUN).

## Official KRX calendar source status (web checked 2026-10-13)

- KRX KOSPI 200 Options specification (official, high confidence for general monthly last-trading-day rule): https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp — states monthly options' last trading day is the second Thursday of the contract month. This is a general rule, not the exact expiry master for a particular contract.
- KRX official Market Closing (Holiday) lookup (official, high confidence as the calendar source, but a specific date range/export still must be retrieved and archived): https://global.krx.co.kr/contents/GLB/05/0501/0501110000/GLB0501110000.jsp
- KRX official annual derivatives calendar (official source; current page exposes year selections including 2026, but a downloadable 2027 schedule / applicable holiday notices must be captured before finalizing 2027 rows): https://open.krx.co.kr/contents/MKD/01/0110/01100303/MKD01100303.jsp
- KRX official holiday lookup (Korean page; use with the applicable derivatives market selection and archived result): https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp

Source pages were verified to exist and describe the relevant official lookup/specification. The actual 2026-11 through 2027-10 holiday list and each contract's authoritative expiry YYYYMMDD were not retrieved as evidence in this task; therefore all date rows and holiday-cluster determinations remain UNSET. Do not convert the second-Thursday rule or weekday-only arithmetic into an executable calendar.
