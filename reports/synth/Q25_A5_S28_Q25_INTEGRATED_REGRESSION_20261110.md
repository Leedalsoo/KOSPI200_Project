기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 사용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09

# Q25 A5 S28 — 통합 회귀 및 최종 판정 (2026-11-10)

## 1. 실행 범위 및 기준

- A5 S28: 통합 회귀, Q25 실행 기록·Decision Log·과제 큐 대조/갱신, 전략별 최종 판정표, 전체 pytest, 허용된 원격 브랜치 반영.
- 격리 worktree: `C:\Users\white\AppData\Local\Temp\Q25_A5_S22_S5_GROUP_CLOSE_20261109`
- 작업 브랜치: `q25-a5-s22-s5-group-close-20261109`
- 시작 HEAD: `f1638ba` (S26 implementation + S27 preflight report local commits 포함)
- 실행 전 원격 `cleanup/p2-quarantine-20261026`: `5549e318b38554861b9c52f9b180d1fa969424ba`
- Current Baseline v2 SHA-256 및 SSOT IDs는 위 기준선과 일치했다.
- 원본 작업폴더 `C:\Users\white\Desktop\MovingProject\KOSPI200_Project`는 조회/수정하지 않았다. 기존 dirty 224건 보존.

## 2. 통합 회귀 결과

### 전체 pytest

명령: `py -m pytest -q -p no:cacheprovider --tb=short`

- Python 3.14.6
- 결과: **496 passed / 29 failed / 1 skipped** (14.41초)
- 29건은 A6 C08에서 확인한 것과 동일한 격리 worktree 외부 synthetic validation dataset/manifest 누락 계열이다.
  - R4 lifecycle: 7건 — `p5_run_20261026_trend_up_seed20261026` replay manifest 누락
  - S7 lifecycle/adapter: 6건 — `q25_s05_3_s7_concurrent` manifest/input 누락
  - S8 adapter: 11건 — `q25_s8_v3/strategy8_monthly/normal` manifest/input 누락
  - S7/S8 calendar-generated assets: 3건 — 생성 manifest 누락
  - S7/S8 synthetic asset manifest checks: 2건 — manifest 누락
  - 오류 형태: `SYNTHETIC_REPLAY_MANIFEST_REQUIRED` 12건, `FileNotFoundError` 17건
- A6 C08 결과(473 passed / 29 failed / 1 skipped) 대비 통과 테스트가 23건 증가했고, 실패 29건의 원인 계열은 동일하다. 이번 실행에서 새로운 전략 로직 assertion 실패는 확인되지 않았다.
- 누락 자산을 임의 생성·복사하지 않았다. 원본 raw data와 기존 manifest는 변경하지 않았다.

### 활성 전략 회귀

S1/S2/S5/S6/S7/S8/S9 관련 core, application composition, validation-only runtime 테스트 35개 파일을 대상으로 실행했다.

- **224 passed** (6.95초)
- S2 sequence validation, execution-plan adapter 및 fail-closed profile 테스트 포함.
- py_compile: S26 변경 코드 4개 파일 PASS.
- `git diff --check`: PASS.

### 테스트 부수 변경 정리

전체 pytest가 `Q25_A5_S15B_OPTION_QUOTE_SUPPLEMENT_20261109.json.sha256`의 줄바꿈만 변경했다. `git diff --ignore-space-at-eol`로 내용 차이가 없음을 확인한 뒤 해당 파일만 HEAD 바이트로 복원했다. Graphify 출력 및 S21/S23~S25 미추적 산출물은 실행 전 상태 그대로 보존했다.

## 3. 전략별 최종 판정표

| 전략 | 최종 상태 | 검증된 범위 | 잔여 차단/제한 |
| --- | --- | --- | --- |
| S1 | PLUMBING_ONLY | S15b 단일 short CALL 자연 신호의 validation-only Decision/Risk/OMS/Router/Virtual fill, Position/PnL 및 FAST/DETAILED parity | Base strangle·multi-leg·exit·fee-inclusive PnL·Production OPTION route 미검증 |
| S2 | BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED | S26 4-leg 순서·validation gate 및 fail-closed profile, S27 preflight | 명세 미승인, Runtime progression 미연결, authoritative 4-contract identity/group risk/PnL·pricing/restart 미확인, U16~U21 미결 |
| S5 | PSB_PASS_VALIDATION_ONLY_SYNTHETIC (close-only) | StrategyHub-owned 기존 position seed 기반 자연 exit, Virtual close fill, PositionLot flat 및 FAST/DETAILED parity; focused 51 tests | seed는 synthetic이며 실제 과거 fill이 아님. 신규 진입 정책은 계속 BLOCKED |
| S6 | PSB_PASS (S03 검증 범위) | first_rank=5 / per_order 조건의 take-profit·trailing·15:10 force-close, FAST/DETAILED 및 flat 확인 | rank6 및 나머지 matrix 조합, authoritative contract identity/calendar/운영 설정 미검증 |
| S7 | PSB_PASS (validation-only synthetic) | 자연 StrategyHub 신호 8건, FAST/DETAILED parity, 월·목 만기별 Position/PnL 대사 | synthetic identity/expiry/calendar 및 fee 범위 한정; Production 승격 아님 |
| S8 | PSB_PASS (validation-only synthetic subset) | STOP/TRAILING/EXPIRY exit 및 No.1397 정책 기반 자연신호 retry E2E | No.1398 multi-contract partial-fill은 PLUMBING_ONLY; U19/U21/U22 등 일부 정책 미결 |
| S9 | PSB_PASS (validation-only synthetic subset) | 독립형 ATM PUT+CALL STOP_LOSS, cold-start 복구, 5분 timeout/retry natural-signal E2E 및 73 tests | retry timer의 프로세스 재시작 복원, 비대칭 fill/reject 후 repair/flatten 정책, 공식 KIS 계약·시장 데이터 미확인 |

## 4. Q25 종합 판정

**COMPLETED_WITH_BLOCKERS / PSB_UNVERIFIED — Production readiness 아님.**

- S1/S5/S6/S7/S8/S9는 각각 기록된 validation-only 범위에서만 부분 또는 제한적 PASS다. 이를 전략 전체 또는 Production PASS로 확대하지 않는다.
- S2는 명세·정책·Runtime wiring 선행조건이 충족되지 않아 Runtime E2E를 실행하지 않았다.
- 전체 pytest의 29개 실패는 기존 격리 synthetic 자산 누락이며, clean full-suite PASS로 판정하지 않는다.
- S2-U16~U21은 미결 상태를 유지한다. 사용자 정책을 임의로 확정하지 않는다.

## 5. Notion 원장·Decision Log·과제 큐 반영 원칙

- S27 완료와 S28 통합 회귀 결과를 A5 진행표 및 Q25 과제 큐에 반영한다.
- Decision Log는 사용자 확정·정정·폐기 정책의 인덱스다. S28은 새로운 정책 결정을 만들지 않았으므로 기존 확정 행을 변경하거나 검증 결과를 새 정책 결정으로 위장해 추가하지 않는다. 실행 증거는 Q&A No.1490에 연결한다.
- 별도 Q25 ledger 데이터베이스/페이지는 검색에서 확인되지 않았다. 존재하지 않는 원장을 새로 가정하지 않고 Q&A No.1490을 통합 결과 원장으로 사용한다.

## 6. 안전 경계

- KIS API, REAL_VTS, Live, 실계좌, 실제 주문·취소·정정, 잔고·증거금 API 호출 없음.
- 운영 RiskConfig, `.env`, scheduler, collector, 원본 raw data, 기존 dataset/manifest 변경 없음.
- S26 코드 외 신규 source/test/config 변경 없음. 이 단계의 추가 산출물은 본 보고서만이다.
- Graphify 기존 변경 출력 및 S21/S23~S25 미추적 파일은 stage/commit 대상에서 제외한다.
