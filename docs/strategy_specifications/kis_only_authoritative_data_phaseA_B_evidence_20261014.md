# KIS 단일 기준 데이터 — Phase A/B 증거 보고서
- 조사일: 2026-10-14 KST
- 브랜치: Project200
- 로컬 HEAD / 원격 origin/Project200: 7eb9945e29774fb61fd2d07801762871b2506b98 (일치)
- 상태: Phase A 자동 인벤토리 PASS, 전략별 종단 추적 미완료; Phase B 부분 PASS / 전체 BLOCKED
- 안전: KIS VTS 읽기 전용 요청만 수행. 주문 endpoint 호출, 전략/런타임 코드 변경, commit/push 없음.

## 증거 파일
- verification/evidence/kis_dependency_inventory_20261014.json 및 .csv: 파일별 KRX/KIS/expiry/calendar/crosswalk/fallback/REST-WS/provenance/strategy 검색 결과
- verification/evidence/kis_api_capability_probe_20261014.json: REST 시세·호가 4건과 영업일 API 응답 원문, 수신시각, TR, SHA-256
- verification/evidence/fo_idx_code_mts_20261014.zip: KIS 공식 옵션 마스터 원본 ZIP
- docs/strategy_specifications/kis_only_authoritative_data_migration_plan_20261014.md: 계획
- 원본 마스터 URL: https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip
- 마스터 HTTP 200, 83,512 bytes, 7,713행, SHA-256 f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e

## Phase A — 의존성 인벤토리
자동 검색은 소스/설정/테스트/문서/verification을 대상으로 하고 raw data, .env, .git, 가상환경 및 생성 baseline은 제외했다.
- 참조 파일 560개. KRX 118파일/1,630라인, KIS 243/2,873, expiry 256/5,311, calendar 142/2,361, crosswalk 51/128, fallback 345/4,763, REST/WS 57/412, Strategy/Track 282/30,217, provenance 217/4,062.
- 원격 AGENTS.md에는 휴장일 우선순위 KRX 공식 데이터 → KIS API → KRX 연도별 캐시가 남아 있다. 로컬 AGENTS.md는 KIS 단일 기준으로 수정됐지만 commit/push 전이므로 원격은 아직 구 기준이다.
- application/composition/option_master_factory.py는 KISHolidayProvider와 KRXHolidayProvider를 FallbackHolidayProvider에 연결하고, infrastructure/kis/holiday_fallback_provider.py가 기존 KRX 우선/fallback 경계다.
- application/composition/futures_identity_source.py는 KIS futures identity와 KRX 상품 명세를 결합한다. infrastructure/kis/krx_kis_option_identity_resolver.py 및 contracts/krx_kis_identity_reconciliation.py는 KRX↔KIS 대조 경계다.
- core/option/option_master.py, infrastructure/kis/kis_index_option_master_source.py, contracts/option_expiry.py는 계약 identity/만기 경로의 핵심이다. application/composition/market_calendar_hub.py는 공통 달력 read model이나 주입된 provider 결과에 의존한다.
- application/composition/automated_virtual_runtime_factory.py에서 Track 2/3/4/5/6/7/8/9의 계약·Runtime Input·IV/Greeks·변동성·futures identity·Risk/Execution source가 각각 조립된다. Strategy 1~9 전체의 input→signal→Risk→OMS/Execution→Position/PnL→Control Tower 종단 추적은 미완료다.

## 마스터·identity 결함
- KIS 마스터 KOSPI200 유형별: 5=2,143, 6=2,143, D=1,108, E=1,108, L=124, M=124, N=113, O=113. 위클리 L/M/N/O는 총 474행이다.
- infrastructure/kis/kis_index_option_master_source.py는 유형 5/6만 선택해 위클리를 누락한다.
- core/option/option_master.py의 KIS 마스터 파서는 코드/이름에서 정확한 YYYYMMDD를 요구한다. 이번 7,713행 마스터를 읽기 전용 파싱한 결과 legacy_contracts=0, canonical identities=0, weekly identities=0이다. 원본 이름은 “C 202611 750.0”, “위클리C 2610W3 885.0”처럼 월/주차만 포함한다.
- KIS_INFO_TYPE_TO_OPTION_TYPE는 N/O를 콜/풋으로 매핑하지 않는다. 다운로드한 마스터에는 계약승수 필드가 없고 코드에는 250,000/50,000 상수가 있다. 공식 KIS 승수 출처는 미확인; KRX fallback으로 보완하지 말고 BLOCKED 또는 공식 명세 확인이 필요하다.
- REST 응답 futs_last_tr_date는 정확한 최종거래일을 제공하지만 현재 normalizer는 이를 canonical identity와 대조하지 않는다.

## Phase B — API capability matrix
| 기능 | 증거 | 판정/제한 |
|---|---|---|
| KIS master | HTTP 200, 7,713행, 원본 ZIP/hash 보존 | 다운로드 PASS, 현재 identity parser 통합 FAIL |
| 정확한 만기 | FHMIF10000000, 두 위클리 코드 | 표본 PASS: B09FGW942 → 20261015; BAFC2W942 → 20261019. canonical identity에 연결되지 않음 |
| REST 시세 | 두 코드 모두 HTTP 200, rt_cd=0, msg_cd=MCA00000 | 전송 PASS, 신선도 BLOCKED: 가격 응답에 날짜 포함 source timestamp 없음 |
| REST 호가 | 두 코드 모두 HTTP 200, rt_cd=0; 5단계 bid/ask·잔량 필드 | 전송 PASS, 신선도 BLOCKED: aspr_acpt_hour는 HHmmss뿐. 00:45 KST에 수신된 값 154500은 전일 장 종료 시각이므로 현재 시세로 취급 금지 |
| 국내휴장일 CTCA0903R | 기존 VTS 요청 HTTP 500 | BLOCKED. 같은 오류를 반복하지 않음 |
| 국내선물 영업일 HHMCM000002C0 | /uapi/domestic-stock/v1/quotations/market-time, HTTP 200, rt_cd=0 | 응답 수신 PASS, 의미 검증 BLOCKED: today=20261014인데 date3=20261013, date4=20261014, date5=20261015. 연간 휴장일 목록도 없음 |
| WebSocket 옵션 체결 H0IOCNT0 | 2026-10-13 raw frame 1,234건, adapter에 실제 frame 입력 | 과거 표본 PASS. 샘플 ask=0.00; trade frame의 bid/ask는 전체 호가 대체재가 아님 |
| WebSocket 옵션 호가 H0IOASP0 | 2026-10-13 raw frame 0건, collector도 구독하지 않음 | BLOCKED. adapter가 TR을 지원한다는 사실은 실제 수신 증거가 아님 |
| WebSocket 선물/지수 | H0IFCNT0 166,860, H0UPCNT0 23,336; H0IFASP0 0 | 과거 표본 PASS, 선물 호가 미검증 |
| 계좌/증거금 | 이번 단계에서는 호출하지 않음 | UNVERIFIED; 계좌 민감정보 미조회 |
| REST 제한 | 2026-10-13 총 13,916요청 중 HTTP200/rt_cd=0 13,658, HTTP500/EGW00201 258 | FAIL/원인 분석 필요. 프로세스별 1초 제한만으로 앱키 전체의 합산 제한을 보장하지 못할 수 있음 |

### 실증 세부사항
- B09FGW942 목요일 위클리: price HTTP 200/rt_cd=0, futs_last_tr_date=20261015, SHA-256 83ba65456b25619a918653cb87cf1870a205ed27e9b5a409beed76fa44c8a6f4
- BAFC2W942 월요일 위클리: price HTTP 200/rt_cd=0, futs_last_tr_date=20261019, SHA-256 b5ec8ee1c8cbe85d574707b75546ebd4d600012fd64fc63484ba40033b4b0723
- raw 응답과 수신시각은 JSON 증거 파일에 저장했다. 토큰/AppKey/AppSecret은 저장하지 않았다.
- 2026-10-13 WebSocket raw: H0IOCNT0 1,234, H0IFCNT0 166,860, H0UPCNT0 23,336, H0IOASP0 0, H0IFASP0 0.
- 현재 collector는 옵션 H0IOCNT0 체결만 구독한다. 구독 29개, 세션 제한 41개이며 옵션 26개에 호가를 단순 추가하면 총 55개로 제한 초과다. 2026-10-14 00:43 KST에는 collector가 실행 중이지만 당일 raw frame은 없었고, 중복 WebSocket 세션을 시작하지 않았다.

## Canonical model / provenance
- contracts/types.py에는 MarketObservation, MarketDataProvenance, RawMarketDataReference, DataQuality가 있다.
- REST transport는 raw response/hash, TR, request_started_at, response_received_at, HTTP status, rt_cd/msg_cd/msg1을 보존하고 collector는 canonical observation에 raw reference를 연결한다.
- 그러나 REST normalizer는 observed_at=None, 날짜 없는 source time만 사용하고 canonical provenance에 master snapshot version/hash와 validation result가 연결되지 않는다.
- 실제 REST Greeks 필드는 gama, theta, vega, delta_val, hts_ints_vltl 등인데 normalizer는 gamma_val/theta_val/vega_val을 찾아 gamma/theta/vega가 누락될 수 있다.
- WebSocket normalizer는 H0IOCNT0만 처리하고 observed_at은 수신 시각, source timestamp는 HHmmss만 남긴다. 모든 전략 입력에서 freshness/version/validation을 공통 보장하는 상태는 아니다.

## 차단 사항 및 다음 조사
1. HHMCM000002C0 date1~date5의 공식 의미와 VTS 지원 범위, 연간 달력 제공 경로를 검증한다. 검증 전 연간 거래일/휴장일은 BLOCKED.
2. KIS master code/type/strike와 REST futs_last_tr_date를 공통 identity로 연결하는 설계를 조사한다. KRX crosswalk/요일 추정은 사용하지 않는다.
3. D/E/L/M/N/O 상품 분류 및 계약승수의 공식 KIS 출처를 확인한다. 출처 미확인 계약은 BLOCKED.
4. 다음 거래 세션에서 승인된 안전한 방식으로 H0IOASP0 실제 frame을 확인한다. 현재 collector와 중복 연결하지 않는다.
5. REST/WS 공통 observation에 source timestamp, 수신 시각, schema/data version, master snapshot hash, validation result, stale reason을 연결하는 파일별 계획을 만든다.
6. Strategy 1~9 종단 추적, 다중 프로세스 합산 rate limit, 계좌/증거금 read-only API capability를 계속 조사한다.

## 변경·승인 상태
- 전략·런타임 코드·설정·주문 경로 수정 없음. 주문 API 호출 없음.
- git diff --check PASS. 전체 Python 테스트는 실행하지 않았다.
- 로컬 AGENTS.md/계획 문서는 이전 단계에서 수정됐고 원격에 push하지 않았다. 원격 AGENTS.md에는 KRX 우선 정책이 남아 있다.
- Shrimp Resume Context는 갱신하지 않았다. 확인 가능한 Shrimp 전용 MCP/CLI를 찾지 못했다.
- 이 보고서는 조사 결과이며 구현 승인 명세가 아니다. 구현과 데이터/아키텍처 변경의 commit/push는 별도 승인 전까지 보류한다.


## Phase A 추가 추적 — 공통 실행 경로 (2026-10-14)
- core/strategy/standard_registry.py에 Track1TailDefense, Track2AsymmetricTrap, Track3StatisticalArbitrage, Track4GammaScalping, Track5GapDivergence, Track6DailyTailInsurance, Track7VolatilitySkewWeeklyInsurance, Track8MacroRegimeMonthlyStrangle, Track9EventOvernightInsurance 9개가 등록되어 있다.
- application/composition/automated_virtual_trading_loop.py의 on_tick은 MarketState를 만들고 context_builder → strategy_hub.run → RuntimeStrategyResultCollectionAdapter → DecisionArbiter → RiskGate/RiskEngine → StandardOrderRouter/OrderStateMachine/VirtualBroker ACK adapter 경로로 흐른다. 다중 레그는 VirtualMultiLegExecutionBridge와 VSSF runtime으로 전달되고 execution result callback이 StrategyHub로 돌아온다.
- application/composition/automated_virtual_runtime_factory.py의 context_builder는 StandardRuntimeInputProvider.build(tick, state, account)를 호출한다. 이 provider는 단일 snapshot 하나만 읽는 대신 OptionMaster/expiry, Track2 IV, Track3 runtime input, Track4 Greeks, Track6 volatility, Track7 support/resistance/order timeout, KIS daily data, basis, market metrics, volume profile, option orderbook, Track9 event/ATM IV, calendar, account/margin/risk status를 개별 source로 조립한다.
- contracts/types.py의 CanonicalMarketTick/MarketState/DataQuality는 공통 시장 입력 모델로 쓰이지만, REST/WS가 생성하는 MarketObservation은 별도 DTO이며 그 필드·provenance가 모든 StrategyContext 입력까지 연속적으로 전달되는지는 확인되지 않았다. Historical replay에는 environments/virtual/market/canonical.py의 ReferenceCanonicalMarketTick에서 contracts.types.CanonicalMarketTick로 투영하는 별도 adapter가 있다.
- 따라서 9개 전략이 동일 registry/loop를 통과한다는 것은 확인했으나, 각 전략의 모든 필수 feature/source와 개별 RuntimeDataStatus가 동일한 KIS snapshot/version을 공유하는지는 아직 미검증이다. 이를 위해 strategy manifest의 required_sources/required_analytics와 StandardRuntimeInputProvider의 실제 매핑을 Track별로 연결한 추적표가 추가로 필요하다.
