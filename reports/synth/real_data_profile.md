# REAL_VTS 원본 프로파일링 — 부분 결과

- 기준일: 2026-10-28
- 상태: BLOCKED_PARTIAL_EVIDENCE
- 범위: 기존 날짜별 자료의 표본·메타데이터 확인. 2026-10-28 오늘 raw 파일의 내용 및 해시는 장중 가드 때문에 접근하지 않음.
- 목적: synthetic validation용 realism 기준과 데이터 공백을 구분한다. 수익성 검증 목적이 아니다.

## 관측된 저장 구조

- 운영 원본 후보 루트: `data/kis_market_data_restart/YYYYMMDD/`
- `data_archive/real_kis_mock/`는 기존 상태 점검에서 존재하지 않는 것으로 확인됨.
- 2026-10-14 표본 파일 크기: REST raw JSONL 16,884,875 bytes; canonical observations 12,836,916 bytes; WebSocket raw 105,320,999 bytes; futures-underlying REST 289 lines / 258,946 bytes; subscription events 40 lines / 89,064 bytes.
- 2026-10-27 표본 파일 크기: WebSocket raw 36,636,743 bytes; subscription events 11 lines / 3,388 bytes.
- 2026-10-14 manifest의 WebSocket evidence_record_count는 300,676이며 상태는 RECEIVED_WITH_EVIDENCE로 기록되어 있음. 이는 manifest 주장이지 모든 필드·기간의 무결성을 입증하지 않는다.
- 2026-10-19 partition에 WebSocket raw JSONL이 없는 것으로 기존 조사에서 확인됨. futures_underlying_rest.jsonl, heartbeat.jsonl, daily_status.json, manifest.json은 존재.

## 표본에서 관찰한 필드·품질 제한

1. Canonical 표본은 `canonical-market-observation-v1`. 옵션 CALL last=15.00, PUT last=126.50이었으나 bid/ask 및 5단계 호가 가격·수량 필드가 모두 0으로 나타남. `observed_at=null`, `underlying_observed_hour="000000"`도 관찰됨. 이 표본만으로 전체 기간의 0 비율을 산출할 수 없음.
2. REST raw 표본 schema는 `kis-rest-raw-market-response-v1`, provider `KISOptionRestAdapter`, TR `FHMIF10000000+FHMIF10010000`. raw metadata에 collected_at, response status, payload, content hash가 포함됨.
3. Underlying REST 표본 TR `FHPIF05030200`, symbol `A05611`. 인접 레코드에서 가격 943.18인 상태로 ask/bid가 942.88/935.00에서 867.74/0.00으로 바뀌는 예가 관찰됨. 원인은 확인되지 않았고, 일부 volume 필드는 0.
4. WebSocket raw 표본 schema는 `kis-realtime-raw-v1`; received_at, trading_date, instrument, tr_id, payload_sha256, payload, sequence 필드가 보임.
5. 2026-10-27 subscription-event 표본은 active_count=27, subscription_cap=41, ack_status=NOT_USED. 이는 실제 broker ACK 또는 각 구독의 성공을 증명하지 않음.

## 무결성 증거의 범위

- 기존 R0 검사에서 WebSocket raw JSONL과 해당 manifest의 파일 해시가 9개 날짜(2026-10-14, 15, 16, 20, 21, 22, 23, 26, 27)에서 일치함.
- 2026-10-26 및 2026-10-27 subscription-event JSONL도 개별 manifest와 일치함.
- 2026-10-14 partition에서 보조 메타데이터 3개(`daily_status.json`, `kis_vts_subscription_events.manifest.json`, `kis_vts_websocket_raw.jsonl.manifest.json`)는 상위 manifest와 해시 불일치. 원인은 미확인. 이를 전체 데이터 무결성 PASS 또는 데이터 손상 확정으로 해석하지 않는다.
- 해시 비교는 확인한 파일 범위만 뒷받침하며, 전체 partition의 의미적 무결성·시간 연속성·시장 품질을 입증하지 않는다.

## 통계 산출 상태

| 지표 | 상태 | 근거/제한 |
|---|---|---|
| 거래일별 파일 존재·크기 | 부분 관측 | 위에 명시한 표본만 확인 |
| REST/WS 레코드 전체 분포 | 미측정 | 안전한 읽기 전용 집계 실행이 차단됨 |
| TR·종목별 프레임 수 및 공백률 | 미측정 | 전체 집계 미실행 |
| 중복·지연·원천시각 분포 | 미측정 | 표본만으로 계산하지 않음 |
| zero/stale bid-ask 및 depth 비율 | 미측정 | 표본 anomaly 존재, 전체 비율 추정 금지 |
| IV surface 및 arbitrage consistency | 미측정 | 현재 표본만으로 검증하지 않음 |
| authoritative session boundaries | 미확정 | D6에 따라 공식 KIS master/실관측 전까지 assumed |
| 전체 raw data integrity | BLOCKED | 2026-10-14 보조 metadata hash mismatch 원인 미확인 |

## 분류 원칙

- 확인된 표본 사실은 관측으로 기록한다.
- 전체 기간에 대한 비율·분포를 표본에서 확대 추론하지 않는다.
- 관측 근거가 없는 시각, 이벤트율, 누락률, 변동성 및 세션 경계는 `assumed: true`로 취급하고 production runtime에 사용할 수 없다.
- 2026-10-28 오늘 raw 파일은 장중 접근하지 않았다.

## 다음 조치

1. 안전한 읽기 전용 집계 경로가 확보되면 오늘이 아닌 기존 날짜 partition만 대상으로 날짜/TR/종목별 통계 산출.
2. 2026-10-14 보조 metadata hash mismatch의 생성·갱신 경로를 조사하되 원본을 수정하지 않음.
3. 결과를 synthetic generator v0.2 realism comparison에 반영하고, 관측치와 가정을 명확히 분리.
