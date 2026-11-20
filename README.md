# KOSPI200 Project200

KOSPI200 선물·옵션 자동매매 시스템 개발 프로젝트다. 현재 개발·검증의 중심은 **Virtual Trading / KIS VTS / Control Tower / Strategy 1~9 / REAL_VTS 기반 E2E**이며, Live 주문은 실행하지 않는다.

상세 작업 기준은 [AGENTS.md](AGENTS.md)를 따른다.

## 1. 현재 표준 실행 구조

**Market Data Source → Runtime Input → Strategy → Decision → Risk → OMS/Order Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model**

Control Tower는 감독·운영·read-model 계층이며 정상적인 주문 생성이나 전략 로직을 소유하지 않는다.

| 경로 | 역할 |
|---|---|
| `contracts/` | 표준 계약·DTO·Port |
| `core/` | 환경 독립 Domain·Strategy·Risk·OMS |
| `application/` | Orchestration·Composition·Hub |
| `environments/` | Virtual/Paper/Live/High-Speed 구현 |
| `infrastructure/` | KIS/KRX 등 외부 Adapter/Source |
| `interfaces/` | Control Tower/API/UI |
| `tests/` | 회귀·통합 검증 |

## 2. Strategy 기준

Strategy 1~9는 독립적인 Strategy Plugin/Registry 경계를 유지한다.

공통 시장지표와 계산은 Common Analytics가 소유하고 표준 `AnalyticsSnapshot`으로 제공한다. Strategy는 이를 소비하고 전략 고유의 진입·청산·헤지·상태전이·포지션 규칙을 담당한다.

Authoritative source가 없는 값을 고정값, 0/False, 추정값 또는 synthetic 값으로 채워 정상 신호를 만들지 않는다.

## 3. KIS VTS / REAL_VTS 데이터

KIS VTS 모의계좌에서 수집한 실제 시장데이터는 **REAL_VTS 원본**으로 취급한다. REAL_VTS는 Live 데이터가 아니며 Live E2E PASS를 의미하지 않는다.

현재 운영 저장 루트:

`data/kis_market_data_restart/YYYYMMDD/`

날짜별 partition은 독립적인 테스트 데이터셋이 아니라 누적되는 실제 시장 데이터 stream의 저장 단위다.

REST와 WebSocket은 독립적인 수집 경계로 유지한다.

- REST: 시장관측/Historical Store 원본
- WebSocket: raw frame 원본
- source/provenance와 timestamp를 transport 간 혼용하지 않는다.
- WebSocket 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
- manifest와 실제 raw/canonical evidence가 다르면 collector lifecycle 문제로 별도 조사한다.

## 4. Replay / E2E 검증

Strategy 1~9는 가능한 authoritative input 범위에서 독립적으로 검증한다.

**Source → Runtime Input → Strategy Signal → Decision → Risk → OMS/Router → Virtual Execution → Position/PnL → Regression**

실제 signal이 관찰되지 않은 전략은 signal-driven execution lifecycle PASS를 선언하지 않는다.

REAL_VTS, DERIVED_SCENARIO, SYNTHETIC, VIRTUAL_EXECUTION provenance는 서로 구분한다.

각 실행은 독립 Run ID와 독립적인 execution/position/strategy state를 사용한다.

High-Speed Replay은 필요에 따라 가속 실행하되 원본 event timestamp의 순서와 시간관계를 보존한다.

## 5. Control Tower

현재 UI는 다음 구조를 유지한다.

- 6개 운영 탭
- Strategy 1~9
- 3×3 동일 크기 Strategy Grid
- Strategy별 독립 Composition Graph
- Strategy Control의 USE / ENTRY / EXIT
- Strategy Trade P/L과 Account P/L 분리
- Strategy 카드의 월별 Trade P/L: ENTRY → CLOSE/EXPIRY
- 카드 하단의 Strategy Integrated P/L
- Graph에서는 BUY/SELL trade value와 계약 구조를 표시하며 P/L을 계산하지 않음

UI 표준 경로:

**Authoritative Runtime / Execution / Position Read Model → Option Program Read Model → Control Tower API → UI**

UI가 Strategy/Core를 직접 호출하거나 없는 데이터를 임의 생성하지 않는다.

## 6. Filled → Position → Trade P/L → UI

**ExecutionReport → Position Group → Strategy Trade P/L → Strategy Card P/L**

Runtime execution과 Control Tower Read Model은 동일한 authoritative execution/position-group 상태를 바라보아야 한다.

Account P/L과 Strategy Trade P/L은 의미가 다를 수 있으므로 임의로 동일하게 맞추지 않는다. Position open/closed와 Trade Ledger 상태가 불일치하면 별도 accounting/read-model 검증 대상으로 취급한다.

현재 일부 실제 VTS 연결 증거가 확보되어 있지만 이를 Strategy 1~9 전체 Full E2E PASS로 확대하지 않는다.

## 7. 3개월 자동 E2E

자동 검증 pattern:

**trend_up → trend_down → mean_revert → high_volatility → low_volatility → shock**

판정 규칙:

- Replay PASS + UI smoke PASS → PASS
- Replay FAIL → FAIL
- UI smoke FAIL → FAIL
- Replay FAIL이어도 UI smoke는 실행
- UI smoke FAIL이면 다음 pattern으로 회전
- Replay만 FAIL이고 UI smoke가 PASS이면 같은 pattern 재시도

현재 scheduled UI smoke는 HTTP/API/UI contract를 검증한다. 동일 replay의 실제 브라우저 DOM Playwright 검증과는 구분한다.

## 8. 검증 원칙

테스트 파일의 PASS만으로 production 기능의 PASS를 선언하지 않는다.

실제 검증은 현재 코드와 실제 실행 evidence를 우선한다.

기본 참조 순서:

**Current Baseline → 최신 활성 Decision Log → AGENTS.md → 현재 코드/실제 데이터/source → 새 검증**

Windows Python 실행은 `py`를 사용한다.

판정은 실제 실행 명령, 출력, exit code 및 관련 evidence를 기준으로 **PASS / FAIL / BLOCKED**를 구분한다.

## 9. Git / 작업 기준

- `.env` 및 credential은 commit하지 않는다.
- 사용자 작업 중인 unrelated 변경은 임의로 수정하거나 함께 commit하지 않는다.
- 일회성 실행 로그, cache 및 폐기된 Legacy 산출물은 저장소에 남기지 않는다.
- 변경 후 focused test 및 필요한 E2E를 수행한다.
- `git diff --check`와 `git status`를 확인한다.
- commit/push 후 원격 `Project200` HEAD를 확인한다.

상세 작업 절차와 현재 세부 기준은 **[AGENTS.md](AGENTS.md)**를 기준으로 한다.

## 10. 현재 미완료 범주

실제 evidence가 확보될 때까지 다음 항목은 전체 PASS로 취급하지 않는다.

- Strategy 1~9 전체의 REAL_VTS signal → execution → Position/PnL Full E2E
- 동일 3개월 replay와 동일 runtime state를 대상으로 한 실제 browser DOM Playwright 자동 검증
- Strategy Trade P/L / Account P/L / Position open·closed semantics의 완전한 회계 정합성
- KIS VTS Collector manifest/lifecycle과 실제 evidence의 완전한 정합성
- KIS Live credential 및 실제 Live E2E
- 옵션 매수호가·승수·수량·수수료·슬리피지를 반영하는 Runtime 프리미엄 검사
- 옵션 레그별 만기 payoff/max-loss 및 기존 미청산 포지션·체결 원장 기반 계좌 전체 위험 집계
- 부분체결·거절·청산·만기 회귀 검증
- Strategy 1 헤지 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도 확정

## 11. 옵션 헤지 위험 검사 — 현재 계획

옵션 헤지 설정 초안은 config/risk/option-hedge-risk.v1.json, 검증 모델은 core/risk/option_hedge_risk_config.py에 있다. 현재 DISABLED_UNTIL_RUNTIME_INTEGRATION 상태이므로 실제 주문 경로의 위험 차단 기능으로 간주하지 않는다. 단위 테스트가 통과해도 Runtime enforcement PASS를 의미하지 않는다.

구현 순서는 다음과 같다.

1. Strategy 1 보호 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도를 별도 검토한다.
2. authoritative 매수호가, 계약 승수, 수량, 수수료 및 보수적 슬리피지를 포함해 프리미엄을 검사한다.
3. 각 레그의 정확한 만기·행사가·방향·수량으로 만기 payoff와 최대손실을 계산한다.
4. 기존 미청산 포지션과 실제 체결 원장을 연결해 중복 없는 계좌 전체 위험을 집계한다.
5. 부분체결·거절·청산·만기 및 입력 누락/오류 회귀를 검증한다.

기존 공통 RiskConfig의 일일 손실 한도와 증거금 한도는 그대로 유지하며 옵션 프리미엄/최대손실 한도로 재해석하지 않는다. 임시 설정 금액은 최종 운용 한도로 확정되지 않았다. authoritative 데이터가 누락되거나 계산이 불가능하면 fail-closed한다. 전략 코드·manifest·매매 정책은 전략별 설계 및 회귀 범위 승인을 거친 뒤 변경한다.

README는 프로젝트의 현재 구조와 작업 순서를 요약하고, 상세 절차는 AGENTS.md, 실제 결정 상태는 Notion의 최신 Q&A와 확정 Decision Log를 기준으로 한다.


## 12. Current U22 strategy revalidation (2026-11-20)

The current isolated worktree `Q25_A8_U22_Current_20261120` was rechecked against the present U22 source and the latest Notion decisions. Missing test data was reconciled against existing `Project200`/R10 originals by manifest and SHA-256 before using read-only copies in the isolated worktree.

| Scope | Current result |
|---|---:|
| S1-S4 targeted + shared-runtime subset | 266 passed |
| S5-S7 targeted regression | 115 passed |
| S8/U19/U21/candidate isolation focused regression | 256 passed |
| S9 focused regression | 44 passed |
| Shared S1/S9 freshness | 12 passed |

The S1-S4 shared-runtime subset uses a synthetic signal driver; it validates common routing/fault boundaries, not natural signal generation for every strategy. The P5 fixture manifest explicitly prohibits runtime use and leaves synthetic contract identity unresolved. S5-S7 counts are focused regression evidence, not full strategy acceptance.

S8 natural multi-contract partial-fill: validation-only 3 contracts per leg, 1+2 fills, FAST/DETAILED parity, 6 order commands/9 execution events, 6 PositionLots/6 close events, gross group/account PnL +30,000 KRW and final FLAT. Default entry quantity remains 1; zero-fee assumptions do not certify fee-inclusive PnL.

S9 independent ATM PUT+CALL BUY/BUY: normal close +1,060,000 KRW; below-1% stop-loss -620,000 KRW; one-leg reject intentionally retains `OVERNIGHT_INSURANCE_PARTIAL`; process restart restore/resume ends CLOSED/FLAT. All reports are synthetic validation-only.

These results do not establish S1-S9 full integrated E2E, official KIS data readiness, REAL_VTS, Live or real-account readiness. No real order, cancel or liquidation API was used. Details: Notion No.1663 and the U22 follow-up record.

## 13. Project200 current strategy validation integration (2026-11-20)

The current U22 strategy-validation branch was fast-forward integrated into `Project200` after checking its ancestry and changed-path overlap with the existing local worktree. The pre-existing 203 modified/untracked local items were preserved and were not included in the integration commit. The integration head is `c26c979cccc61a8899cc2b662bdd2778ce8bc030` before the follow-up correction recorded below.

The U22 branch's separate targeted suites recorded 693 passed across S1-S4, S5-S7, S8/U19/U21/candidate isolation, S9, and shared freshness. These are separate scopes, not one S1-S9 integrated E2E run. After integration, Project200 reran 375 tests in four focused batches: U19/candidate/S2 identity and replay 176; S8/multi-leg/S2 quote and identity 99; broker/SQLite settlement 44; independent S9 policy/runtime/recovery/freshness 56.

Project200's first S8 multi-contract rerun exposed a line-ending-only raw-hash mismatch between semantically identical risk-profile JSON files and a fee-specific error being masked by a generic profile error. The adapter now uses a CRLF/LF-normalized semantic digest for this profile binding, while exact-file sidecars continue to verify raw bytes; non-zero fee is rejected before the broader profile-integrity check. A CRLF/LF equivalence regression test was added. The focused S8 batch then passed 99 tests.

`compileall`, scoped Ruff F821, Ruff F401 on the new S8 files, and `git diff --check` passed. A broader F401 scan still reports 33 existing unused-import findings in legacy/touched files; no unrelated cleanup was applied. Synthetic validation-only provenance and no-live-order boundaries remain unchanged. See Notion No.1663 and Current Baseline v2 for the full evidence and limitations.

## 14. T4 X3 ? S4 Mini futures Virtual Runtime fault slice (2026-11-20)

Track4 futures hedge identity is enforced as KRX MINI (`product_type=MINI`, multiplier 50,000) in the validation composition and Virtual multi-leg bridge. A stored STANDARD/250,000 identity is rejected with `TRACK4_MINI_FUTURES_IDENTITY_REQUIRED` before VSSF order submission. Existing synthetic STANDARD routes remain unchanged.

Focused results: 13 committed S4 identity/runtime/profile tests passed, including Virtual Risk/OMS/Router/VSSF entry fill, partial 2/5 fill ? confirmed cancel ? late 3/5 fill exact-once reconciliation, close-to-FLAT, and wrong-product identity fault injection. A separate S3/S4 StrategyHub signal integration run passed 2 tests in an isolated worktree; its raw-source-dependent test file was not committed. A separate 16-test multi-leg bridge, identity, U19, and T25 regression batch passed after hash-verifying the P5 scenario copy against Project200 originals. The P5 manifest retains `BLOCKED_IDENTITY_OWNER_UNRESOLVED` and `runtime_use=PROHIBITED`; it is used only by the synthetic shared-runtime harness.

This is a validation-only S4 Runtime slice, not official KIS Mini identity or Live/real-account acceptance. S4 U19 SQLite checkpoint reopen and duplicate-event dedup passed; the U19 decision still leaves new entries/order submission disabled and no U16 runtime rehydration was performed. Full T4 strategy/common Runtime fault matrix remains open.

## 15. T4 continued validation ? P5 source reconciliation and shared Runtime (2026-11-20)

A shared StrategyHub regression initially skipped 13 cases because the isolated T4 worktree did not contain the manifest-declared raw anchors. Following No.1534 and No.1665, the P5 manifest and canonical Project200 sources were reconciled before changing the test environment. Manifest SHA-256: `47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5`; 53,550 event rows, 62 days, 63 declared event files. All 63 event-file hashes matched in both roots. The option-master anchor (`e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`), futures daily anchor (`16cc2a913f7e7b02dfb5a82c859ff01e7ed028e005de76751047e3644af8d9ec`), and KRX 2026?2028 calendar anchors were verified and copied only into the isolated T4 worktree. The original Project200 sources were unchanged. The 13 shared StrategyHub tests then passed.

Additional T4 worktree focused regressions: S4 MINI identity/runtime/late-fill/U19 5; Track4 profile/spec 12; U19 recovery 114; shared StrategyHub 13; FRESH31 bridge/U19 2; R4 multi-leg lifecycle 6; R4 strategy-decision lifecycle 2; Track6 cancel 2; validation-only provider boundary 9. Total: 165 passed across separate targeted suites. This is not a single integrated T4 or S1?S9 E2E acceptance run. Static checks (compileall, Ruff F821, Ruff F401 on the new Track4 test, `git diff --check`) passed.

The P5 manifest still explicitly marks identity owner unresolved and runtime use prohibited; it is used only as a synthetic shared-runtime test fixture. T4 U16/runtime rehydration and the complete common/strategy fault matrix remain open. No KIS, REAL_VTS, Live, real-account API, or actual order/cancel/liquidation was used. See Notion No.1665 and Current Baseline v2.


## T4 X3 follow-up - U16 Runtime rehydration after U19 recovery (2026-11-20)

- Added one focused validation test joining the real `evaluate_u19_recovery` decision object with the append-only SQLite U16 Runtime state store and a restarted `ValidationOnlyU16RuntimeCoordinator`.
- The test confirms U19 `RESTORE_ALLOWED` is required to reload the U16 state, while `new_entry_enabled` and `order_submission_enabled` remain false. A previously submitted repair with terminal/reconciliation evidence still pending is not blindly retried after restart. Only after explicit terminal + position-reconciled evidence is recorded can the next U16 retry slot submit the missing quantity.
- Focused validation batches: U16 Runtime/core 61 passed; U19 ledger/recovery 26 passed; shared StrategyHub + runtime safety boundaries 68 passed; R4/Track4 MINI 16 passed; Track6 cancel boundary 2 passed. Total 173 passed across separate batches, not one integrated T4 acceptance run.
- Static checks: `compileall`, scoped Ruff F821/F401, and `git diff --check` passed. Only the U16 coordinator test file changed; no production runtime code or raw source data changed.
- Remaining: full T4 common/strategy fault-injection matrix and integrated end-to-end acceptance remain open. P5 remains synthetic fixture only (`runtime_use=PROHIBITED`). No KIS/REAL_VTS/Live/real-account API or actual order/cancel/liquidation was used.