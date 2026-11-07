# R0 상태 동기화 — 2026-10-28

조회 시각: 2026-10-28 12:24:11 KST  
범위: 읽기 전용 상태 확인. 기존 코드·설정·원본 데이터는 수정하지 않음. 이 파일은 이번 R0에서 요청된 신규 보고서다.

## 요약

- Branch: `cleanup/p2-quarantine-20261026`
- HEAD: `657b573123ec43495c86da8712b9a6278bd9a746`
- Tag `pre_cleanup_20261026`: 존재. `origin/Project200`도 같은 HEAD이며 ahead/behind `0/0`.
- 작업트리: tracked 수정 27개, 삭제 0개, staged 0개, 미추적 파일 900개(재귀 경로 기준). 기존 변경은 보존.
- `py -m py_compile application/composition/virtual_composition_root.py`: exit 0. `environments/high_speed/` Python 11개 컴파일 실패 0.
- `py -m pytest -q`: **165 passed in 1.59s**. `git diff --check`: exit 0; LF/CRLF 경고만 출력.

## P1 / P2 / P3 증거 상태

| 단계 | 현재 판정 | 직접 확인한 증거 |
|---|---|---|
| P1 인벤토리·시간 의존성 | 증거 없음 | `reports/cleanup/INVENTORY.csv`, `reports/cleanup/CLEANUP_PLAN.md`, `reports/synth/TIME_DEPENDENCY.md` 없음. 신규 인벤토리나 시간 의존성 파일은 이번 조회 전에 존재하지 않았음. |
| P2 격리·회귀 비교 | 부분 완료 / 회귀 비교 미확인 | 저장소의 `reports/cleanup/QUARANTINE_MANIFEST.csv`, `data_archive/real_kis_mock/MANIFEST.sha256`, `_quarantine/` 없음. 별도 백업 `D:\Project200_P0_Backup_20261026\quarantine_P2_20261026\quarantine_manifest.csv`는 존재: 1,259행, `HashMatch=True` 1,259, False 0; 백업 격리 파일 1,260개(매니페스트 포함). 회귀 비교표는 확인하지 못함. |
| P3 실데이터 프로파일링 | 미완료 | 원본 후보는 `data/kis_market_data_restart/`. `data_archive/real_kis_mock/`와 `reports/synth/real_data_profile.md/json`은 없음. `reports/synth/REALISM_COMPARISON.md`도 현재 없음. |

## 실데이터 위치·무결성 관찰

- 원본 파티션 루트: `data/kis_market_data_restart/`. 38개 디렉터리가 존재하며, 이 중 날짜 파티션 외 `logs`도 포함됨.
- WebSocket raw JSONL의 기존 manifest와 SHA-256을 비교한 9개 날짜(2026-10-14, 20261015, 20261016, 20261020, 20261021, 20261022, 20261023, 20261026, 20261027)는 모두 일치.
- `20261019` 파티션에는 `kis_vts_websocket_raw.jsonl`이 없고 `futures_underlying_rest.jsonl`, `heartbeat.jsonl`, `daily_status.json`, `manifest.json`만 확인됨. 해당 날짜 WebSocket raw의 연속성은 입증되지 않음.
- `2026-10-14/manifest.json` 기준으로 `kis_vts_websocket_raw.jsonl`을 포함한 시장관측 원본 10개 파일은 해시가 일치. 보조 메타데이터 3개(`daily_status.json`, `kis_vts_subscription_events.manifest.json`, `kis_vts_websocket_raw.jsonl.manifest.json`)는 현재 해시가 상위 manifest 값과 불일치. `daily_status.json`은 상위 manifest보다 나중에 수정된 시각이 확인되나, 나머지 2개 불일치의 원인은 확정하지 않음. 따라서 모든 파일의 무결성 PASS는 선언하지 않음.
- 20261026·20261027의 raw WebSocket JSONL과 subscription event JSONL은 각각의 개별 manifest SHA-256과 일치.
- 20261028 현재 파티션은 파일 메타데이터만 확인했으며, 장중 원본 파일 내용은 열거나 해시하지 않음.

## 합성 정책·실행 경로 기록 확인

- Q&A No.1344에는 `synthetic-expiry-krx-calendar-v1` 정책과 `production_runtime_eligible=false`, `validation_only=true` 경계가 기록됨.
- Q&A No.1354에는 `--validation-only-synthetic` 실행과 제한 smoke 결과가 기록됨.
- 현재 코드에서도 정책 버전은 `scripts/generate_synthetic_3m_p5.py`, CLI 경로는 `environments/high_speed/virtual_runtime_replay.py`에서 확인됨.
- 결정로그 No.1265는 G1–G4 정책 결정이며, 해당 합성 전용 만기 정책의 별도 결정로그 항목은 이번 검색에서 확인하지 못함. 결정로그 등록용 초안이 필요하며, 이번 R0에서는 결정로그를 수정하지 않음.

## 위험·제한

- Graphify의 `application/composition/virtual_composition_root.py` 구문 경고는 `py_compile`로 재현되지 않음. Graphify 파서 한계인지 다른 원인인지는 미확정.
- P1·P3 산출물 부재와 2026-10-14 보조 메타데이터 해시 불일치는 후속 작업으로 남김.
- UI smoke는 D5에 따라 완료 조건에서 제외하며 `BLOCKED_TOOL_UNAVAILABLE`로 취급. 이번 R0에서 UI smoke를 실행하지 않음.
- 전체 pytest PASS는 테스트 기준선일 뿐 전략 E2E PASS가 아님.

## 안전 경계

KIS API/Live/주문/계좌 API 호출 없음. `.env`·토큰 캐시·스케줄러 변경 없음. 수집기·수집 코드 중지/재시작/수정 없음. 삭제·이동·stage·commit·push 없음. 오늘(20261028) raw 파일은 내용 열람 및 해시 검증하지 않음.
