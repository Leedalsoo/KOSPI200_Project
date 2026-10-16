# KIS 수집기 구조 정의서 v1

- 작성일: 2026-10-15 KST
- 상태: 설계 초안. 사용자 승인 전 코드·스케줄러 설정에 적용하지 않는다.
- 당일 데이터 판정: **이중 세션 의심**. 두 경로가 같은 거래일에 실행된 증거가 있으나, 호가 공백의 직접 원인이라고 확정하지 않는다.
- 안전 경계: KIS Live, 주문/계좌 API, 실제 WebSocket 구독/해제 요청, 시간 가드 우회, 두 번째 연결, 파일 삭제, 전체 테스트 스위트, Git stage/commit/push 금지.

## 1. 구성요소 표

표의 “목표”는 승인 후 목표 구조이며, “현재”는 2026-10-15에 관찰한 상태다. 제안된 작업 스케줄은 아직 만들거나 변경하지 않는다.

| 구성요소 | 단일 목적 | 실행 진입점(하나) | 스케줄 항목(하나) | 입력 | 출력 | TR/API | 한도·상태 |
|---|---|---|---|---|---|---|---|
| WebSocket 수집기 | 실시간 옵션 호가 및 지수 프레임 수신·원본 보존 | py -m scripts.kis_vts_websocket_collector | 기존 Project200-KIS-VTS-WebSocket-Collector 하나. 목표 전환 시 이 작업 하나만 WebSocket supervisor를 시작하게 하는 방안 검토 | KIS VTS 자격정보, 검증된 당일 구독 후보, 시간 가드 | data/kis_market_data_restart/YYYYMMDD/kis_vts_websocket_raw.jsonl, kis_vts_websocket_timing.jsonl, kis_vts_websocket_control_events.jsonl, kis_vts_subscription_events.jsonl, logs/websocket_collector.log | WS H0IOASP0 옵션 호가, H0UPCNT0/2001 지수 | 단일 세션 소유자. 전체 구독 41 이하. 기본 세트 26+1=27. ACK 스키마 미검증은 계속 fail-closed/관측 전용 |
| REST 관측기 | 승인된 계약 후보의 가격·호가 관측을 REST로 기록 | KISRestMarketObservationCollector를 구성하는 기존 _rest_collector_for_day() 경로; 최종 CLI 진입점은 구조 이관 시 단일화 | 제안: Project200-KIS-REST-Market-Observation 1개, 일일 기준데이터 성공 후에만 실행. 현재 스케줄은 만들지 않음 | 일일 기준데이터의 검증된 계약 ID, KIS VTS REST 인증 | data/kis_market_data_restart/YYYYMMDD/historical_market_observations.jsonl, rest_request_timing.jsonl, rest_blocked_diagnostics.jsonl, manifest.json | FHMIF10000000 가격, FHMIF10010000 호가; 기초자산 관측은 별도 FHPIF05030200 | REST 초당 최대 1건, 요청 간격 최소 1.25초로 계획, 재시도 금지, 호출 수 상한 필요. 현재 재개 여부는 사용자 결정 |
| 일일 기준데이터 루틴 | 공식 마스터 스냅샷과 계약 identity를 매일 검증해 후보 파일 생성 | 제안: py -m scripts.kis_daily_reference_data (아직 없음) | 제안: Project200-KIS-Daily-Reference-Data 1개, 08:20 KST | 공식 옵션 마스터, 거래일, 후보 심볼 | data/kis_market_data_restart/YYYYMMDD/reference/ 아래 마스터 원본/해시/검증 결과 및 append-only identity snapshot | 공식 마스터 다운로드, 후보별 REST 가격 검증은 승인된 범위에서만 수행 | 다운로드/형식/REST 검증 실패 시 해당 후보 BLOCKED. 어제 스냅샷을 오늘 값으로 대체 금지. 한 번의 REST 요청마다 최소 1.25초 간격 |
| Watchdog | WebSocket 수집기 프로세스 생존 감시와 단일 프로세스 복구 | 현재 scripts/run_kis_daily_watchdog.ps1; 목표는 이 파일의 역할을 WebSocket supervisor 하나로 명확히 제한 | 목표: WebSocket 작업과 중복되지 않는 단일 시작 경로. 권장안은 기존 WS 작업 하나가 supervisor를 실행하고 별도 로그인 Run 항목은 두지 않는 것 | 프로세스 상태, 시간 가드, 종료 코드 | data/kis_market_data_restart/logs/watchdog.log | KIS API/TR 호출 없음; WebSocket 직접 연결 금지 | 현재 HKCU Run 값은 비활성화됨. Watchdog는 소켓을 열거나 구독하지 않는다. 자동 재기동은 단일 인스턴스 잠금과 명확한 가드가 검증된 후에만 재허용 |
| 공통 유틸 | 경로, 시간, identity, manifest, raw 저장 등 재사용 기능 제공 | 라이브러리 import만; 독립 실행 진입점 없음 | 없음 — 독립 프로세스가 아니며 다른 구성요소에 의해 호출 | 호출자의 명시적 인자 | 호출자가 지정한 경로/반환값 | 자체 TR/API 없음 | 네트워크·소켓·스케줄러 동작 금지 |

### 단일 세션 원칙
1. WebSocket 세션을 여는 구성요소는 scripts/kis_vts_websocket_collector.py 하나뿐이다.
2. REST 관측기, 일일 기준데이터 루틴, Watchdog, 공통 유틸은 WebSocket을 열지 않는다.
3. Watchdog는 프로세스만 감시한다. 직접 구독/해제 요청이나 인증 키 발급을 수행하지 않는다.
4. 하나의 시작 경로와 하나의 감시 경로만 둔다. 같은 AppKey를 사용하는 별도 수집기/작업/로그인 자동시작 항목을 중복 활성화하지 않는다.
5. WebSocket 등록은 세션 내 총 41개를 넘지 않는다. 재중심화 시 해제 후 추가한다.
6. REST 호출은 초당 1건 이하, 후보 검증 요청 간 최소 1.25초, 자동 재시도 없음.
7. source timestamp 의미나 ACK 상관관계가 확인되지 않으면 추정하지 않는다. 수신시각을 원천시각으로 대체하지 않는다.

## 2. 현재 경로 및 미해결 의존성

- 새 WebSocket 진입점은 scripts/kis_vts_websocket_collector.py다.
- 기존 infrastructure/kis/kis_vts_weekday_collector.py는 WebSocket 실행부와 REST 일일 오케스트레이션이 함께 들어 있다.
- 직접 import하는 프로젝트 코드:
  - scripts/kis_vts_websocket_collector.py → market_data_root_from_env()
  - scripts/ingest_kis_vts_websocket_canonical.py → _kis_option_resolver_for_day()
  - verification/evidence/kis_vts_collector_calendar_daily_integration_20261014.py → authoritative_calendar_for_today()
- 기존 weekday 파일은 data/.../kis_vts_raw.jsonl에 기록하며 KISRealtimeCollector를 사용한다. 새 수집기는 data/.../kis_vts_websocket_raw.jsonl에 기록한다. 두 경로의 raw 파일은 별도지만 동일 AppKey에서 이중 WebSocket 세션이 열릴 수 있다는 운영 리스크가 있다.
- 기존 weekday 파일을 즉시 삭제하면 위 import 및 REST 일일 루틴이 깨질 수 있다. 이 정의서는 코드 이동/삭제를 승인하지 않는다.

## 3. 이관 계획 및 롤백

### 단계 A — 실행 경로 안정화
1. 기존 weekday Watchdog 자동시작은 J-2에서 비활성화했다. 원래 HKCU Run 값은 %TEMP%/Project200_J_20261015/HKCU_Run_Project200-KIS-Daily-Market-Collector_backup.json에 보관했다.
2. 옛 수집기 재기동 PID의 종료는 도구 안전 검사에 막혀 완료 검증되지 않았다. 따라서 단일 세션 상태는 NOT PROVEN이며, 실제 재시작/연결 확인을 하지 않는다.
3. 다음 작업은 읽기 전용 프로세스 확인을 통해 옛 경로가 사라졌는지 검증하는 것이다. 확인 전 새 연결은 금지한다.
4. 새 collector의 시간 가드는 우회하지 않는다. 장외 재시작만으로 연결/구독 요청이 전송됐다고 간주하지 않는다.

### 단계 B — 공통 코드 분리 설계
1. market_data_root_from_env()를 공통 경로 유틸 모듈로 이동하고 새 collector와 REST 루틴이 그 모듈을 import하도록 변경안을 만든다.
2. _kis_option_resolver_for_day()와 authoritative_calendar_for_today()는 사용처를 기준으로 각각 계약 identity resolver와 거래일 provider로 분리하는 안을 제시한다. 이관 전 전체 호출자·테스트·문서 참조를 추적한다.
3. WebSocket 전용 함수 _collect_day(), run(), main()은 새 collector에서 기능 동등성과 오프라인 검증이 입증된 후에만 weekday 파일에서 제거하는 별도 승인 변경으로 다룬다.
4. REST 일일 루틴(DailySessionOrchestrator, run_rest_cycle_for_day(), run_daily_once(), run_daily_forever(), daily_main())은 REST 관측기/일일 오케스트레이터로 옮기거나 유지 위치를 명시적으로 결정한다. 새 구조가 기존 REST 결과와 manifest를 재현하기 전에는 제거하지 않는다.

### 단계 C — 검증, 롤백, 옛 코드 정리 조건
1. 각 단계 전 변경 대상 파일의 SHA-256과 원본 사본을 보존한다. 기존 수정/미추적 파일은 덮어쓰지 않는다.
2. 먼저 오프라인 단위 검증 및 startup gate를 확인한다. 이 단계는 인증/REST/WebSocket 네트워크 요청을 보내지 않는다.
3. 별도 승인을 받은 뒤에만 단일 수집기를 기동한다. 승인된 시점에도 시간 가드를 우회하지 않으며 두 번째 연결을 열지 않는다.
4. 다음 거래일 08:35에는 프로세스 수, PID/부모 PID, 작업 스케줄러, watchdog 로그, raw 파일 경로/크기/hash, 마지막 프레임 시각을 읽기 전용으로 확인한다. 09:00 이후에는 호가 프레임·심볼 커버리지·프레임 간격·세션 오류를 별도 확인한다.
5. **새 경로가 하루 동안 깨끗하게 수집된 것이 입증된 뒤에만 옛 WebSocket 코드 정리를 제안한다.** 한 거래일의 깨끗한 수집, 단일 세션, 필수 심볼 커버리지, 원본 보존 및 롤백 절차가 모두 PASS가 아니면 옛 코드를 삭제하지 않는다.
6. 롤백은 코드 원본 복원만으로 끝내지 않는다. 작업 스케줄러/Run 원본 설정을 검토하고, 사용자 승인을 받은 후에만 설정을 복원한다. 자동으로 옛 Watchdog를 재활성화하지 않는다.

### 일정
- 2026-10-16 08:35 KST: 읽기 전용 기동 상태 체크리스트를 수행할 수 있도록 준비. 재시작은 J-2 완료 및 승인 9 조건 전까지 금지.
- 2026-10-16 장중: 단일 세션과 프레임 수신을 검증하되, 데이터가 없거나 가드가 닫혀 있으면 실패/차단으로 기록한다.
- 2026-10-19 08:20 KST 이전 목표: 일일 기준데이터 루틴과 계약 identity 검증을 오프라인 검증 및 별도 승인 하에 준비한다.
- 2026-10-19 전까지 기존 weekday 파일 삭제는 계획하지 않는다. “새 경로가 하루 깨끗하게 수집된 뒤” 규칙이 일정 목표보다 우선한다.

## 4. REST 관측기의 현재 가치와 재개 조건

### 현재 가치
- REST는 WebSocket 프레임과 별개로 가격/호가를 요청해 독립 관측 근거를 제공하고, WebSocket timestamp/continuity 이슈를 비교하는 데 가치가 있다.
- 기존 모듈은 FHMIF10000000 가격과 FHMIF10010000 호가 TR을 사용하며, historical_market_observations.jsonl 및 요청 타이밍/차단 진단을 기록하는 구조다.
- 2026-10-15 기록에서 KIS_INDEX_OPTION_MASTER_EMPTY로 BLOCKED였고, 옵션 대상 목록과 REST raw 결과가 비어 있었다. 기초자산 REST 관측은 별도 경로로 기록됐다. 따라서 모듈이 존재한다는 사실은 옵션 관측 성공을 뜻하지 않는다.

### 재개 전 조건
1. 당일 공식 옵션 마스터를 다운로드하고 원본과 SHA-256을 보존한다.
2. 계약별 심볼, exact expiry, strike, CALL/PUT identity를 검증한다.
3. 당일 기준데이터 산출이 성공하지 않으면 REST 옵션 관측은 BLOCKED로 유지한다. 전일 후보 목록을 당일 기준으로 재사용하지 않는다.
4. 호출 간격 최소 1.25초, 초당 1건 이하, 자동 재시도 금지, 일일 호출 수 상한 및 요청 로그/hash를 적용한다.
5. 실제 REST 관측 재개 여부는 사용자 결정으로 남긴다. 이 문서는 재개를 승인하거나 자동 스케줄을 만들지 않는다.

## 5. AGENTS.md 반영 문구 초안 — 적용 전용 승인 필요

> ### KIS Market Data Collector Boundaries
> - Exactly one process/module owns the KIS VTS WebSocket session: scripts/kis_vts_websocket_collector.py.
> - REST observation, daily reference-data preparation, watchdog, and common utilities MUST NOT open a WebSocket session or send subscription/unsubscription messages.
> - Never run the legacy infrastructure.kis.kis_vts_weekday_collector WebSocket path alongside the primary collector.
> - Do not delete legacy WebSocket code until the new path has completed one clean trading day and coverage, continuity, raw preservation, and rollback evidence are reviewed.
> - Enforce the WebSocket subscription cap of 41 per session and REST pacing of at most one request per second; planned REST validation interval is at least 1.25 seconds with no automatic retry.
> - If source-time semantics, contract identity, or ACK correlation are unverified, do not infer them; fail closed and report BLOCKED/NOT PROVEN.
> - Do not bypass time guards, open a second connection, call KIS Live, or use order/account APIs without separate explicit approval.
> - Any scheduler/registry change must preserve the original setting and include a reversible record. Never stage, commit, or push without explicit instruction.

## 6. 현재 상태와 승인 경계

- J-1: 주요 실행 경로와 import 의존성 확인. 옛 수집기의 정확한 실제 구독 수 및 오류와 재연결의 시간 일치는 미확정.
- J-2: HKCU Run의 옛 Watchdog 시작값은 백업 후 비활성화. Watchdog가 종료 시도 중 옛 수집기를 새 PID로 재기동한 사실을 확인했으나, 재기동된 프로세스 종료는 도구 안전 검사에 막혀 검증되지 않았다. 단일 세션은 NOT PROVEN.
- J-3: 이 문서는 설계 초안만 작성한다. 코드, AGENTS.md, 작업 스케줄러의 새 구조는 변경하지 않았다.
- 사용자 결정 필요: REST 관측 재개 여부, 공통 유틸 분리 설계 승인, supervisor/작업 스케줄러 전환안 승인, AGENTS.md 문구 적용 승인.
