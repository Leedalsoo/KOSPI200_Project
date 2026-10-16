# KRX 위클리 옵션 코드 조인 및 OTP 다운로드 조사

- 작성일: 2026-10-13
- 상태: 읽기 전용 조사 결과 / 만기·전략 판정 기준으로 사용 금지
- 범위: 과거 KRX XLSX 2개와 로컬 fo_idx_code_mts.mst 스냅샷의 구조 및 후보 조인 키 분석
- 사용 목적: historical evidence와 데이터 공급 경계 조사. S7 구현 또는 만기 추정 근거가 아님.

## 1. 입력 증거와 재현 가능한 식별값

원본은 c989c0c 직전 Git tree (c989c0c^:tests/fixtures/krx/)에서 읽기 전용으로 추출했다. 대상:
data/reference/krx/_recovered_20260919/

| KRX XLSX | 데이터 행 | 대표 상품/주간 번호 | KRX 표준코드 예시 | 최종거래일(G열) |
|---|---:|---|---|---|
| data_2923_20260919.xlsx | 196 | KOSPI WEEKLY C 2609W4, 목요일 | KR4B09FE9375 | 2026-09-23 |
| data_2935_20260919.xlsx | 232 | KOSPI WEEKLY M C 2609W3, 월요일 | KR4BAFBY9227 | 2026-09-21 |

파일 해시(SHA-256):
- 2923: dee41a33f0d343145b0da4efbad0ae548798a9596f838b2c8ff4f08eed4b0e02
- 2935: 6096dadca2c100b47bd2b5ff4968e6617e167ef8dcdcaa71bd5beae8e1d8e463

두 파일 모두 XLSX ZIP 무결성 PASS, Windows read-only 속성 설정 확인. G열은 최종거래일, H열은 최종결제일; 이 파일들은 2026-09-19 과거 스냅샷이며 현행 만기 소스로 쓰면 안 된다.

## 2. 로컬 KIS 마스터에서 실제로 확인된 것

검사 파일: fo_idx_code_mts.mst
- 크기: 619,046 bytes
- SHA-256: c6cd3a4c33faeca578dfd0a07dad40b08318254827c78545fbe6b50fee83b253
- 파일의 공식 기준일/갱신시각은 확인되지 않음 (UNSET).

스냅샷 내 위클리 이름/코드 패턴을 가진 레코드 270개를 찾았다. 이 스냅샷의 주간 표시는 모두 2609W2였다. 예: KIS 단축코드 BAFBXW937, 표준코드 KR4BAFBX9376, 이름의 상품/행사가는 위클리M C 2609W2 937.5. 즉 로컬 KIS 파일에는 위클리 관련 레코드가 존재한다. 다만 기준일을 입증할 manifest가 없으므로 “2026-09-19 시점의 완전한 KIS 마스터”라고 단정할 수 없다.

## 3. 0건 일치의 원인 분석

### 직접 조인 결과

- KRX 표준코드 A열 ↔ KIS 표준코드 필드: 2923 0/196, 2935 0/232.
- KRX 단축코드 B열 ↔ KIS 단축코드 필드: 두 파일 모두 0건.
- 따라서 단순한 KRX 표준코드 = KIS stnd_iscd 조인만으로는 이 두 역사 스냅샷을 연결할 수 없다.

### 상품 계열과 주차 차이

- 2923은 일반 KOSPI WEEKLY 2609W4(목요일)이다. 로컬 KIS 위클리 레코드 270개는 모두 2609W2이며 이름에 위클리M이 있어 상품 계열도 다르다. 월·행사가·콜풋 같은 부분 속성만으로 조인하면 다른 상품 계열을 잘못 붙일 수 있다.
- 2935는 KOSPI WEEKLY M 2609W3(월요일)이다. 로컬 KIS 스냅샷은 같은 2609 월의 W2를 가지고 있어 주차가 다르다. 같은 월·콜풋·행사가만 비교하면 232행 중 224행이 후보로 겹치지만, 이들은 W3와 W2라는 다른 계약이므로 유효한 identity 조인이 아니다. 같은 월·주차·콜풋·행사가까지 요구하면 일치 0건이다.
- 같은 행사가 937.5에서도 주차에 따라 코드가 다르다: KRX W3는 BAFBY937 / KR4BAFBY9375, KIS W2는 BAFBXW937 / KR4BAFBX9376. 단축코드 형식도 동일하지 않다.

### 가능한 키와 안전한 결론

- 종목명은 사람이 비교할 보조 증거로 쓸 수 있지만, 월·주차·상품계열·콜풋·행사가를 보존해도 KRX와 KIS의 식별자 간 authoritative crosswalk가 입증된 것은 아니다.
- 월 + 주차 + 상품 계열 + 콜풋 + 행사가 는 후보 검색/진단용 복합 속성이지, 현재 증거만으로 확정 조인 키가 아니다. 만기일도 KRX 최종거래일과 KIS 계약 만기 정의를 교차 검증한 뒤에만 후보 검증에 사용한다.
- 해결에는 동일 기준일의 KRX와 KIS 마스터 원본 및 공식 코드 매핑/정의가 필요하다. 이를 확보하기 전에는 자동 name-based mapping을 만들지 않는다.

## 4. S7 월·목 위클리 exact 만기에 미치는 영향

- KRX XLSX 스냅샷은 과거 표본에서 월요일 2026-09-21, 목요일 2026-09-23이라는 정확한 최종거래일을 제공했다.
- KIS 로컬 스냅샷의 주간 계약은 2609W2만 확인되므로 월요일 W3와 목요일 W4를 식별하거나 exact 만기를 대체할 수 없다.
- 따라서 KIS 마스터만으로 S7의 월·목 위클리 exact YYYYMMDD 만기를 결정하는 경로는 BLOCKED다. 월요일/목요일 규칙이나 종목명으로 만기를 생성하지 않는다.
- 향후 실제 날짜의 KRX exact master가 없거나 KRX↔KIS contract identity를 입증할 수 없는 계약은 해당 계약만 UNAVAILABLE/BLOCKED 처리한다. 이는 전략 코드 변경 지시가 아니며, S7 로직은 이 조사에서 수정하지 않았다.

## 5. KRX OTP→XLS 다운로드 기술·정책 조사

### 확인된 휴장일 다운로드 형식

- 화면: KRX 정보데이터시스템 휴장일 조회
- 화면 URL: https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp
- OTP endpoint: http://marketdata.krx.co.kr/contents/COM/GenerateOTP.jspx (legacy reference scheme; HTTPS behavior not tested)
- 파라미터: name=fileDown, filetype=xls, url=MKD/01/0110/01100305/mkd01100305_01, search_bas_yy=YYYY, gridTp=KRX, pagePath=/contents/MKD/01/0110/01100305/MKD01100305.jsp
- 다운로드 endpoint: http://file.krx.co.kr/download.jspx (legacy reference scheme; HTTPS behavior not tested); form field code에 OTP를 POST한다.
- 휴장일 파라미터 참고자료: https://hayjo.tistory.com/71 (비공식 기술자료). 실제 HTTP 요청은 이번 조사에서 보내지 않았다.

### 계약 마스터의 화면명

프로젝트의 기존 KRX XLSX 검증/Q&A 기록은
- 현행 KRX Data Marketplace에서 확인되는 상위 메뉴 경로는 파생상품 > 종목정보 > 전종목 기본정보 (공식 메뉴: https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd)이다. 구형 번호별 화면과 현행 화면의 정확한 대응/필터 상태는 아직 검증되지 않았다. 0841 미니 KOSPI200 옵션, 0900 표준 KOSPI200 선물, 2801 KOSPI200 옵션 전종목 기본정보, 2836 미니 KOSPI200 선물, 2923 목요일 위클리 옵션, 2935 월요일 위클리 옵션으로 식별한다. 이들 각 화면의 현재 OTP url/pagePath 및 추가 query/form 필드는 브라우저 Network 캡처로 확인하지 않았다. 휴장일 파라미터를 계약 마스터에 전용하지 않는다.

### 약관과 호출 한도

- 공식 KRX Data Marketplace 홈페이지 이용약관 https://data.krx.co.kr/contents/MDC/INFO/informationController/MDCINFO003.cmd 제10조는 자동화 수단에 의한 무단 수집·복제·배포를 금지하고, 제12조는 사전 허락 없는 정보 복제·전송 등을 제한하며, 제12조의2는 별도 마켓데이터 이용약관 적용 가능성을 명시한다.
- 공개 약관에서 분당/일별 숫자 호출 제한은 확인되지 않았다. 호출 제한이 없다고 추정할 수 없고, OTP의 존재 자체가 자동 수집 허가를 의미하지 않는다. 이 약관은 현재 Data Marketplace의 공식 약관이며, 레거시 marketdata 다운로드 화면에 적용되는 별도 약관/허용 범위는 확인되지 않았다.
- 결론: 휴장일 OTP→XLS 다운로드는 기술적으로 구체화되어 있고, 일반적인 2단계 OTP→다운로드 패턴은 알려져 있다. 그러나 각 계약 마스터 화면의 파라미터와 자동 수집 허용 범위는 미확정이다. KRX에 공식 확인하기 전 실제 자동 요청·반복 호출·스케줄러는 만들지 않는다.

## 6. 승인된 데이터 운영 기본값

Registry 초안에 사용자가 승인한 정책을 반영했다:
- 휴장일: 연 1회 갱신 + 30일마다 확인.
- 종목 마스터: 매 거래일 장 시작 전 갱신, 최종 성공 갱신이 24시간을 초과하면 해당 계약 차단.
- 백업: 다른 폴더/클라우드에 독립 사본 1벌. 정확한 위치는 UNSET.
