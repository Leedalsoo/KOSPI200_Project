# KIS 단일 기준 데이터 아키텍처 전수검토·수정 계획 (초안)

- 작성일: 2026-10-14
- 프로젝트: Project200 / PHASE J
- 상태: 계획 초안 — 구현 전 검토·승인 필요
- 작업 원칙: 현재 working tree의 수정/미추적 파일을 덮어쓰거나 정리하지 않는다. 사용자가 2026-10-14에 명시적으로 확정한 KIS 단일 기준 데이터 정책 범위에 한해 AGENTS.md의 충돌 문구를 갱신한다. 전략 로직·위험한도·주문 설정은 변경하지 않는다. KIS VTS 읽기 전용 조회만 사용하고 주문 API는 호출하지 않는다.

## 1. 목표와 범위

목표는 KRX 데이터를 런타임의 필수 기준 또는 KIS와의 코드 대조 기준으로 사용하는 현재 경로를 전수 조사하고, 자동투자에 필요한 기준 데이터·시세·달력·계약 identity를 KIS 공식 API/종목 마스터에서 취득하도록 일관된 단일 데이터 공급 경계로 정리하는 것이다.

대상 범위:
- KIS 인증, VTS/Live 환경 분리, 토큰 및 WebSocket 승인키
- KIS 종목 마스터 다운로드·파싱·갱신·신선도·캐시
- KOSPI200 및 미니 KOSPI200 옵션/선물, 월물·월요일 위클리·목요일 위클리 종목 분류
- 계약 identity: broker short code, standard code, 상품 유형, 콜/풋, 행사가, 정확한 최종거래일, 계약승수
- 휴장일·영업일·세션 경계·거래일 판정
- REST 시세·호가·이력과 WebSocket 체결·호가·연결 상태·구독 한도
- Strategy 1~9 및 공통 Analytics/Runtime Input, Calendar, Option Master, IV/Greeks, 계약선택, 신호, Risk, OMS, Virtual/Paper/Live adapter, Execution, Position/PnL, Control Tower read model
- 과거/합성/리플레이 데이터, fixture, verification 스크립트와 테스트
- 운영 문서, 데이터 레지스트리, source-priority 문서, 오래된 KRX 의존성 문서

제외:
- 이번 계획 단계에서는 코드·전략·설정 변경을 하지 않는다.
- KIS API로 확보되지 않는 값을 추정하거나 주간 만기 규칙만으로 실만기일을 생성하지 않는다.
- 주문/정정/취소 API 호출, Live 주문, commit/push는 하지 않는다.
- 데이터 보존을 위해 기존 파일·원시 기록·검증 산출물을 삭제하지 않는다.

## 2. 단일 데이터 원칙(목표안)

1. **KIS는 런타임의 유일한 외부 브로커 데이터 기준**이다. KRX 엑셀, KRX 웹/API, KRX 코드 대조표를 런타임 필수 의존성으로 사용하지 않는다.
2. **KIS 원본과 내부 표준 모델을 분리**한다. 모든 KIS 응답은 adapter에서 검증·정규화한 뒤 공통 계약으로 전달한다. 전략별 코드에서 KIS 응답 필드나 KRX 규칙을 직접 파싱하지 않는다.
3. **KIS 내부에서도 출처별 기능을 구분**한다: 종목 마스터는 코드/상품 속성의 기준, 해당 종목의 REST 응답은 API가 제공하는 경우 정확한 최종거래일·시세·호가의 기준, 거래일 API는 지원 범위 내 영업일 정보의 기준, WebSocket은 장중 실시간 이벤트의 기준이다. 한 API의 응답을 다른 API가 제공하지 않는 필드의 증거로 간주하지 않는다.
4. 원본 응답·API 이름/TR ID·VTS/Live 환경·수신시각·원본 시각·마스터 버전/hash·검증 상태를 provenance로 남긴다. 비밀키·토큰은 기록하지 않는다.
5. 정확한 expiry, 상품 구분, 행사가, 옵션 종류, 계약승수, 종목코드가 빠졌거나 상충/오래되면 해당 계약만 `UNAVAILABLE/BLOCKED` 처리한다. 다른 주차의 코드, 종목명, 행사가, 요일 패턴으로 추정해 연결하지 않는다.
6. KIS API가 필요한 필드를 제공하지 않는 것으로 확인되면 코드 변경으로 감추지 않고 명확한 BLOCKED 항목과 공식 KIS 보완 경로/제약을 보고한다. 완전한 자동화의 필수 요건이 충족되지 않으면 운영 가능 판정을 내리지 않는다.
7. KIS 모의계좌와 Live 인증정보·호스트·토큰 캐시·WebSocket 세션은 분리한다. 모의 데이터는 Live 검증 증거로 간주하지 않는다.

## 3. 현재 확인된 초기 증거

- KIS VTS OAuth 토큰 발급과 KOSPI200 지수 REST 조회는 성공했다.
- KIS 옵션 마스터에서 위클리 유형 레코드가 발견되었고, 월요일/목요일 위클리 예시 종목의 시세 및 호가 REST 요청이 성공했다.
- 현재 `infrastructure/kis/kis_index_option_master_source.py`는 옵션 유형을 제한적으로 필터링하여 일부 위클리 유형을 제외하는 것으로 확인됐다.
- 현재 `infrastructure/krx/krx_option_expiry_master.py`, `contracts/krx_kis_identity_reconciliation.py`, `infrastructure/kis/krx_kis_option_identity_resolver.py`, `infrastructure/kis/holiday_fallback_provider.py` 등 KRX 기반·교차 대조 경계가 존재한다.
- KIS VTS 휴장일 요청은 테스트에서 HTTP 500으로 실패했다. 이는 현재 호출 경로가 실패했다는 뜻이며, KIS의 다른 공식 거래일 API/요청 형식도 모두 실패한다는 결론은 아니다.
- 실제 모든 전략·런타임 경로를 KIS 단일 기준으로 검증한 상태는 아니다.
- 현재 working tree에는 이 계획과 별개인 다수의 수정/미추적 파일이 이미 존재한다. 해당 파일은 본 작업에서 정리·복원·덮어쓰기하지 않는다.

## 4. 단계별 계획

### Phase A — 현 상태 동결 및 전체 의존성 목록 작성

- 시작 시점의 branch/HEAD/status와 기존 diff/untracked 목록을 별도 증거로 저장한다. 기존 변경 파일은 소유/범위를 추정하지 않고 보존한다.
- 모든 실행 코드·설정·테스트·문서에서 KRX, 날짜/휴장일/만기일, 종목코드 매핑, fallback, 하드코딩된 월물/위클리 규칙을 검색한다.
- 각 발견을 `런타임 필수`, `검증/대조 전용`, `과거 기록/문서`, `합성·fixture 전용`, `미사용/폐기 후보`로 분류한다.
- 전략 1~9 각각에 대해 입력 → 계약 선택 → 신호 → Risk → OMS/Execution → Position/PnL 경로와 참조 데이터 source를 추적표로 연결한다.
- 산출물: 파일/심볼 단위 의존성 인벤토리, 호출 그래프, 영향도/위험 등급. 이 단계에서는 구현하지 않는다.

### Phase B — KIS API capability matrix 및 읽기 전용 실증

필요 데이터별로 공식 API 문서, TR ID, 요청 필드, 응답 필드, VTS 지원, 호출 제한, pagination/연속조회, 갱신주기, 실패 의미를 표로 만든다.

필수 확인 항목:
- 종목 마스터: 모든 필요한 표준/미니 선물·옵션 유형과 월물/월요일/목요일 위클리 포함 여부, 코드 필드, 이름/행사가/상품 구분 필드, 업데이트 시각
- 정확한 만기일: KIS가 제공하는 공식 필드/API의 실재 여부와 주차별 실응답 검증
- 휴장일/영업일: 기존 휴장일 API 및 국내선물 영업일 API의 정확한 요청·응답, VTS 지원 여부, 연도 범위
- 시세/호가: 대표 월물/월요일 위클리/목요일 위클리의 REST 가격·호가 응답과 코드 연속성
- 실시간: WebSocket 체결/호가 TR, 구독 제한, 구독/해제, heartbeat, 재연결, 메시지 파싱, 실제 frame 수신
- 계좌·증거금·주문가능 조회 등 전략 Risk에 필요한 정보. 읽기 전용 API만 호출한다.
- API가 직접 제공하지 않는 지표(예: IV/Greeks)는 KIS 원본 시세와 검증된 수학 계산으로 산출 가능한지 분류하고, 파생 계산임을 provenance로 표시한다.

산출물: `KIS API capability matrix`와 각 기능별 PASS/FAIL/BLOCKED 증거. 실제 요청을 하지 않은 기능을 PASS로 표시하지 않는다.

### Phase C — 단일 Canonical KIS Data Boundary 설계

- KIS adapter 계층만 외부 KIS 형식과 통신한다.
- 공통 `InstrumentMasterSnapshot`, `OptionInstrumentIdentity`, `TradingCalendarSnapshot`, `Quote`, `OrderBook`, `Trade`, `Account/Risk Observation` 등 내부 계약을 정의/점검한다.
- 모든 날짜는 내부에서 `YYYYMMDD`로 정규화하되, 원본 값과 파싱 상태를 보존한다.
- 상품 유형을 문자열명이나 행사가만으로 판단하지 않고 마스터의 유형 코드/문서화된 필드로 분류한다.
- KIS short code와 standard code는 서로 다른 필드로 유지하고, API별 요구 코드가 검증되기 전에는 서로 대체하지 않는다.
- 마스터 새로고침 시각·hash·age·필수 유형별 count·중복/누락 검사·원자적 교체를 공통화한다.
- API별 rate limit, backoff, retry budget, timeout, circuit breaker와 fail-closed 상태를 한곳에서 관리한다.
- KRX fallback/교차 대조는 런타임 경로에서 제거할 후보로 분리하되, 역사 자료·검증 리포트·보존 fixture는 지우지 않는다.

### Phase D — Calendar/Expiry/Identity 경로 통합

- `MarketCalendarHub`, `TradingCalendar`, `HolidayProvider`, `OptionMaster`, expiry source, identity resolver와 factory/composition 연결을 조사해 단일 source 정책으로 통합한다.
- 거래일/휴장일, 세션 시간, 마지막 거래일/만기일은 서로 다른 개념으로 보존한다. 결제일을 최종거래일로 쓰지 않는다.
- 정확한 만기일이 KIS에서 확인되지 않은 계약은 요일/월물 규칙으로 생성하지 않고 차단한다.
- 주간 옵션과 월물 옵션이 같은 달에 있어도 exact expiry + 상품유형 + 콜/풋 + 행사가 + KIS 코드가 유지되도록 한다.
- 캐시는 KIS 응답의 복구 수단일 뿐 새로운 권위 출처가 아니다. 신선도 기준 초과/오염/환경 불일치 시 관련 계약을 차단한다.

### Phase E — 전체 전략 및 공통 코드 전수검토

전략 1~9를 개별 수정하지 않고 공통 데이터 경계를 먼저 통일한 다음, 각 전략의 소비 경로를 추적한다.

- Track 1~9 Runtime Input/Analytics source
- 전략별 Option/Futures Contract Source 및 expiry selection
- IV/Greeks/변동성·가격 지표/이벤트 materializer
- 공통 Calendar flags, DTE, expiry cutoff, 세션 종료 처리
- signal adapters, strategy state machine, Risk guards, OMS/Order Router
- virtual broker/exchange, VTS adapters, execution recovery, positions, PnL, provenance
- Control Tower read model/API와 운영 화면에 표시되는 코드·만기·데이터 상태
- high-speed replay, historical observations, synthetic data, fixtures, verification scripts

전략별 추적표에는 입력 source, 사용 필드, canonical key, 누락 처리, 관련 테스트, 결과를 명시한다. 승인된 새 전략 명세가 없는 경우 전략 진입/청산 규칙은 변경하지 않고, 데이터 공급 경계 변경만 수행한다.

### Phase F — 수집기/운영 자동화 통합

- 장 시작 전 KIS 마스터 자동 갱신, 필수 상품군/만기/코드 검증, snapshot/version 저장
- 휴장일/영업일 조회 및 연간 범위 검증
- 장중 필요한 종목만 WebSocket으로 구독하고 REST는 보완·검증/복구에 사용
- 구독 제한에 따른 종목 선정·순환 정책은 전략 요구사항과 우선순위에 따라 별도 설계하고, 모든 종목의 동시 실시간 수신을 보장한다고 가정하지 않는다.
- stale master, auth failure, REST/WS 불일치, 끊김, 메시지 누락, 시간 역전, 잘못된 expiry/code 시 자동 차단·알림·재시도 상태를 명시한다.
- 백업 복사본과 복구 절차를 만들되 기존 데이터는 삭제하지 않는다.

### Phase G — 테스트 및 증거 검증

1. 단위 테스트: 모든 마스터 유형, 날짜 파싱, exact expiry, calendar, 코드 분류, freshness, 중복/누락, API 오류
2. 계약 테스트: KIS 원본 → canonical model → 전략 입력까지 필드·provenance 연속성
3. 전략별 회귀: Strategy 1~9 입력/신호/상태전이/Risk/OMS/Position/PnL. 전략 규칙이 의도치 않게 바뀌지 않았는지 비교
4. VTS 읽기 전용 통합 테스트: 월물·월요일 위클리·목요일 위클리의 실제 REST quote/orderbook 및 WebSocket frame
5. 휴장일/만기일 경계 테스트: 휴장일, 연휴, 만기일, 만기 직전/직후, 세션 종료, 누락/오래된 데이터
6. 장애 테스트: 토큰 만료, HTTP 429/500, API 지연, WebSocket 끊김, 마스터 갱신 실패, 캐시 오래됨, 잘못된 코드
7. 전체 테스트 스위트와 compile/lint, `git diff --check`
8. E2E provenance: KIS source → runtime → strategy → risk → virtual execution → position/PnL → Control Tower. 주문 endpoint는 호출하지 않는다.

PASS 기준은 각 필수 데이터 항목에 실제 응답 증거가 있고, Strategy 1~9의 입력 경로가 동일 canonical snapshot을 사용하며, 누락/오래된 정보에서 주문 경로가 차단되는 것이다. 테스트 파일의 존재나 과거 PASS 기록만으로 PASS를 선언하지 않는다.

### Phase H — 문서·정책·기록 정합성

- 전략 코드·런타임 설정은 수정하지 않았다. AGENTS.md는 사용자가 명시한 KIS 단일 기준 정책에 맞춰 source-priority, calendar source, synthetic initial spot source 및 provenance/fail-closed 규칙만 갱신했다.
- 사용자는 2026-10-14에 KIS 단일 기준 정책을 직접 지시하고, REST/WebSocket 실제 응답, Strategy 1~9 공통 canonical model, fail-closed, provenance 보존을 명시했다. 이에 따라 AGENTS.md의 충돌 정책 문구만 해당 범위에서 갱신한다. 구현 코드는 Phase A/B 증거 검토와 파일별 영향 보고 후 별도 범위 승인 전까지 수정하지 않는다.
- 과거 조사/결정/실패 기록은 삭제하지 않는다. 현재 유효하지 않게 되는 확정 Decision Log는 사용자 확인 후 상태 변경과 근거를 남긴다.
- 최종 보고서에는 변경 파일, 삭제하지 않고 유지한 역사 자료, 테스트 증거, 남은 API 제한, BLOCKED 항목을 기록한다.

## 5. 필수 완료 기준(Definition of Done)

- [ ] 실행 코드·설정·테스트·문서에 대한 KRX/KIS 의존성 인벤토리 완료
- [ ] KIS API capability matrix의 모든 필수 데이터 항목에 실증 결과 존재
- [ ] KIS 마스터에서 필요한 모든 KOSPI200/미니 KOSPI200 월물·월요일/목요일 위클리 유형 식별
- [ ] 필요한 계약의 정확한 만기일을 KIS 공식 응답으로 확보하거나, 확보 불가 계약이 명확히 BLOCKED
- [ ] 휴장일/영업일 API가 성공하고 실제 반환값의 의미가 검증됨
- [ ] REST와 WebSocket의 코드·상품 identity가 일치하고 실제 frame이 관찰됨
- [ ] Strategy 1~9 전체 데이터 소비 경로가 동일 canonical KIS boundary 사용
- [ ] 코드/날짜/만기/달력 관련 KRX 비교가 런타임 필수 의존성에서 제거됨
- [ ] 전체 테스트와 전략별 회귀 및 VTS E2E 증거 완료
- [ ] fail-closed, 신선도 차단, provenance 및 오류 복구 검증 완료
- [ ] 변경 문서/Decision Log/Q&A와 실제 코드 상태 일치
- [ ] 사용자의 별도 승인 전 commit/push 및 Live 주문 없음

## 6. 위험 및 선행 확인

- 현재 작업폴더에 기존 수정/미추적 파일이 다수 존재하므로 변경 전 기준 스냅샷과 파일 소유 범위를 확인해야 한다.
- KIS VTS 휴장일 API HTTP 500은 요청 파라미터/TR ID/엔드포인트 또는 VTS 지원 범위를 조사해야 한다. 재시도만 반복하지 않는다.
- WebSocket 구독 한도 때문에 모든 행사가의 호가/체결을 동시에 구독할 수 없을 수 있다. 전략의 실제 필요 데이터와 종목 순환 정책을 먼저 정의해야 한다.
- KIS가 직접 제공하지 않는 휴장일/정확한 만기 정보가 발견되면 KRX로 몰래 fallback하지 않는다. 대안과 자동화 가능성에 대한 차단 보고를 하고 결정한다.
- 실시간/계좌 API 권한, 모의계좌 데이터와 Live 환경 차이, rate limits, API 약관을 테스트 결과와 별도로 기록한다.

## 7. 이 계획 단계의 상태

- 계획 문서 작성만 수행한다.
- Phase A 자동 인벤토리와 핵심 공통 실행 경로 조사, Phase B 일부 KIS VTS API 실증을 수행했다. 상세 결과는 docs/strategy_specifications/kis_only_authoritative_data_phaseA_B_evidence_20261014.md에 기록했다. Strategy 1~9별 필수 source 종단 추적과 달력/실시간 호가 검증은 미완료다.
- 읽기 전용 KIS VTS API 실증과 실제 raw WebSocket frame의 parser 확인을 수행했다. 전체 Python 테스트 스위트는 실행하지 않았다.
- commit/push와 Live/모의 주문은 수행하지 않는다.
- 다음 단계는 Track 1~9의 required_sources/required_analytics를 StandardRuntimeInputProvider와 연결한 추적표를 완성하고, 달력 의미 및 H0IOASP0 실시간 호가를 안전하게 검증하는 것이다. 전체 결과 보고와 별도 사용자 승인 전에는 런타임 구현·commit/push를 진행하지 않는다.


## 8. Phase A/B 조사 결과 업데이트 (2026-10-14)
- 증거 보고서: docs/strategy_specifications/kis_only_authoritative_data_phaseA_B_evidence_20261014.md
- 자동 인벤토리: 560개 파일에서 KRX/KIS/expiry/calendar/crosswalk/fallback/REST-WebSocket/provenance/Strategy 참조를 분류·집계했다. 전략 1~9 종단 추적은 계속 필요하다.
- KIS 마스터 HTTP 200, 7,713행, SHA-256 f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e. 위클리 L/M/N/O 474행을 확인했으나 현 loader의 5/6 제한과 core parser의 exact YYYYMMDD 조건 때문에 canonical identities는 0이었다.
- VTS REST price/orderbook 4건 PASS: B09FGW942 futs_last_tr_date=20261015, BAFC2W942=20261019. 원문/수신시각/hash는 verification/evidence/kis_api_capability_probe_20261014.json에 보존했다.
- HHMCM000002C0는 HTTP 200/rt_cd=0이나 date3=20261013, today/date4=20261014로 의미 검증이 필요하다. CTCA0903R의 과거 VTS HTTP 500은 재시도하지 않았다. 연간 달력은 BLOCKED.
- WebSocket H0IOCNT0 1,234건은 확인했지만 H0IOASP0 0건이며 현 collector가 구독하지 않는다. 29개 구독에 호가를 단순 추가하면 41개 제한을 넘을 수 있다.
- REST freshness/source timestamp, Greeks 필드 매핑, canonical provenance의 data/master version·validation 연결에 결함이 확인됐다.
- Phase A 자동 인벤토리 PASS, 전략별 종단 추적 미완료. Phase B 부분 PASS, 달력·실시간 호가·승수·freshness·계좌/증거금은 BLOCKED 또는 미검증. 전체 KIS-only 전환은 미완료.
- 코드/전략/런타임 설정/주문 경로는 수정하지 않았다. git diff --check PASS. Commit/push 없음.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — 지시서 E 구현 진행 메모

- KIS 공식 마스터 원본: 7,713 raw rows, SHA-256 `f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e`; 기존 검증 다운로드를 `data/reference/kis/index_master/`에 append-only cache로 이관했다. 현재 KST 날짜 snapshot을 재사용하며, KST 날짜별 최대 1회 refresh와 24시간 TTL을 코드화했다.
- KOSPI200 option type codes 5/6/D/E/L/M/N/O: 6,976 contracts; L/M/N/O weekly: 474. 원본 전체의 넓은 option-like count 7,058은 다른 underlying의 P/Q/R/S weekly types 82개를 포함하므로 KOSPI200 option count와 혼용하지 않는다.
- Exact expiry generalized read-only VTS probe: monthly 202611 5/5, 202612 5/5, 202701 5/5; Thursday weekly 5/5; Monday weekly 3/5 (2 HTTP 500 / EGW00201). Failed contracts were not retried; successful 23 responses were imported to append-only expiry cache without further network requests.
- KIS master parser now recognizes monthly, mini-monthly, Thursday weekly and Monday weekly only when type code and ASCII C/P + expiry-label patterns agree. Unknown/mismatched labels are excluded.
- Multiplier is still BLOCKED/UNSET: the observed master row has no multiplier field and no KIS-authoritative multiplier field was verified.
- Holiday calendar is BLOCKED: VTS CTCA0903R HTTP 500 is historical evidence; the response body was not preserved in the available probe record, and a concurrent REST collector is running. No additional API call was made to avoid adding rate-limit pressure. KIS annual coverage is now required; otherwise only an explicitly user-approved, hash-verified holiday file can be used.

 
## Directive F execution addendum (2026-10-14)

Status: PARTIAL PASS / overall BLOCKED; this addendum supplements the prior E evidence without deleting it. Directive E is superseded by Directive F for remaining work; the historical E record is retained.

### Actual master -> exact-expiry identity join
- Offline input: verification/evidence/fo_idx_code_mts_20261014.zip; SHA-256 f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e.
- Cached exact-expiry records reused: 23; network calls during this join: 0.
- Identity result: 23 identities = MONTHLY 15, THURSDAY_WEEKLY 5, MONDAY_WEEKLY 3; 8 weekly identities total. All 23 cached symbols resolved.
- Cross-check: all 15 monthly samples match second-Thursday candidates; all 8 weekly samples match their weekday occurrence labels; no sample mismatch. Holiday-shift behavior remains NOT TESTED.
- Type code mapping status remains PARTIAL: KIS master row code/name correlation is present, but an independent official type-code dictionary was not found. Parser must reject unknown/mismatched labels. Mini-option exact-expiry sample and authoritative multiplier remain UNSET.
- Evidence: verification/evidence/kis_master_identity_join_20261014.json; verification/evidence/kis_expiry_crosscheck_20261014.json; draft mapping table docs/strategy_specifications/kis_type_code_mapping_evidence_draft_20261014.md.

### Holiday / D-4 / DTE10
- One VTS read-only CTCA0903R request: HTTP 500, rt_cd=1, msg_cd=EGW02006. msg1 decoding was not legible in the saved UTF-8 interpretation; no retry was made. The probe response hash is preserved in verification/evidence/kis_holiday_single_probe_20261014.json. Official portal lists domestic holiday lookup, but VTS support/annual coverage is not proven.
- HHMCM000002C0 date-field meanings remain unverified; do not treat it as an annual calendar.
- Draft files: data/reference/calendar/holidays_2026_draft.json (17 dates) and holidays_2027_draft.json (16 dates). Their date-list SHA-256 values are recorded in each file. Source was KRX cache for draft input only; all reasons are marked unverified, approval_state is DRAFT_USER_REVIEW_REQUIRED, runtime_eligible=false.
- trading_day_boundary_table_v4.md was created and v3 preserved. Monthly dates with cached exact expiry: 2026-11-12, 2026-12-10, 2027-01-14. All other monthly rows and unqueried future weekly rows remain UNSET. D-4 and DTE10 candidate dates use an unapproved draft calendar only; not runtime eligible.
- Added D-4 exit-due utility: before 11:00 KST on D-4 returns false; at/after 11:00 KST returns true; timezone-naive input is rejected.

### Subscription planner
- Added infrastructure/kis/kis_subscription_planner.py as a pure planner; it does not connect to or modify the collector.
- User-defined hard cap: 41 registrations. Public official docs reviewed did not confirm whether the scope is per session/AppKey; use conservative per-session count of each (TR_ID, symbol) and do not open a second session. With index + option trade/book, maximum is 20 option contracts; with one mini-futures trade/book contract, maximum is 19 options.
- Existing collector construction remains 26 monthly option trade + standard futures trade + mini futures trade + index = 29; it has 0 option-book, 0 futures-book and 0 weekly option registrations. Proposed removals: standard futures until S3 spread design is approved; mini futures for entry until S3/S4 enabled. S5's current mini-futures dependency conflicts with this scope and is BLOCKED pending a newly approved specification.
- Dry-run evidence: verification/evidence/kis_subscription_plan_dry_run_v2_20261014.json. Counts: S5 window 5; weekly S6/S7 fixture 17; multi-strategy peak fixture 37 with S7 BLOCKED for capacity. Scenarios use real cached identities as capacity fixtures, not live ATM selection. Operational calendar remains blocked.
- Rotation plan is unsubscribe -> wait for unsubscribe acknowledgement -> subscribe. min hold, ATM hysteresis and max_quote_age remain UNSET; automatic rotation disabled. Collector changes/application not performed.

### Greeks and account capability
- Normalizer now reads KIS original keys gama/theta/vega into canonical gamma/theta/vega. REST source timestamp remains unavailable as full date-time; observed_at remains None and freshness BLOCKED.
- Config-only check printed no values: KIS_MODE=VTS, VTS app key/secret present, account number has 8-digit shape and starts with 6, product code 03; no explicit VTS-specific account-number key. KIS Developers states mock accounts starting with 6 are futures/options.
- One read-only balance request to VTFO6118R returned HTTP 200 / rt_cd=1 / msg_cd=90070000; account/user/appkey association could not be confirmed and msg1 was not legible in the saved text encoding. KIS Developers maps this code to mock account ID/user-information mismatch, often related to HTS ID change or live/mock account confusion. KIS Developers public FAQ maps 90070000 to a VTS mock account ID/user-information mismatch: https://apiportal.koreainvestment.com/. Response values and account number were not recorded. Orderable query was not attempted after balance failure. Daytime VTS margin TR could not be confirmed from official mock documentation and was not called. No retry.
- Existing 250000/50000 constants are not authoritative; multiplier/tick values remain UNSET pending source and user approval.

### Tests
- Full suite: 316 passed in 15.45s (final rerun after planner hardening).
- Focused Directive F tests: 46 passed in 0.49s.
- compileall: exit 0.
- git diff --check: exit 0; only LF/CRLF working-copy warnings.

### Safety boundary
- No order/modify/cancel API call; no Live order.
- No collector stop/restart or extra WebSocket session.
- No commit/push.
- No Decision Log or AGENTS.md change.
- No preserved/recovery file was deleted or edited; KRX caches and v2/v3 tables were retained.
- No credential values or account amounts were recorded.
### Correction note — WebSocket 41 scope
- The 41 hard ceiling is directly specified by the user. Public KIS portal pages reviewed did not conclusively document whether the limit is per session or AppKey, nor whether trade and quote are aggregated. Planner uses the conservative assumption: every (TR_ID, symbol) pair is one registration, total per single session <=41, and no second session is opened to bypass the limit.
- The earlier dry-run JSON field named official_websocket_limit was too strong. See verification/evidence/kis_subscription_plan_dry_run_v2_20261014.json for the corrected evidence record; the earlier JSON is preserved as historical evidence.

### Official master update cadence note
- KIS Developers public API docs state the official master file is updated at multiple intraday times (including 06:00, 06:55, 07:35, 07:55, 08:45, 09:46 and later updates): https://apiportal.koreainvestment.com/apiservice?keyword=ci%EC%BD%94%EB%93%9C. The project policy remains one pre-market download per KST date because that is the user-confirmed rule. This means intraday master revisions are not refreshed; exact identity mismatch or missing data must still fail closed.
