# AGENTS.md — KOSPI200 Project 작업 기준

## 1. 문서 권한과 기준
이 문서는 저장소 작업 지침이다. 기준의 권한 순서는 다음과 같다.

1. 사용자의 현재 직접 지시
2. [Current Baseline v2 — SSOT (2026-11-09)](https://app.notion.com/p/4135f4f6eaa181f7ac42dea70e10fa42)
3. SSOT가 유효하다고 명시한 확정 Decision Log 항목
4. 이 문서(AGENTS.md)
5. 현재 코드·원본 데이터·새 검증 결과

과거 Q&A, 구 Current Baseline, 과거 초안·PASS/BLOCKED 보고서는 역사 참고 자료다. 최신 SSOT와 충돌하면 현재 실행 기준으로 사용하지 않는다. 확정 Decision Log 항목과 SSOT가 충돌하면 임의 수정하지 말고 충돌을 보고해 사용자 결정을 받는다.

## 2. 프로젝트 범위와 검증 판정
- Q25의 현재 검증은 PSB(validation-only)이며 Production/실거래 준비 완료를 의미하지 않는다.
- 현재 대상 전략은 S1, S2, S5, S6, S7, S8, S9이다. S3/S4는 현재 범위에서 제외한다.
- `PSB_PASS`는 보고서에 명시된 validation-only 시나리오·입력·코드 경로에만 적용한다. Production/REAL_VTS/Live PASS로 확대 해석하지 않는다.
- Fixture 기반 연결 확인은 `PLUMBING_ONLY`; 미실행·증거 부족은 `PSB_UNVERIFIED` 또는 구체적인 `BLOCKED_*`로 기록한다.
- Scenario catalog 생성, 단위 테스트, 신호 관찰만으로 전체 Runtime E2E PASS를 선언하지 않는다.
- FAST/DETAILED 동등성은 동일 dataset hash, manifest, scenario, run scope와 clock 기준을 사용해 실제 비교한 경우에만 인정한다.

## 3. 절대 안전 경계
- KIS Live, REAL_VTS, 실계좌, 실제 주문·정정·취소·계좌·잔고·체결·증거금 API를 호출하지 않는다. 명시적인 별도 사용자 승인과 안전한 작업 범위가 없는 한 Live/실계좌 작업은 금지한다.
- credential, token, 비밀값, `.env` 내용을 로그·Notion·Git에 기록하지 않는다.
- 운영 RiskConfig, runtime 권한 플래그, `.env`, 권한, scheduler, collector 설정 및 실행 상태를 임의 변경하지 않는다.
- 원본 KIS 데이터와 기존 synthetic/derived 데이터셋·manifest는 수정·덮어쓰기·삭제하지 않는다. 검증 산출물은 별도 경로에 생성한다.
- authoritative 입력이 누락·오래됨·불일치·검증 불가이면 추정값, 0/False, synthetic 값으로 보정하지 않고 fail-closed로 `UNAVAILABLE`/구체적 `BLOCKED_*` 처리한다.
- 부분체결, cancel race, late fill, unknown terminal state에서는 중복 주문이나 blind retry를 금지하고 reconciliation/fail-closed 처리한다.
- 비밀정보 노출, 원본 훼손 위험, 실제 주문 가능성, 운영 설정 변경 필요, 근거 없는 권위 데이터 생성 필요 시 즉시 중단하고 보고한다. 같은 오류가 연속 2회 발생하면 반복하지 않는다.

## 4. 데이터·계약 기준
- Runtime/contract의 authoritative source는 KIS 공식 API 및 공식 KIS 종목 Master 범위로 한정한다. KRX·외부 데이터·캐시를 KIS 계약 identity나 필수 KIS 값을 임의 대체하는 용도로 사용하지 않는다.
- Option Master, quote, orderbook, execution의 instrument identity와 exact expiry(YYYYMMDD), strike, option type, broker symbol, multiplier, tradability를 authoritative source로 검증한다.
- 관측값은 원본 응답/frame, API/TR·transport 식별, 환경(VTS/Live), 수신 시각, source timestamp, canonical schema/data version, master snapshot version/hash, 검증 결과 및 실패 사유를 보존한다. 비밀값은 제외한다.
- REST와 WebSocket은 별도 transport/provenance로 취급한다. REST 응답이나 연결 성공만으로 WebSocket frame 품질을 대체·추정하지 않는다.
- `REAL_VTS`, `DERIVED_SCENARIO`, `SYNTHETIC`, `VIRTUAL_EXECUTION` provenance를 분리한다. synthetic/derived는 보존된 KIS anchor와 manifest/hash를 가진 validation-only 보완 입력으로만 사용한다. Production authoritative 입력으로 승격하지 않는다.
- Canonical observation_id 중복, observed_at/received_at 의미, replay eligibility가 입증되지 않은 경우 해결된 것으로 간주하지 않는다.

## 5. 현재 전략 상태 — 기준일 2026-11-09
| 전략 | 현재 확인 상태 | 제한·미완료 |
| --- | --- | --- |
| S1 | S15a signal-only 완료. S15b 단일 short CALL natural-signal Virtual Runtime E2E는 validation-only PSB_PASS. | 단일-leg plumbing 범위. multi-leg/Production route 및 추가 lifecycle 검증 미완료. |
| S2 | Rank 5 확인. | Rank 6 Runtime 미연결, PSB_UNVERIFIED. |
| S5 | 신규 진입 BLOCKED. No.1475 S21 시나리오 카탈로그 54건(24 DESIGNED / 20 BLOCKED_SPEC / 10 BLOCKED_INPUT). | 카탈로그 생성은 Runtime PASS가 아니다. S22 대기. |
| S6 | synthetic validation-only E2E PSB_PASS. | Production 검증 아님. |
| S7 | synthetic validation-only Runtime/exit/fee-aware E2E PSB_PASS. | Production 검증 아님. |
| S8 | S10 synthetic exit E2E PSB_PASS. S11b natural-signal retry E2E PSB_PASS_VALIDATION_ONLY_SYNTHETIC. | No.1397 정책 범위만 적용: 600초 timeout, terminal CANCELLED 확인, 레그별 최대 3회, 3거래일 창, 3일차 15:00 cutoff. 부분체결·일반 취소·거절·상태 불명 시 blind retry 금지. |
| S9 | No.1439 승인 독립형 v0.3: ATM PUT+CALL BUY/BUY, 15:00 진입, 익일 공식 시가/전일 공식 종가 절대 변동률 1% 규칙에 따라 양 레그 청산 또는 stop-loss. | 야간 18:00–06:00 미사용. 공식 KIS multiplier·tradability·가격·calendar 등 미확인 항목은 추정 금지. |

전략별 세부 규칙은 SSOT와 해당 전략의 최신 승인 명세를 확인한다. 한 전략의 retry/exit 정책을 다른 전략에 일반화하지 않는다.

## 6. Runtime·Risk·OMS 공통 원칙
- Strategy → Runtime Input → Decision → Risk → OMS/Order Router → Broker/Virtual Execution → ExecutionReport → Position/Ledger/PnL 경계를 유지한다.
- 각 execution leg의 strategy_id, group_id, leg_id, client_order_id, execution_id 및 수량·계약 identity provenance를 연결한다.
- Position/PnL은 실제 execution/lot/ledger evidence를 기반으로 계산한다. execution evidence가 없으면 position/PnL을 추정하지 않는다.
- 운영 RiskConfig와 runtime_config_verified, risk_limits_available 등 운영 권한 플래그를 validation-only 검증 목적으로 변경하지 않는다.
- validation-only synthetic adapter/config는 운영 설정과 분리하고 manifest, dataset hash, scenario_id, run_id 및 verdict에 provenance를 보존한다.

## 7. Calendar·시간 기준
- 거래일·휴장일·previous/next trading day는 공통 MarketCalendarHub/MarketCalendarSnapshot 경계를 사용한다.
- Calendar authoritative source 충돌(No.1150/1170/1171)은 A6 DC-01 사용자 결정 전까지 해결된 것으로 간주하지 않는다. 미확정이면 UNKNOWN/BLOCKED로 fail-closed 한다.
- 시간은 Asia/Seoul 기준으로 명시한다. KOSPI200 옵션 정규장 및 최종거래일 cutoff는 최신 승인 기준과 authoritative calendar를 확인한다. 날짜·휴장 여부를 추정하지 않는다.
- Calendar 자동화·scheduler·Control Tower 상세 요구는 A6 DC-03/DC-04 결정 전까지 운영 설정이나 scheduler 변경 근거로 사용하지 않는다.

## 8. 문서·Notion 기록 관리
- Current Baseline v2를 현재 기준으로 사용한다. 구 Current Baseline 및 A5 진행표는 역사 참고로 보존한다.
- Decision Log의 확정 항목을 임의로 수정·폐기·재작성하지 않는다. 충돌은 decision card로 분리해 사용자 결정을 받는다.
- Notion 페이지 삭제는 사용자가 해당 페이지와 삭제를 명시적으로 승인한 경우에만 가능하다. 페이지 이동은 대상 parent와 링크를 검증하고 승인된 범위에서만 한다.
- 작업 보고는 지정된 Q&A `[No.xxx 답변내용요약]` 페이지에 기록하고 중복 번호를 만들지 않는다. 기록 후 재조회해 실제 저장 내용을 확인한다.
- 과거 결과는 날짜·범위·provenance와 함께 기록하고 현재 상태처럼 표현하지 않는다.

## 9. Git·작업폴더 보호
- 변경 전 원격 대상 브랜치, HEAD, AGENTS.md, 실제 파일 상태와 작업 범위를 확인한다.
- 원본 작업폴더의 dirty/untracked 파일은 보존한다. 해당 폴더에서 reset, clean, checkout, pull 또는 덮어쓰기를 하지 않는다. 필요한 경우 별도 worktree를 사용한다.
- 승인된 대상 브랜치에서만 작업한다. `cleanup/p2-quarantine-20261026` 이외 브랜치 push, `Project200`/`master` push, force push, merge 및 history rewrite를 금지한다.
- 커밋 전 diff와 staged 파일 목록을 확인하고 승인 범위 밖 파일을 포함하지 않는다. 문서 전용 변경은 해당 문서만 커밋한다.
- 사용자가 명시적으로 승인한 경우에만 commit/push한다. Push 후 원격 SHA를 확인한다.

## 10. 검증 및 보고
- 작업 전 현재 기준과 대상 파일·변경 범위를 명시한다. 기존 테스트의 존재나 과거 PASS만으로 현재 기준 충족을 가정하지 않는다.
- 변경 범위에 맞는 정적 검사·diff 검토·테스트를 수행하고 실행하지 않은 검증은 수행했다고 보고하지 않는다.
- 테스트 실패는 현재 기준, fixture/manifest, 환경, 코드 회귀 등 근거에 따라 분류한다. 기준 충돌을 테스트 수정으로 숨기지 않는다.
- 보고에는 기준 문서/버전, 대상 범위, 변경 파일, 실행한 검증과 결과, 미검증·차단 사항, commit SHA(있는 경우)를 포함한다.

## 11. A6 정리 프로토콜 (2026-11-09)
A6 C01–C10은 문서·기준 정합성 정리 작업이다. 완료 전까지 A5 전략 실행 단계는 일시 중단한다.

- 사용자의 bare `승인`은 A6 진행표에서 첫 번째 `대기` 단계 하나만 실행하고 중지한다. `승인 Cxx`는 해당 단계만 실행한다.
- A6 동안 전략 E2E, Replay, strategy matrix, 전략 로직 변경, 원본 데이터 변경, KIS/Live/실계좌/API 호출, scheduler/collector/운영 설정 변경은 금지한다.
- C01–C05 완료 상태는 A6 진행표 No.1476을 확인한다. C06 이후 단계는 각 단계의 승인 범위에 한정한다.
- C05 Notion 정리 원칙: 상태 배너 또는 supersession notice만 허용된 범위에서 추가하고, 페이지 삭제는 0건으로 유지한다.
- C10 완료 후에도 A5/A4 자동 재개를 추정하지 않는다. 별도 직접 지시가 필요하다.

## 12. Graphify
- 코드베이스 질문에서 `graphify-out/graph.json`이 있으면 첫 grep/search/source read 전에 `graphify query "<question>"`를 실행한다.
- 관계는 `graphify path "<A>" "<B>"`, 개념은 `graphify explain "<concept>"`로 좁혀 조사한다. `graphify-out/wiki/index.md`가 있으면 넓은 탐색에 우선 사용한다.
- 코드 변경 후 Graphify 갱신이 허용된 작업 범위일 때 `graphify update .`를 실행한다. 문서 전용 작업은 코드 그래프 갱신을 요구하지 않는다.
- dirty graphify 출력은 자동 갱신으로 생길 수 있으므로 원본 작업을 덮어쓰거나 무단 정리하지 않는다.

## 13. 즉시 중단 조건
다음 상황에서는 추정하거나 범위를 확장하지 말고 중단·보고한다.
- 실계좌·Live·실제 주문·운영 설정·scheduler·collector 변경이 필요해지는 경우
- credential/secret 노출 또는 원본 데이터 손상 가능성이 있는 경우
- authoritative source, 명세 또는 사용자 결정이 필요한 충돌이 확인된 경우
- 같은 오류가 연속 2회 발생한 경우
- 승인 범위 밖 파일·브랜치·Notion 기록을 변경해야 하는 경우
