# Q25 A8 R10 T32 — Graphify 최신화 및 검증 통과 범위 확정
Date: 2026-11-19

## 적용 결정
- No.1534를 필수 데이터·원본 참조 기준으로 유지한다.
- No.1535 및 No.1555의 합성·보완 데이터 인정 기준을 적용한다.
- 합성 데이터 검증 PASS는 해당 소프트웨어의 구조·계약·처리 흐름·복구 로직에 대한 validation-only 증거로 확정한다.
- 합성 결과를 실제 시장 관측, KIS authoritative identity, 실계좌 주문/체결, Live/Production 성능 증거로 승격하지 않는다.
- 데이터 불일치/부족은 Notion 결정과 기존 Raw/Canonical/manifest를 먼저 대조하고 대체 검증을 적용한다. 그 후에도 핵심 identity/event-time/provenance가 해소되지 않는 경우에만 BLOCKED/UNAVAILABLE 처리한다.

## 백업 승인 및 완료
- 사용자가 Graphify 산출물 백업을 승인함.
- 대상: graphify-out/graph.json, graphify-out/GRAPH_REPORT.md.
- 백업 위치: %LOCALAPPDATA%/KOSPI200_Project/graphify-backups/Q25_A8_R10/2026-11-19/.
- 원본/백업 SHA-256 일치 확인:
  - graph.json: 15D802184162145CC639F89605E7933264E33FE8F616D5A71324C8B8D346AF95
  - GRAPH_REPORT.md: D9BD4C186B863A98F94B05266B10C3D47F806246B1DF44800DBC04414C89030E
- backup-manifest.json에 source/backup 경로, 크기, SHA-256, branch/HEAD, Graphify version, built_at_commit, Git baseline blob을 기록.
- 원본 파일은 백업 단계에서 수정하지 않음.

## Graphify 최신화
- 작업 폴더: C:/Users/white/Desktop/MovingProject/Q25_A8_R10
- branch: work/q25-a8-r10-order-lineage-u19-20261118
- 입력 코드 기준 HEAD: fcbb0ab65ec1707f8a7d214dcb625b140722e13e
- Graphify: 0.9.91
- graphify update <R10> 실행 후 graphify cluster-only <R10> --no-viz --no-label 실행.
- LLM semantic extraction / community naming은 실행하지 않음.
- graph.json: 9,481 nodes / 27,822 links / 489 communities.
- Graphify report built_at_commit은 입력 코드 기준 HEAD와 일치.
- duplicate node IDs 0, dangling links 0.
- Graph nodes 중 source_file이 빈 문자열인 AST code nodes 780개가 남아 있음(주로 imported/builtin symbol 형태). 이를 file-level provenance가 완전하다고 표현하지 않으며 Graphify 산출물의 알려진 한계로 기록.
- cluster-only --no-viz로 graph.html은 생성하지 않음. Raw/Canonical/accepted/manifest 데이터는 변경하지 않음.

## 코드 구조 검증 확정 범위
- 미커밋 application/composition/validation_only_runtime_invariant_checker.py 변경은 EOF newline만 추가한 것임.
- 해당 checker 전용 테스트: 17 passed.
- py -m compileall 대상 checker: PASS.
- git diff --check: PASS.
- 기존 T18–T26의 합성 기반 OMS/4-leg/partial-fill/cancel-race/U19 restart/replay 검증은 각 단계 보고서와 커밋 증거에 따라 해당 validation-only 범위로 유지한다. T26 배치 결과는 328 passed이며 전체 실거래/Live 인증을 뜻하지 않는다.

## 보호 및 미완료 범위
- Project200 메인 브랜치 및 그 HEAD는 변경하지 않음.
- R10 Raw/Canonical/accepted partitions/manifests와 synthetic source data는 수정하지 않음.
- KIS Live/REAL_VTS/실계좌 API 호출, 주문/취소/청산, 신규 수집은 수행하지 않음.
- Task Scheduler 등록/변경, Graphify watcher 활성화/실행은 수행하지 않음.
- Graphify 산출물은 현재 로컬 R10 작업 폴더에서 최신화됨. 이후 Git 반영은 이 보고서와 산출물 무결성 검토를 포함해 별도 커밋으로 수행한다.
