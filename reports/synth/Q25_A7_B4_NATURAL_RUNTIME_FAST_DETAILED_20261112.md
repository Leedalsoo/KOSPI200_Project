# Q25 A7 B4 — Natural Runtime E2E / Fast-Detailed parity (2026-11-12)

## 판정

- B4 검증 작업 완료, S2 최종 판정은 **PSB_UNVERIFIED**.
- 동일 거래일의 실제 관측 데이터로 Runtime E2E를 수행했으나, 검증한 7개 거래일에서 자연 진입 신호가 발생하지 않았다.
- Fast/Detailed Replay semantic parity는 통과했지만 두 모드 모두 신호 0건이다. 신호 발생·주문 실행 경로를 실거래 데이터로 입증한 것으로 간주하지 않는다.

## 기준 및 데이터 선택

- CB2: `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`
- 통합 브랜치: `integrate/q25-s2-20261111`
- 시작 HEAD: `771894387adb1cbd6063495000ee9405f20b0fe2`
- 최신 옵션 마스터 파일: `verification/evidence/fo_idx_code_mts_20261014.zip`
- 마스터 SHA-256: `f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e`
- 마스터 파싱: 6,510 identities, expiry cache 23 records. 2026-10-14 관측 데이터의 26개 계약 심볼이 마스터의 만기월·CALL/PUT·행사가·승수와 모두 일치했다.
- 원본 관측 데이터의 월 단위 만기 표기는 정확한 만기일로 매핑한 임시 replay 사본에서만 보정했다. 원본 파일은 변경하지 않았다.
- 원본 SHA-256 전후 동일:
  - observations: `9d32a5e73bc7580e23fcc7befc9483535c3df41f551b6cbb2ba4fd0ae7e3f7ca`
  - raw WS: `c8f0db829dbb5e7d9882b81bb80dd74454d5aedc987082221f16ac7179edc812`
  - option master: `f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e`

## 자연 데이터 Runtime E2E

- 2026-10-14 replay: 6,840 ticks, option projection errors 463.
- 선물 WS events 225,351 / 지수 WS events 23,320 모두 소비했다.
- 전략 입력: AVAILABLE 5,807; BASIS unavailable 633; option orderbook unavailable 382; volume-profile POC unavailable 18.
- 자연 진입 조건의 첫 차단 사유: BBW 5,538, volume z-score 260, OBI 9. 모든 진입 조건을 동시에 통과한 tick은 0건.
- 2026-10-02, 10-06, 10-07, 10-08, 10-12, 10-13, 10-14의 동일 거래일 replay에서도 자연 진입 신호 0건. 10-06~10-08은 같은 계약 심볼·유형·행사가·승수를 교차 확인한 동일 계약의 정확 만기일만 매핑했다.
- Strategy gate 기본값은 `runtime_config_verified=false`, `risk_limits_available=false`였다. 전략 조건 관찰만을 위해 이 두 플래그를 메모리 내에서만 활성화했고, 설정 파일은 수정하지 않았다.
- `signal_observation_only=true`; broker orders 0, approved/routed/filled/rejected 0. 외부 네트워크 차단, KIS API 미호출, 실주문 미제출.

## 이후 날짜 데이터 커버리지

- 2026-10-15, 10-16, 10-20~10-23, 10-26~10-30, 11-02~11-06, 11-09~11-11 raw WS 파일은 H0IOASP0와 H0UPCNT0를 포함하지만 H0IFCNT0 선물 체결 프레임이 없다.
- 따라서 해당 날짜들은 같은 거래일 기준 선물 basis·BBW·거래량 z-score·POC를 구성할 수 없어 자연 S2 신호 검증에 사용하지 않았다. 서로 다른 날짜의 선물·옵션 데이터를 혼합하지 않았다.

## Fast / Detailed parity

- S2 전략만 명시 선택한 validation-only synthetic replay 100 events씩 실행.
- FAST / DETAILED 결과 동일: signals 0, approved/routed/filled/rejected 0, execution IDs empty, realized/unrealized/net PnL 모두 0.
- 14개 S2 회귀 테스트 파일: **197 passed**; S9 adjacent regression 4 files **46 passed**; total 18 files **243 passed** (Fast/Detailed parity 포함).
- compileall PASS, `git diff --check` PASS, diff secret-pattern scan no matches.
- Graphify 산출물 갱신 완료.

## 변경 파일

- `application/bootstrap.py`: Virtual bootstrap에 명시적 strategy keys 전달.
- `application/composition/automated_virtual_runtime_factory.py`: StandardRuntimeInputProvider가 지원하지 않는 S9 adapter/position-lot 인자 제거.
- `environments/high_speed/virtual_runtime_replay.py`: 선택된 S2 strategy keys를 bootstrap에 전달.
- `tests/scripts/test_virtual_runtime_replay_determinism.py`: S2 선택 및 FAST/DETAILED semantic parity 검증 추가.
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`: 그래프 산출물 갱신.

## 안전 및 다음 단계

- 원본 데이터, 원본 작업폴더 HEAD 및 dirty/untracked 224건 변경 없음.
- `.env`, scheduler, collector, 운영 설정 변경 없음. Live/REAL_VTS/실계좌/KIS 주문 API 미호출.
- S2는 PSB_UNVERIFIED 유지. 자연 신호 부재는 버전 불일치 때문이 아니라 실제 데이터에서 BBW/volume z-score/OBI 조건이 동시에 성립하지 않았기 때문이다.
- B4 결과 기록 후 다음 A7 단계 C1은 별도 사용자 승인 전 시작하지 않는다.
