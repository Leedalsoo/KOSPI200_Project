# AGENTS.md — KOSPI200 Project 작업 기준

## 1. 최우선 목표

- 최우선 목표는 KOSPI200 프로그램의 기능 완성, 실제 코드 경로의 통합, 안정적인 검증이다.
- 작업은 현재 구현의 결함과 미완료 연결을 해소하는 데 집중한다. 과거 단계표, 오래된 보고서, 일회성 체크리스트를 현재 작업의 선행 조건으로 반복 적용하지 않는다.
- 기존 기능을 보존하면서 가장 중요한 차단 결함부터 작은 단위로 수정하고, 각 단위마다 관련 테스트와 통합 검증을 수행한다.
- 진행 상태는 현재 코드, 데이터, 실행 결과로 다시 확인한다. 과거 PASS/BLOCKED 기록을 현재 결과로 재사용하지 않는다.

## 2. 기준과 충돌 해결

작업 기준은 다음 순서로 적용한다.

1. 사용자의 현재 직접 지시
2. 최신 상태의 사용자 확정 결정 및 승인된 명세
3. 현재 저장소의 이 AGENTS.md
4. 현재 코드·데이터·실행 결과
5. 과거 Q&A, 보고서, 커밋 기록(역사적 참고만)

- Notion의 결정로그는 확정된 정책·명세를 확인하는 데 사용하고, 질문과답변은 작업 연속성과 실행 증거를 기록하는 데 사용한다.
- Current Baseline 및 과거 보고서는 작성 시점의 스냅샷이다. 현재 코드나 더 최신의 사용자 확정 결정과 충돌하면 자동으로 현재 기준으로 간주하지 않는다.
- 승인되지 않은 초안, 과거 전략별 상태, 이전 테스트 PASS는 새로운 승인이나 구현 완료의 근거가 아니다.
- 문서 간 충돌을 발견하면 임의로 정책을 바꾸지 말고 충돌 항목만 분리해 확인한다. 단, 충돌과 무관한 안전한 구현·검증은 계속 진행한다.

## 3. 현재 우선 개발 방향

현재 데이터 파이프라인 작업의 기본 방향은 원본을 보존하고, 품질을 검증한 다음, 부족한 데이터만 보완하여 재현 가능한 가상 검증 환경을 완성하는 것이다.

1. 기존 WebSocket 및 REST 원본 파일을 변경·삭제하지 않고 기준선으로 보존한다.
2. 날짜·종목·계약 누락, 중복, 시간 역전, 비정상 가격, 수신 지연 및 manifest/hash 정합성을 전수 점검한다.
3. Option Master, Quote, OrderBook, Execution의 계약 identity와 시간·출처 provenance를 대조한다.
4. 누락 데이터와 실제 결함을 구분한다. REST 표본 범위 차이를 WebSocket 데이터 누락으로 오판하지 않는다.
5. 원본과 기존 Canonical을 덮어쓰지 않는다. 수정된 정규화 결과는 새 버전·새 경로로 생성하고 원본과 연결한다.
6. 데이터 검증이 끝난 뒤 Runtime/Replay/Virtual 검증으로 연결하고, 각 단계의 미완료·차단 사유를 명시한다.

### 데이터 및 계약 원칙

- REST와 WebSocket은 별도 수집 경계다. source timestamp, received_at, collected_at을 구분하고 서로 대체하지 않는다.
- 원본 frame/response, transport/API 식별자, 거래일, 수신 시각, 원본 source timestamp(제공 시), schema version, master snapshot/hash, 검증 결과 및 실패 사유를 보존한다. credential과 token은 저장하지 않는다.
- 관측 데이터 및 런타임 계약 기준정보의 권위 출처는 KIS API와 공식 KIS 종목 마스터다. 필수 필드가 없거나 오래되거나 상충하면 추정하지 않고 BLOCKED/UNAVAILABLE 처리한다.
- KRX 데이터는 코드 교차대조 및 독립적인 검증 증거로만 사용할 수 있다. KIS 런타임 기준값, 필수 fallback 또는 KIS 계약 identity의 대체 출처로 사용하지 않는다.
- 옵션 계약은 표준/미니 구분, CALL/PUT, 행사가, 정확한 만기일, KIS 종목코드, 승수 및 출처를 각각 검증한다. 승수 등 필수 값은 근거 없이 하드코딩하거나 유추하지 않는다.
- REST의 source timestamp가 수신 시각과 다르거나 오래된 경우 freshness 기준이 검증되기 전까지 tick-level 관측값으로 취급하지 않는다.
- 중복처럼 보이는 레코드도 원본 frame 내 개별 거래일 수 있다. 원본 record 수와 Canonical record 수를 대사하고, 고유 ID는 원본 frame 및 frame 내부 record까지 충돌 없이 식별해야 한다.

## 4. 프로그램 아키텍처 및 구현 원칙

- 현재 저장소의 실제 구조와 공개 계약을 먼저 확인하고 기존 표준 경계를 따른다.
- 공통 계약·DTO·port는 contracts, 환경 독립 도메인·전략·위험·OMS 규칙은 core, orchestration은 application, 환경별 구현은 environments, 외부 연동은 infrastructure, UI/API는 interfaces, 검증은 tests 및 verification에 둔다. 실제 저장소의 최신 구조와 명칭을 우선 확인한다.
- Strategy/Runtime/UI가 외부 브로커 구현이나 서로의 내부 상태를 직접 참조하지 않도록 한다. 공개 계약 또는 명시된 application port를 사용한다.
- Quote/mark price와 실제 fill price를 혼용하지 않는다. 주문·체결·포지션·손익에는 instrument, group/leg/order/execution 및 수량 provenance를 연결한다.
- 부분체결, 취소 경합, 지연 체결, 상태 불명 및 재시작 복구는 실제 체결량과 authoritative 상태를 대사한 뒤 처리한다. 불명확한 상태에서 blind retry 또는 신규 주문을 실행하지 않는다.
- 기존 구현과 테스트를 충분히 확인한 후 변경한다. 단순히 테스트를 통과시키기 위한 fixture, expected value, assertion 완화는 금지한다.
- Legacy 코드는 대체 경로와 호출 관계를 확인하기 전 임의 삭제하거나 새 표준 경로에 무분별하게 연결하지 않는다.

## 5. 안전 및 운영 경계

- KIS Live, REAL_VTS 운영계정, 실계좌, 실제 주문·정정·취소, 잔고·증거금 등 계좌 API 호출은 사용자의 별도 명시 승인 없이는 수행하지 않는다.
- 개발·검증은 격리된 Virtual/validation-only 환경을 우선 사용한다. Synthetic, DERIVED_SCENARIO, VIRTUAL_EXECUTION, REAL_VTS, Live provenance를 혼동하지 않는다.
- Synthetic/Mock 결과는 지정된 검증 범위만 증명한다. 이를 실데이터 검증, 실거래 준비 또는 Live PASS로 표현하지 않는다.
- credential, token, .env, 인증 캐시 및 민감한 계정정보를 열람·출력·복사·커밋하지 않는다.
- 운영 설정, 실제 수집기 프로세스·스케줄러, 권한, 원본 데이터의 변경은 별도 승인을 받는다. 장중 수집기 조작은 승인 없이 수행하지 않는다.
- 원본 데이터 손상, 비밀정보 노출, 실제 주문 가능성 또는 계정 변경 가능성이 발견되면 즉시 중단하고 보고한다.
- 모르는 값을 0, False, 고정값 또는 추정값으로 채워 정상 상태처럼 보이게 하지 않는다. 해당 입력과 영향 범위를 명시하고 fail-closed 처리한다.

## 6. 로컬 작업 및 Git 보호

- 실제 수정은 원본 작업폴더의 기존 변경사항을 보호할 수 있는 격리 worktree/branch에서 수행한다.
- 원본 작업폴더의 기존 dirty/untracked 파일을 삭제·초기화·stash·checkout·reset·clean·덮어쓰기하지 않는다.
- 작업 시작 전 branch, HEAD, git status와 변경 파일 범위를 확인한다. 작업 후에도 동일 항목을 확인하고 의도하지 않은 변경이 없는지 검증한다.
- 원본 raw data, 기존 Canonical, manifest, 사용자 산출물을 덮어쓰지 않는다. 신규 결과는 append-only 또는 versioned 경로에 생성한다.
- Windows Python 명령은 py를 사용한다. 실제 실행 명령, 종료 코드, 테스트 결과 및 제한사항을 기록한다.
- 사용 가능한 경우 Graphify를 코드 탐색·영향 분석에 활용한다. 코드 변경 후 graphify update를 실행하되, Graphify 산출물은 별도 검토 없이 커밋에 포함하지 않는다.
- 커밋은 검증된 관련 파일만 포함한다. 무관한 변경, 원본 데이터, runtime output, cache, log, credential은 커밋하지 않는다.
- commit과 push는 별도 단계다. 정식 통합 브랜치는 `Project200`이다. `Project200` push/merge는 사용자의 명시 승인을 받은 경우에만 수행하고, push 전 fetch 및 fast-forward 조상 관계를 확인한 뒤 non-force 방식으로 반영한다. `master`는 별도 보호 브랜치이며 사용자가 명시하지 않으면 변경하지 않는다.

## 7. 검증 및 완료 판정

변경 단위마다 다음을 수행한다.

1. 변경 전 상태와 영향 범위를 확인한다.
2. 관련 focused tests를 실행한다.
3. 필요한 통합·회귀 테스트를 실행한다.
4. 데이터 변경이 있으면 원본 대비 건수, ID 유일성, hash, provenance 및 manifest를 대사한다.
5. git diff --check와 최종 git status를 확인한다.
6. 실제 실행 결과와 미검증 범위를 분리해 기록한다.

- PASS는 실행한 범위와 증거를 함께 명시한다.
- FAIL은 재현 명령과 실패 원인을 남긴다.
- BLOCKED/UNAVAILABLE은 부족한 입력·권한·증거를 구체적으로 표시한다.
- 테스트 PASS만으로 전체 프로그램 또는 실제 운영 경로의 완성을 선언하지 않는다.
- 반대로 과거 미완료 체크리스트만을 이유로 현재 코드에서 이미 검증된 작업을 반복하지 않는다.
- 구현 가능한 독립 작업은 불필요한 문서 대기나 반복 확인으로 지연하지 말고 순차적으로 진행한다. 정책·운영 위험·외부 계정 영향이 있는 변경만 필요한 승인 게이트에서 멈춘다.

## 8. 문서 및 작업 기록

- 이 파일에는 지속 적용할 작업 규칙만 둔다. 날짜별 진행 현황, 개별 테스트 수치, 일회성 오류, 완료된 작업의 상세 로그는 넣지 않는다.
- 현재 상태와 실행 결과는 해당 작업의 Notion 질문과답변 페이지 및 검증 보고서에 기록한다.
- 과거 기록은 삭제하거나 현재 기준으로 위장하지 않는다. 역사적 기록은 역사적 자료로 남기고, 현재 판단에는 최신 증거를 사용한다.
- 이 문서 변경 후 로컬 원본 작업폴더, 격리 후보 작업폴더 및 지정된 원격 branch의 내용이 동일한지 확인한다.

## Current Git baseline (2026-11-15)
- Canonical working branch: `Project200`.
- At the start of each task, fetch and verify that the local `Project200` HEAD matches `origin/Project200`; do not rely on a static SHA. The latest code baseline and validation evidence are recorded in `docs/CURRENT_BASELINE_V2.md` and Notion `Current Baseline v2`.
- `cleanup/p2-quarantine-20261026` and `sync/q25-a7-batch1-integration-20261112` are historical integration-source branches; `integrate/q25-*` and Q25 A5 branches are retained as development/validation history, not as competing canonical branches.
- `master` is unchanged and remains protected. New feature work should use isolated worktrees; integrate into `Project200` only after explicit user approval.


## Current strategy revalidation addendum (2026-11-20)

- Current isolated verification worktree: `Q25_A8_U22_Current_20261120`, branch `work/q25-a8-u22-current-strategy-e2e-20261120`. This is a validation branch, not `Project200`.
- For missing scenario files, first compare the exact manifest-declared originals in `Project200` and R10, verify SHA-256 and provenance, then copy only into the isolated worktree as read-only validation fixtures. Never fabricate or overwrite an original to satisfy a test.
- The P5 shared-runtime fixture declares `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED` and `identity_policy.runtime_use=PROHIBITED`. Its use is limited to the explicit synthetic shared-runtime test harness; it is not authoritative instrument identity or a production runtime input.
- Current U22 strategy regression evidence: S1-S4 266 passed (includes shared-runtime signal-driver plumbing, not proof of natural signal generation for every strategy); S5-S7 115 passed; S8/U19/U21/candidate isolation 256 passed; S9 focused 44 passed; shared S1/S9 freshness 12 passed. These suites are separate and must not be described as S1-S9 full integrated E2E.
- S8 current natural multi-contract partial-fill E2E uses a hash-bound validation-only profile (3 contracts per leg, 1+2 fills), FAST/DETAILED parity, six orders/nine executions, six lots/six closes, group/account gross PnL +30,000 KRW and final FLAT. Default quantity remains one. Zero-fee fixture does not certify fee-inclusive PnL.
- S9 current independent ATM PUT+CALL BUY/BUY synthetic Runtime reports: normal close +1,060,000 KRW; below-1% stop-loss -620,000 KRW; one-leg reject intentionally remains `OVERNIGHT_INSURANCE_PARTIAL`; process restart restore/resume ends `OVERNIGHT_INSURANCE_CLOSED` and FLAT. Official KIS/real-account inputs remain unavailable.
- KIS API, REAL_VTS, Live, real account, actual orders/cancels/liquidations were not used. Keep all validation-only gates and provenance labels.

## Synthetic validation and source reconciliation addendum (2026-11-20)

- When data is missing or inconsistent, first compare the latest active Notion decisions, prior execution reports, the current local worktree, and the exact raw/accepted/manifest/sidecar sources. Do not inherit an old BLOCKED/PASS label without rechecking current evidence.
- Preserve original data. Reuse only source files whose provenance and manifest references are verified; use isolated read-only copies or explicitly versioned derived fixtures for validation.
- For text-based configuration bindings, distinguish raw-byte SHA-256 from semantic-content hashes. Normalize CRLF/LF only for the explicitly defined semantic hash; retain raw-byte hashes when exact-file integrity is required. A line-ending-only difference is not a policy mismatch when parsed content is identical.
- Until the real-account investment API is connected, use provenance-labelled synthetic/validation-only data and criteria. Never promote these results to REAL_VTS, Live, authoritative contract identity, or real-account readiness. After authoritative account/API inputs are connected, revalidate the complete code against the then-confirmed identity, multiplier, calendar, quotes, fees, margin, and account-risk criteria.

## T4 X3 ? S4 Mini futures Virtual Runtime fault slice (2026-11-20)

- Track4 gamma hedge is MINI futures: product type `MINI`, multiplier 50,000, per No.1066/1067. Other synthetic futures routes retain their separately specified product types.
- Synthetic Track4 identity composition must use the strategy-specific Mini contract spec. `VirtualMultiLegExecutionBridge.identity_for_leg` rejects a stored Track4 STANDARD/250,000 identity with `TRACK4_MINI_FUTURES_IDENTITY_REQUIRED` before VSSF order submission.
- Validation evidence: 13 committed S4 identity/runtime/profile tests passed, including Mini identity, actual Virtual Risk/OMS/Router/VSSF entry fill, partial 2/5 fill ? confirmed cancel ? late 3/5 fill exact-once reconciliation, close-to-FLAT, and wrong-product identity fault injection. A separate S3/S4 StrategyHub signal integration run passed 2 tests in an isolated worktree; its raw-source-dependent test file was not committed. A separate 16-test bridge/identity/U19/T25 regression batch passed.
- P5 shared-runtime fixture was copied from Project200 only after verifying all 65 files (136,779,904 bytes) by SHA-256. Manifest SHA-256 `47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5`; 53,550 event rows/62 days; Option Master anchor SHA-256 `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`. The manifest still declares `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED` and `identity_policy.runtime_use=PROHIBITED`; use is restricted to synthetic shared-runtime regression, never authoritative identity or production input.
- S4 partial-fill/cancel/late-fill exact-once behavior and S4-specific U19 SQLite checkpoint reopen/dedup passed in synthetic Virtual Runtime. The U19 decision permits restore but keeps new entries/order submission disabled; actual U16 runtime rehydration and the complete common strategy/runtime fault matrix remain open. This does not prove official KIS Mini identity, broker fills, or live margin/fees. No KIS/REAL_VTS/Live/real-account order, cancel, or liquidation was used.

## T4 X3 follow-up ? source reconciliation and shared Runtime rerun (2026-11-20)

- When the shared StrategyHub suite skips because a manifest-declared source anchor is not materialized in an isolated worktree, compare the latest No.1534 rule, No.1665 S4 decision, the exact manifest and canonical Project200 source files before deciding the test is unavailable.
- For P5 `p5_run_20261026_trend_up_seed20261026`, the manifest SHA-256 is `47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5`; it declares 53,550 event rows, 62 days, and 63 output files. All 63 declared event files matched the manifest SHA-256 in both Project200 and the isolated T4 worktree.
- The two manifest-declared raw anchors (20261008 option master and futures daily snapshot) and three KRX calendar files for 2026?2028 were verified against the manifest SHA-256 and copied only from Project200 into the isolated T4 worktree. The original Project200 source files were not modified. The 13 previously skipped shared StrategyHub tests then passed.
- Expanded focused synthetic regression evidence in the T4 worktree: S4 MINI identity/runtime/late-fill/U19 5; Track4 profile/spec 12; U19 recovery 114; shared StrategyHub 13; FRESH31 bridge/U19 2; R4 multi-leg lifecycle 6; R4 strategy-decision lifecycle 2; Track6 cancel 2; validation-only provider boundary 9. These are separate targeted suites (165 passed total), not one integrated T4/S1?S9 acceptance run.
- Static checks for the changed Track4 factory/bridge/test files: compileall, Ruff F821, Ruff F401 on the new Track4 test, and `git diff --check` passed.
- The P5 manifest still declares `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED` and `identity_policy.runtime_use=PROHIBITED`. Its shared-runtime use remains synthetic test-fixture only. T4 U16/runtime rehydration and the complete common/strategy fault matrix remain open; no KIS/REAL_VTS/Live/real-account order/cancel/liquidation was used.


## T4 X3 follow-up - U16 Runtime rehydration after U19 recovery (2026-11-20)

- Added one focused validation test joining the real `evaluate_u19_recovery` decision object with the append-only SQLite U16 Runtime state store and a restarted `ValidationOnlyU16RuntimeCoordinator`.
- The test confirms U19 `RESTORE_ALLOWED` is required to reload the U16 state, while `new_entry_enabled` and `order_submission_enabled` remain false. A previously submitted repair with terminal/reconciliation evidence still pending is not blindly retried after restart. Only after explicit terminal + position-reconciled evidence is recorded can the next U16 retry slot submit the missing quantity.
- Focused validation batches: U16 Runtime/core 61 passed; U19 ledger/recovery 26 passed; shared StrategyHub + runtime safety boundaries 68 passed; R4/Track4 MINI 16 passed; Track6 cancel boundary 2 passed. Total 173 passed across separate batches, not one integrated T4 acceptance run.
- Static checks: `compileall`, scoped Ruff F821/F401, and `git diff --check` passed. Only the U16 coordinator test file changed; no production runtime code or raw source data changed.
- Remaining: full T4 common/strategy fault-injection matrix and integrated end-to-end acceptance remain open. P5 remains synthetic fixture only (`runtime_use=PROHIBITED`). No KIS/REAL_VTS/Live/real-account API or actual order/cancel/liquidation was used.

## T4 X3 follow-up - expanded strategy/common Runtime fault regression and source reconciliation (2026-11-20)

- S7/S8 fixtures missing from the isolated T4 worktree were reconciled against No.1534, No.1662/1663 and canonical Project200 originals before reuse. Read-only copies were materialized only in the isolated T4 worktree. Verified hashes: S7 manifest `9bd038eb4e41992a218bcf07d7abc54603d2cc8e7b737c454399c48d81b9b4d9`, S7 events `7c3fb9ea162b727c686fe49381728b2a5932237fff5e1447a3061b5ab064dea6`; S8 normal manifest `a1eaeea94643db7aa7cb80ffc34627b348ee16aebec6dbe2b93dffb9192ae08a`, normal events `6667d0d0a7b700ceaa927289ad1bce6454342c8577af1ee0d3b6dc65aecdc48a`; S8 high-vol manifest `01f204506929a2db2a55c209c247b98353918fc5bd053f64bfd7ed049564ce01`, high-vol events `fda113074213919b2037cbaf8c3076406f4efe92d5d2b45ae6b935f37df84050`.
- S2 U18/U19 verification fixtures were sourced from the preserved R10/P2 roots after checking No.1538, No.1616/1618, No.1642/1646 and No.1662. Existing accepted runtime manifest/partitions and validation profiles in T4 were independently rechecked. The five missing sidecar files were copied read-only from R10: scenario manifest `13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7`, quote JSONL `466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e`, candidate inputs `d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32`, rebound manifest `b22628009c5ed2a06b5fa5cc4fdf28d29e7609b98997add96a2894f0be898546`, rebound quote JSONL `03decb8449543fdf9027ddf5ee2013b78307386f192365b1f662c10c7208c4dc`. Manifest-internal candidate/quote hashes and accepted partition anchors matched.
- S8 normal risk-profile raw-byte SHA differs between Project200 and the current T4/U22 copy due to CRLF/LF only; parsed JSON values match. S8 high-vol risk-profile raw hashes also differ between Project200 and T4, but parsed JSON values match exactly. No source profile was rewritten.
- Expanded focused regression batches (separate invocations; counts overlap and must not be summed as unique tests): U16/U19/common/R4/Track4/Track6 173; freshness/candidate/U19 identity 57; S7/S8/S9 retry/partial lifecycle 42; OMS cold-start/cancel-race/U19/S8 timeout/Track6 restart 69; S1-S4 profile/spec 39; S5-S9 core/runtime adapters 185; S2 strategy/U16/U18/U19/U21 277; S1+S2 U18/U19 verification E2E 5; S8 normal/high-vol + S7 adapter + retry 26. All listed batches passed after source reconciliation.
- These are targeted, separate suites, not one integrated T4 or S1-S9 acceptance run. Natural signal/Runtime acceptance remains strategy-scoped; S3 tradable spread legs remain undefined until economically approved. P5 still has `runtime_use=PROHIBITED` and remains a synthetic shared-runtime fixture only.
- Project200/R10/P2 source originals were not changed. No KIS/REAL_VTS/Live/account API or actual order/cancel/liquidation was used. Existing 203 Project200 dirty/untracked items remain preserved.

## T4 X3 final scoped regression addition (2026-11-20)

- Remaining common identity/runtime admission/replay clock tests: 45 passed. This batch covered multi-leg asset identity consistency, accepted-runtime raw-lineage and H0IOCNT0 record auditors, X2 virtual admission, KRX futures identity guard, VSSF command context types, synthetic quote identity, and virtual replay clock/determinism/isolation.
- S8 natural Runtime normal + high-vol, S8 adapter, S7 adapter and S8 retry timeout batch: 26 passed after restoring the manifest-bound high-vol fixture. Project200 high-vol manifest/data SHA matched `01f204506929a2db2a55c209c247b98353918fc5bd053f64bfd7ed049564ce01` / `fda113074213919b2037cbaf8c3076406f4efe92d5d2b45ae6b935f37df84050`. Project200 and T4 high-vol risk-profile JSON parsed identically despite raw-byte line-ending differences.
- S1/S2 verification E2E rerun after source reconciliation: 5 passed, 0 skipped. No unresolved missing-source skip remains in the selected T4/S1-S9 focused regression batches.
- All counts above are batch-level and overlap across suites; do not sum them as unique test count. Full integrated T4 acceptance and strategy-wide natural-signal certification remain open.
- Project200/R10/P2 source originals unchanged; all copied fixture files remain isolated/read-only. No Live/REAL_VTS/account API or actual orders/cancels/liquidations.