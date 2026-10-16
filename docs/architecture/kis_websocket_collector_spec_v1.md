# KIS WebSocket 수집기 명세 v1.0

- 상태: 사용자 승인 완료, 구현·운영 검증 진행 중
- 승인일: 2026-10-15
- 프로젝트 루트: C:\Users\white\Desktop\MovingProject\KOSPI200_Project

## 1. 목표
전략 1~9의 재정립을 위한 KIS 실시간 시세·호가를 WebSocket 단일 수집 경로로 확보한다. 기존 날짜별 데이터 저장소와 원본 JSONL은 유지한다. 본 문서는 실시간 주문·계좌 API를 허용하지 않는다.

## 2. 파일과 저장소
- 신규 수집기: scripts\kis_vts_websocket_collector_v2.py
- 신규 실행 래퍼: scripts\run_kis_websocket_collector_v2.cmd
- 기존 저장소 루트: data\kis_market_data_restart\
- 원본 프레임: data\kis_market_data_restart\YYYYMMDD\kis_vts_websocket_raw.jsonl
- 수집 로그: data\kis_market_data_restart\logs\websocket_collector.log
- 연결/제어 이벤트: data\kis_market_data_restart\YYYYMMDD\kis_vts_websocket_control_events.jsonl
- 구독 이벤트: data\kis_market_data_restart\YYYYMMDD\kis_vts_subscription_events.jsonl
- 타이밍 보조자료: data\kis_market_data_restart\YYYYMMDD\kis_vts_websocket_timing.jsonl

저장 경로와 원본 JSONL 형식을 바꾸지 않는다. 기존 원본 데이터는 수정·삭제·이동하지 않는다. 타이밍 후보 필드는 공식 필드 의미가 검증되기 전까지 원본 시각으로 간주하지 않는다.

## 3. 수집 대상
- KOSPI200 지수 실시간 프레임: H0UPCNT0, 종목키 2001
- 월물 옵션 호가: H0IOASP0, 기준 구성 26개
- 현재 기준 총 27개 구독은 기존 구성의 출발점일 뿐이며, 전략 1~9 전체 데이터 충족을 의미하지 않는다.
- 주간 옵션, 옵션 체결 및 전략별 추가 데이터는 종목 마스터·필요성·구독 한도를 검증하고 별도 명세로 확정한다. 현재 날짜에 고정된 주간 종목을 롤오버 검증 없이 자동 구독하지 않는다.

## 4. 수집·시간 기록
- 원본 프레임은 기존 KISRealtimeRawStore 형식으로 추가 기록한다.
- 수신 시각(UTC/KST)과 원본 시각을 구분한다.
- 공식 필드명·날짜 의미·시간대가 검증되지 않은 값은 candidate로만 기록하고 정식 원본 시각 필드에 승격하지 않는다.
- 프레임 파싱 실패, 연결 오류, 재연결, ACK 결과는 제어/구독 이벤트와 로그에 남긴다.

## 5. ACK 및 연결 안정성
- 관측된 ACK의 header.tr_id, header.tr_key, body.rt_cd, body.msg_cd, body.msg1, body.output 구조를 보존한다.
- 실제 ACK 상관관계와 공식 스키마가 검증되기 전에는 ACK 기반 상태 제어를 기본 활성화하지 않는다. 구독 전송만으로 구독 성공을 주장하지 않는다.
- 단일 수집기 실행 잠금을 사용한다. 중복 프로세스 또는 이중 세션 의심 시 신규 연결을 시작하지 않는다.
- 연결 복구 후 재구독 성공과 데이터 재개를 별도로 검증한다.
- 기존 시간 가드와 세션 한도를 유지하며 우회하지 않는다.

## 6. REST 정책
- REST를 실시간 시세·호가의 대체 폴링 경로로 사용하지 않는다.
- 인증/승인키 및 기준정보·옵션 마스터 조회 등 필수 기능의 REST 사용은 별도 검증 전까지 허용 범위를 유지한다.
- 구형 혼합 수집기와 REST 관측 수집기 파일 및 자동 실행 구성은 신규 수집기의 검증·전환 전까지 보존한다. 신규 수집기가 승인 기준을 통과하고 전환이 확인된 후 기존 수집기 파일과 관련 자동 실행 구성을 삭제/비활성화한다. 삭제 전 다른 모듈의 import/호출 의존성을 0으로 만들고, 기존 데이터 파일은 삭제하지 않는다.

## 7. 검증·전환 승인 기준
1. py -m py_compile scripts\kis_vts_websocket_collector_v2.py 통과
2. py -m scripts.kis_vts_websocket_collector_v2 --offline-startup-check 통과
3. 원본 프레임·타이밍·제어 이벤트 저장 경로와 JSONL 호환성 확인
4. 원본 시각과 후보 시각의 분리, ACK 미확정 상태의 fail-closed 확인
5. 단일 프로세스/단일 세션 증거 확보
6. 연결 종료·복구·재구독 후 데이터 재개 검증
7. 전략 1~9의 데이터 요구사항 매핑 완료
8. 충분한 운영 구간의 데이터 공백·지연 측정 및 기준 충족 입증
9. 전환 완료 후 구형 수집기 import/태스크/자동시작 의존성 제거 확인

현재 오프라인 검증은 실시간 연결 안정성, 데이터 연속성 또는 전략 1~9 전체 충족을 입증하지 않는다.

## Date format contract
- All date-only identifiers, trading-date fields, daily directory names, and date labels emitted by the new collector use `YYYYMMDD` (eight digits), e.g. `20261016`.
- Full timestamps such as `recorded_at`, `received_at_utc`, and `received_at_kst` remain timezone-aware ISO 8601 values; they are timestamps, not date-only identifiers.
- Existing historical `YYYY-MM-DD` directories and raw files are immutable. The canonical ingestor may read those legacy paths as a compatibility fallback, but newly collected data is written under `YYYYMMDD`.
- Raw JSONL record schema and filenames remain unchanged; only the date-only value/path convention is standardized.
