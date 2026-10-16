# KRX 기준 데이터 수동 다운로드 안내 (초안)

- 작성일 2026-10-13 / 초보자용 / 신규 파일은 사용자가 직접 다운로드 후 배치
- 이 문서 작성 중 파일 다운로드·복구·이동을 수행하지 않았다.

## 1. 필요한 파일 패턴과 용도

| 과거 파일 패턴 | 용도(과거 스냅샷 기준) | 주의 |
|---|---|---|
| data_2801_YYYYMMDD.xlsx | 파생상품 옵션/종목 master 후보, exact 최종거래일 확인 | 현재 메뉴명과 번호 대응은 다시 확인 필요 |
| data_2836_YYYYMMDD.xlsx | 파생상품 보조/선물·스프레드 계열 후보 | 옵션 데이터와 혼합 금지 |
| data_0841_YYYYMMDD.xlsx | 파생상품 종목/계약 목록으로 과거 사용 | 현재 메뉴명 UNSET |
| data_0900_YYYYMMDD.xlsx | 과거 소량 보조 파생상품 목록 | 상품이 혼합될 수 있음 |
| data_2923_YYYYMMDD.xlsx | 과거 목요일 위클리 계열 목록 | 현재 메뉴명 UNSET |
| data_2935_YYYYMMDD.xlsx | 과거 월요일 위클리 계열 목록 | 현재 메뉴명 UNSET |

위 번호는 과거 파일 이름이다. 현재 KRX가 같은 번호로 동일 파일을 제공한다는 보증은 아니다. 화면에서 실제 메뉴명·조회 조건·헤더를 확인하기 전까지 UNSET이다.

## 2. KRX에서 다운로드
1. https://data.krx.co.kr/ 를 연다.
2. 메뉴 검색에서 “파생상품 종목정보”, “옵션 종목”, “선물 종목”, “최종거래일”을 검색한다. 이 조사에서는 과거 파일 번호에 대응하는 현재 메뉴명을 공식 페이지에서 확인하지 못했다.
3. 월물 옵션, 월요일 위클리, 목요일 위클리, 정규 KOSPI200 선물, Mini KOSPI200 선물을 상품별로 구분해 조회한다. 가능하면 조회 기준일과 상품 구분 조건을 기록한다.
4. 엑셀 다운로드를 선택한다. 로그인·이용약관·호출 제한이 표시되면 공식 화면의 안내를 따른다. 이 조사는 해당 XLSX 자동 취득의 약관·요청 빈도·인증 요건을 확인하지 못했다.
5. 파일을 열어 헤더 A 표준코드, B 단축코드, C 한글종목명, G 최종거래일을 확인한다. H 최종결제일은 최종거래일/만기일이 아니다.
6. 월물·월요일 위클리·목요일 위클리 각 10개 이상 표본(행이 10개 미만이면 전체)을 확인할 수 있도록 원본 파일을 보존한다. 파일 기준일과 실제 다운로드 일시는 별도로 기록한다.

## 3. 저장 위치와 이름 규칙
제안 경로(현재 폴더 미생성): C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\reference\krx\incoming\
사용자가 파일을 준비한 뒤 실제 폴더를 확인한다. 기존 파일과 같은 이름이 있으면 덮어쓰지 않는다. 보관용 버전 이름은 원본기본명_받은날짜YYYYMMDD_SHA256앞8자리.xlsx 형태로 한다. 기존 data/calendar 또는 data/historical 파일을 대체하지 않는다.

## 4. 파일 배치 후 검증
1. 파일 경로, 크기, 수신 시각, 화면 메뉴, 기준일/조회 조건을 기록한다.
2. SHA-256, XLSX 유효성, 필수 헤더와 G열 날짜 형식을 확인한다. YYYYMM만 있거나 G열이 비어 있으면 실패다.
3. 월물·월요일 위클리·목요일 위클리의 표본과 커버 범위를 확인한다.
4. KRX 표준코드와 KIS stnd_iscd 연결을 검사한다. KRX 단축코드를 KIS shrn_iscd로 추정 연결하지 않는다.
5. 불일치·누락은 보정하지 않고 보고한다. 만기·join key·freshness가 입증되지 않으면 해당 계약을 BLOCKED로 둔다.

## 5. 확인된 자동화 한계
- 휴장일은 infrastructure/kis/holiday_fallback_provider.py에 KRX 공식 OTP→JSON 수집 구현이 있다.
- KRX Open API /drv/opt_bydd_trd의 2026-10-08 응답에는 BAS_DD, PROD_NM, RGHT_TP_NM, ISU_CD, ISU_NM, TDD_CLSPRC 등 15개 필드가 있었고 exact 최종거래일 필드는 없었다. 따라서 이 endpoint의 일별 시세/종목 행을 exact 만기 마스터로 대체하지 않는다.
- KRX KOSPI200 옵션 공식 상품 설명: https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp — 일반 월물/월·목 위클리 규칙을 설명하지만, 개별 계약의 exact YYYYMMDD 마스터를 대신하지 않는다.
- 자동 XLSX 다운로드 endpoint, 약관, 인증 및 호출 제한은 입증되지 않았다. 만기 마스터 자동 갱신은 아직 BLOCKED이고 수동 다운로드 절차가 필요하다.


## KRX XLSX 자동 다운로드 조사 보충 (2026-10-13)

### 휴장일 Excel의 확인된 OTP→파일 흐름

- 화면/메뉴: KRX 정보데이터시스템의 휴장일 조회 화면. 기존 URL 경로는 /contents/MKD/01/0110/01100305/MKD01100305.jsp.
- OTP 요청 endpoint: http://marketdata.krx.co.kr/contents/COM/GenerateOTP.jspx (legacy reference scheme; HTTPS behavior not tested)
- 휴장일 XLS 요청의 확인된 파라미터:
  - name=fileDown
  - filetype=xls
  - url=MKD/01/0110/01100305/mkd01100305_01
  - search_bas_yy=YYYY
  - gridTp=KRX
  - pagePath=/contents/MKD/01/0110/01100305/MKD01100305.jsp
- 다운로드 endpoint: http://file.krx.co.kr/download.jspx (legacy reference scheme; HTTPS behavior not tested); POST form의 code에 OTP 값을 전달한다.
- 이 경로는 기존 infrastructure/kis/holiday_fallback_provider.py의 KRX OTP→JSON 구현과 별개의 XLSX 다운로드 경로다. 이번 조사는 이 요청을 실제 전송하지 않았다.
- 파라미터 근거: [KRX 휴장일 화면](https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp), [OTP→XLS 절차를 기록한 기술 참고자료](https://hayjo.tistory.com/71). 두 번째 링크는 공식 문서가 아니라 과거 기술 참고자료다. 실제 자동화 전에 브라우저 Network로 현행 요청을 재확인해야 한다.

### 계약 마스터 화면과 미확정 항목

기존 Q&A의 실제 파일 검증 기록에 따른 화면/자료 이름:
- 현행 KRX Data Marketplace에서 확인되는 상위 메뉴 경로는 파생상품 > 종목정보 > 전종목 기본정보 ([공식 메뉴](https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd))이다. 구형 번호별 화면과 현행 화면의 정확한 대응/필터 상태는 아직 검증되지 않았다.
- 0841: 미니 KOSPI200 옵션
- 0900: 표준 KOSPI200 선물
- 2801: KOSPI200 옵션 전종목 기본정보
- 2836: 미니 KOSPI200 선물
- 2923: KOSPI200 위클리 옵션(목요일)
- 2935: KOSPI200 위클리 옵션(월요일)

위 번호는 프로젝트 기록에서 확인된 화면/자료 식별값이다. 각 화면별 현재 url/pagePath/추가 필터 파라미터는 실제 Network 캡처로 확인하지 않았으므로 UNSET; 휴장일의 url 값을 다른 화면에 그대로 재사용하지 않는다.

### 이용 약관·호출 제한

- [KRX Data Marketplace 홈페이지 이용약관](https://data.krx.co.kr/contents/MDC/INFO/informationController/MDCINFO003.cmd) 제10조는 자동화 수단을 이용한 무단 수집·복제·배포를 금지하고, 제12조는 거래소 사전 허락 없는 정보 복사·복제·배포·전송·공중송신을 제한한다. 제12조의2는 마켓데이터 이용에 별도 약관이 적용될 수 있다고 명시한다.
- 공개된 홈페이지 약관에서 분당/일일 요청 수 같은 숫자로 된 호출 한도는 확인하지 못했다. 이는 제한이 없다는 뜻이 아니다.
- 따라서 OTP 기술 흐름은 구현 가능성을 보여주지만, 해당 계약 마스터의 자동 수집이 허용된다고 결론 내릴 수 없다. KRX의 허용 범위와 적용 약관을 서면/공식 문의로 확인하기 전에는 자동 다운로드 실험·스케줄러 구현을 하지 않는다.
- 제안만 기록: 사용자가 승인하면 My_Playwright 개발자 도구의 Network 탭에서 사용자가 직접 화면을 열고 XLSX 다운로드 버튼을 누르는 1회 관찰로 요청 method, endpoint, query/form parameters, referer, response content-type, 파일 서명을 기록한다. 자동 요청·반복 호출은 하지 않는다.
