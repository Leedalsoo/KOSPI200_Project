# Current Baseline v2 — SSOT

> Notion decision source: `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`. This repository file is the synchronized state snapshot. Detailed chronological updates are maintained separately in the A8 update log; the pre-rewrite SSOT is preserved in the linked archive.

## 기준 헤더 — 2026-11-17 (KST)

- CB2 ID: `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`.
- 유일한 활성 개발 기준 브랜치: `Project200`.
- 시작 시마다 `AGENTS.md`, 이 SSOT, `git status`, 현재 브랜치, 로컬 HEAD 및 live `origin/Project200` HEAD를 확인한다. SHA는 고정 기준으로 사용하지 않는다.
- A8 진행표: [No.1546 Q25 A8 로드맵](https://app.notion.com/p/4195f4f6eaa1811a9da1d2072a9b3fd1).
- 변경 이력: [A8 SSOT 갱신 로그](https://app.notion.com/p/4195f4f6eaa181869a49c12e5aa83076).
- 변경 전 SSOT 전체 보존본: [A8 pre-rewrite archive](https://app.notion.com/p/4195f4f6eaa181d1858ff03dca454fee).

## 1. Git 기준 및 작업 규칙

- `Project200`만 정식 개발·통합 기준이다. 단계 작업은 live `origin/Project200`에서 만든 격리 worktree의 `work/q25-a8-<단계>` 브랜치에서 수행한다.
- A8에서 `푸시`로 표시된 단계는 사용자의 A8 명시 지시에 따라 Project200으로 non-force fast-forward push할 수 있다. push 직전 fetch 및 조상 관계를 재확인하고, push 후 local/remote SHA 일치를 확인한다.
- `master`는 GitHub 기본 브랜치이며 변경·삭제 금지. `Project200_First`(고유 커밋 1개)와 `archive/remote-head-before-local-sync-20261111`(고유 커밋 14개)는 보존한다.
- 2026-11-15 사용자 승인으로 원격 정리 후보 5개를 삭제했다: `KOSPI200_BASE`, `Project200_Second`, `baseline/current-implementation-20261011`, `cleanup/p2-quarantine-20261026`, `sync/q25-a7-batch1-integration-20261112`. 로컬 브랜치·worktree·사용자 파일은 별도 승인 없이 삭제하지 않는다. 상세는 No.1545.
- 원본 작업폴더의 untracked 파일, Graphify 산출물, nested worktree 및 기타 사용자 자료는 삭제·이동·stage·커밋하지 않는다. `clean/reset/stash` 금지. 원본 폴더 동기화가 필요한 경우 `git pull --ff-only`만 허용하고 충돌 시 중단한다.
- 2026-11-15 A8 P1 시작 전 실제 확인: 원본 작업폴더는 `Project200`, local HEAD와 live remote HEAD 모두 `d70b27cd845bf5dce89318afb39187186e109321`. 기존 Graphify tracked 파일 2개가 modified이고 다수의 untracked 항목이 확인됐다. 모두 그대로 보존했다. A8 지시서의 tracked diff 0 표기와 달라 실제 관측 상태를 우선 기록한다.
- Windows Python 실행은 `py`를 사용한다. 검증 결과는 실행 명령·종료 코드·범위와 함께 기록한다.

## 2. 데이터 인정·보존 정책 (No.1535 확정)

- Mandatory No.1534 inventory/reuse-first rule: when data sources disagree, compare the relevant confirmed Notion decisions and existing Raw/Canonical/manifest/Master/REST/expiry lineage first; then try crosswalk, independent replay, schema/contract validation or provenance-preserving deterministic fixtures. Do not immediately label a mismatch BLOCKED. Use BLOCKED/UNAVAILABLE only if critical identity, event-time, provenance or required validation evidence remains unresolved.

- 기존 REST·WebSocket 원본 수집 데이터는 프로젝트 검증 입력으로 인정한다.
- 기존 수집 데이터를 기반으로 생성한 합성·보완 데이터도 프로젝트의 공식 검증 입력으로 인정한다. 합성·보완이라는 이유로 별도 격리하거나 검증 자격에서 배제하지 않는다.
- provenance, 원본 연결, 생성 근거, 모델·변환 규칙, manifest 및 SHA-256은 추적 가능하게 보존한다. 생성값을 원본 관측값 또는 Production authoritative 값으로 표기하지 않는다.
- 신규 REST·WebSocket 수집은 중단 상태를 유지한다. 수집기 재시작 및 예약작업 재활성화 금지. 기존 Raw, Canonical, Manifest, accepted dataset 및 synthetic tree는 삭제·덮어쓰기 금지.
- 통합 인정 인벤토리: `data/accepted_market_data/registry_20261114.json`, 9개 그룹, SHA-256 `9e31f8a63b8df515b2c491934617e88f4c3d7f72f6feda545054ae498c3768f6`.
- 10/12·10/13 Canonical v2는 686건 + 1,386건 = 2,072건. 생성 경로는 `data/kis_market_data_restart/{date}/canonical_v2_h0iocnt0_identity_timefix/`. H0IOCNT0 `observed_at`은 거래일과 `BSOP_HOUR`로 만들고 `collected_at`은 WebSocket 수신시각을 보존한다. 해당 생성 결과에서 ID collision 0건.
- Canonical v2 코드 근거는 `scripts/ingest_kis_vts_websocket_canonical.py`, `infrastructure/kis/kis_websocket_market_observation_normalizer.py` 및 `tests/infrastructure/kis/test_kis_websocket_canonical_pipeline.py`에 존재한다. 코드에 frame 내 record index 기반 식별 보조와 관측/수신 시각 분리가 확인됐다.
- Canonical sidecar 자체 SHA와 상위 날짜 manifest 기대 SHA 사이 불일치는 미해결 provenance 항목이다. 이를 정합 완료로 주장하지 않는다.
- Registry에 연결된 accepted Runtime v2는 10/12·10/13 2,072 events를 처리했다. 이 결과는 데이터 입력·Runtime 경로 검증이며 S2 전략 성능 PASS가 아니다.
- 기존 synthetic market data tree는 약 10.744 GiB이며 복사 없이 원본 위치를 참조한다. 2026-11-14 기준 C: 여유 공간은 약 9.8 GiB로 기록됐다. 백업 단일본 위험은 P3에서 재확인한다.

## 3. 정책 충돌 결정 카드

### K-1 - Synthetic contract identity vs authoritative KIS identity

- Status: RESOLVED - option A confirmed by No.1554 on 2026-11-16.
- Provenance-preserving synthetic contracts and complementary observations are accepted as validation-only inputs under explicit SYNTHETIC_CONTRACT: / SYNTHETIC:DERIVED_SCENARIO namespaces, source anchors where available, generation rules, manifests and SHA-256.
- Synthetic identities/values must not be promoted to actual KIS contract identity, account/broker facts, Production or Live. No.1469 authoritative-anchor requirements remain in force for real KIS identity and Production.
- Until a separately connected and approved real-account investment API exists, use existing observations and provenance-preserving synthetic/complementary inputs for software and Virtual Runtime validation. No.1554 does not authorize API calls, orders or Live activation.

## 4. 전략별 현재 상태

| 전략 | 현재 판정 | 검증 범위 및 잔여 제한 |
| --- | --- | --- |
| S1 | `PLUMBING_ONLY` | 단일 short CALL plumbing만. base strangle, multi-leg, exit, fee-inclusive PnL 미완료. |
| S2 | PSB_UNVERIFIED | Q3 completed four validation-only 4-leg E2E scenarios and Fast/Detailed parity: full-fill baseline, group-close/exit, U16 partial-fill repair + U19 evidence-gated recovery, and zero-fill cancel -> group-flat. Q4 residuals: U17 IV basis BLOCKED_INPUT/fail-closed; U18/U19/U21 validation-only checks pass but operating values/providers/Runtime wiring remain unverified; actual fee/tax/slippage/margin and KIS/account identity mapping remain unverified. All 12 operating risk limits remain null/fail-closed. No natural-signal, account, Production or Live certification. |
| S5 | `PSB_PASS_VALIDATION_ONLY_SYNTHETIC` (close-only) | 기존 포지션 close lifecycle 검증 범위. 신규 진입 BLOCKED. |
| S6 | `PSB_PASS` (rank 5 범위) | rank 6 및 나머지 matrix 조합 미완료. |
| S7 | `PSB_PASS` (validation-only synthetic) | 승인된 검증 subset 범위만. Production 승격 아님. |
| S8 | `PSB_PASS` (subset) | No.1398 다중계약 partial-fill 승격 미완료. |
| S9 | `PSB_PASS` (subset) | retry timer 재시작 복원 및 비대칭 체결 repair/flatten 미완료. |

### S2 Q3 validation-only 4-leg evidence (2026-11-16)

- Accepted Runtime v2: 2,072 rows (2026-10-12 to 13), manifest SHA-256 7657C90F13A81A7F98A8CCD075A259C8EC9795477A2A0541366094CD87E0360F.
- Original four-leg sidecar: 21 candidates / 84 quote rows, manifest SHA-256 13580E010C34C74A1787BFFB6B6B72ADEBDC4964F848937C0894BFA0FD4918B7. Synthetic identities and synchronized quotes are validation-only, not listed contracts or actual simultaneous market observations.
- Full-fill baseline: 2,072 events, four legs FILLED, validation-only PnL -787,500.0; trace SHA-256 39EA44475B56D962F5B7DC866AEBAD29A2B234AD78312A54A3010D82E62DF007.
- Group-close/exit: 2,072 events, 3 signals/approvals, 12 routed/filled, rejected 0; realized -1,575,000.0, unrealized -750,000.0, net -2,325,000.0; Fast/Detailed parity PASS. Trace SHA-256 FF8F1071B6187AEF8C778FE94A86DA5FFA9AAC363CF5B437BE1E4234EEE25FBB.
- Partial-fill repair + evidence-gated recovery: 86 events; final quantity 3 per leg; outer-call original 1/3 partial fill then cancel and repair quantity 2; broker snapshot, execution ledger and expected manifest reconciled. Validation-only recovery RESTORE_ALLOWED; U16 REPAIR_COMPLETE/NO_SUBMISSION. Fast/Detailed parity PASS; validation-only PnL -2,362,500.0; trace SHA-256 037B75F88AB15CD6ED808DE4EF7E39019264A23B8AD1E314A6ED7E78F3E2B244.
- Zero-fill cancel to group-flat: 2,072 market events, 4 entry routed, 3 fills + 1 zero-fill CANCELLED, 3 close fills; open lots/pending/account positions all zero. Group-flat and Fast/Detailed parity PASS; validation-only PnL -1,137,500.0; trace SHA-256 59A6EF144EA91C8DCA877D1407CB154C79F42C3F230311C775EE0A3E5CE530E0.
- Track2 focused regression: 271 passed, 531 deselected; compileall and git diff --check PASS.

### S2 Q4 residual decision table (2026-11-17)

| Item | Current verdict | Remaining limitation |
| --- | --- | --- |
| U17 IV basis | BLOCKED_INPUT / fail-closed | No sufficient evidence to approve a general-session IV metric/source/window/threshold. Do not adopt 0.85 as an operating threshold. |
| U18 exit policy | VALIDATION_ONLY_PASS | Operating stop-loss/activation/pullback values are not approved; actual fee/tax/slippage and freshness criteria remain unresolved. |
| U19 recovery | VALIDATION_ONLY_PASS | Actual broker provider, late-fill/timestamp tolerance, operational persistence and automatic Runtime restore are not connected. |
| U21 quote policy | VALIDATION_ONLY_PASS | Evaluator boundary tests pass; Runtime/OMS wiring and authoritative quote provider are not connected. |
| Cost and margin | VALIDATION_ONLY | Actual KIS fee/tax, empirical fill slippage and official KRX/KIS margin formula remain unverified. Fixture values are not operating values. |
| KIS contract/account identity | UNVERIFIED | Actual account API and authoritative contract/multiplier/tick/tradability standards are not connected. |

- All 12 operating risk limits remain null/fail-closed. Quote-age/spread, stop/trailing, fee/slippage and margin fixtures must not be promoted to operating standards.
- Overall S2 verdict remains PSB_UNVERIFIED. Q1/Q2/Q3 validation-only PASS does not mean account, Production or Live approval.
- After a separately connected and approved real-account investment API, reconcile contract code/product type/CP/strike/exact expiry/multiplier/tick/tradability, quote source/time, order/fill, fee/tax, balance/margin, risk and lifecycle fields across the full codebase against official KIS/account definitions.
- Until then, use existing observations and provenance-preserving synthetic/complementary data for validation-only work. No Live/REAL_VTS/account/order API calls, new collection or collector restart.

## 5. Runtime·Risk·OMS 안전 경계

- 주문/체결/포지션/PnL의 identity·수량·group/leg/order/execution provenance를 대조한다. 상태 불명, partial fill, cancel race, late fill, mismatch는 fail-closed.
- Validation-only fixture는 테스트 입력으로 주입할 수 있으나 운영 기본값이나 production risk profile에 복사·승격하지 않는다.
- 운영 risk limits null, Live/REAL_VTS/order submission flags false를 유지한다. 실제 repair/flatten order submission은 별도 명시 승인 전 금지.
- KIS Live, REAL_VTS, 실계좌, 주문·정정·취소·잔고·증거금 API 호출 금지.
- 운영 설정, 권한, scheduler, `.env`, credential/token cache 변경·출력·커밋 금지.
- 신규 REST/WS 수집, collector 재시작, 예약작업 활성화 금지.
- Raw/Canonical/manifest/accepted dataset/synthetic tree는 read-only 입력으로 취급한다. 신규 산출물은 versioned 신규 경로만 사용한다.

## 6. 미해결 및 후속 단계

- K-1 conflict resolved by No.1554: option A allows provenance-preserving synthetic inputs for validation-only use while retaining No.1469 real-KIS/Production authority boundaries.
- Canonical v2: 10/12·10/13의 ID 충돌 0 및 BSOP_HOUR/receive-time 분리는 산출물과 코드 경로에서 확인. 상위 manifest와 sidecar SHA 불일치는 여전히 미해결.
- S2 residuals: U17 IV metric/source/window/threshold; U18 operating exit values; U19 real broker/persistence/automatic restore; U21 Runtime/OMS and authoritative provider wiring; actual fee/tax/slippage/margin; and KIS/account identity field mapping. The 12 operating risk limits remain null/fail-closed.
- S2 실제 4-leg 데이터 후보 21건은 실제 동시·신선한 네 레그 호가 커버리지가 충분하지 않다. 합성 quote를 실제 quote로 주장하지 않는다.
- 백업·재생성 가능성, 단일본 데이터, C: 저장공간 위험은 P3에서 read-only로 확인하고 K-2를 제출한다.
- A8 후속 단계는 No.1546 진행표만 기준으로 한다. A5(No.1415), A6(No.1476), A7(No.1517)은 역사 참고다.

## 7. 확인된 근거

- No.1469: [anchor 없는 계약 UNAVAILABLE 및 validation-only synthetic 원칙](https://app.notion.com/p/4125f4f6eaa181d29441f757645d1ca9)
- No.1534: [Full source-data inventory and reuse baseline](https://app.notion.com/p/4175f4f6eaa181268573ea21a5aef01f)
- No.1554: [K-1 validation-only synthetic identity and real-account API boundary](https://app.notion.com/p/41a5f4f6eaa18188aac6dc511b1f87a5)
- No.1559: [Q4 S2 final verdict and remaining blockers](https://app.notion.com/p/41a5f4f6eaa18129ac88e4cfcdce4f2b)
- No.1535: [기존 수집·합성 데이터 인정 및 추가 수집 중단 결정](https://app.notion.com/p/4185f4f6eaa18106ac1cc19962c109a7)
- No.1537: [S2 10/12·10/13 실제 4-leg 데이터 커버리지 검증](https://app.notion.com/p/4185f4f6eaa18177861be9960ef72097)
- No.1538: [S2 시장보정형 합성 4-leg 데이터 및 Runtime 검증](https://app.notion.com/p/4185f4f6eaa181689b07c6e919b30fc4)
- No.1544: [Project200 브랜치 통합 및 작업폴더 최신화](https://app.notion.com/p/4185f4f6eaa18184a3cfd728c080e34e)
- No.1545: [Project200 단일 기준 및 브랜치 보존·정리 원칙](https://app.notion.com/p/4185f4f6eaa1816b80c9ce740c8ba37d)
- A8 진행: [No.1546](https://app.notion.com/p/4195f4f6eaa1811a9da1d2072a9b3fd1)
- A8 변경 로그: [Current Baseline v2 update log](https://app.notion.com/p/4195f4f6eaa181869a49c12e5aa83076)

## 2026-11-20 T4 source-reconciled shared Runtime verification

- P5 shared StrategyHub tests initially skipped 13 cases because the isolated T4 worktree lacked manifest-declared source anchors. Per No.1534/No.1665, all 63 manifest-declared event files were rechecked against Project200 and matched; the manifest SHA-256 is `47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5` (53,550 rows / 62 days). Two raw anchors and three KRX calendar files were individually SHA-256 verified against the manifest and copied only to the isolated T4 worktree. The 13 tests then passed; Project200 originals were unchanged.
- Additional focused regression evidence in the T4 worktree: 165 passed across S4 MINI identity/runtime/late-fill/U19 (5), Track4 profile/spec (12), U19 recovery (114), shared StrategyHub (13), FRESH31 bridge/U19 (2), R4 multi-leg lifecycle (6), R4 strategy-decision lifecycle (2), Track6 cancel (2), and validation-only provider boundary (9).
- compileall, Ruff F821, Ruff F401 on the new Track4 test, and `git diff --check` passed. These are separate targeted suites, not a complete integrated strategy or T4 fault matrix.
- P5 remains synthetic-only: identity owner unresolved and runtime use prohibited by its manifest. U16/runtime rehydration and the full common/strategy fault matrix remain open. No KIS/REAL_VTS/Live/real-account or actual order/cancel/liquidation API was used.


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