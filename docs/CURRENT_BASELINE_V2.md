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

## T4 X3 final scoped regression addition (2026-11-20)

- Remaining common identity/runtime admission/replay clock tests: 45 passed. This batch covered multi-leg asset identity consistency, accepted-runtime raw-lineage and H0IOCNT0 record auditors, X2 virtual admission, KRX futures identity guard, VSSF command context types, synthetic quote identity, and virtual replay clock/determinism/isolation.
- S8 natural Runtime normal + high-vol, S8 adapter, S7 adapter and S8 retry timeout batch: 26 passed after restoring the manifest-bound high-vol fixture. Project200 high-vol manifest/data SHA matched `01f204506929a2db2a55c209c247b98353918fc5bd053f64bfd7ed049564ce01` / `fda113074213919b2037cbaf8c3076406f4efe92d5d2b45ae6b935f37df84050`. Project200 and T4 high-vol risk-profile JSON parsed identically despite raw-byte line-ending differences.
- S1/S2 verification E2E rerun after source reconciliation: 5 passed, 0 skipped. No unresolved missing-source skip remains in the selected T4/S1-S9 focused regression batches.
- All counts above are batch-level and overlap across suites; do not sum them as unique test count. Full integrated T4 acceptance and strategy-wide natural-signal certification remain open.
- Project200/R10/P2 source originals unchanged; all copied fixture files remain isolated/read-only. No Live/REAL_VTS/account API or actual orders/cancels/liquidations.

## Strategy-specific residual scope (2026-11-20)

- S5 validation-only seed-ingestion adapter tests: 3 passed. This does not certify S5 Runtime E2E. Per No.1474/1480/1483, retired S5 entry policy remains blocked; the prior seed is not canonical executable evidence and the canonical runtime historical-order ingestion port/full Risk-OMS-Router-Virtual Execution E2E remains unconnected. No synthetic fill was promoted to an observed fill.
- S3 spread-leg definition remains blocked pending approved economic legs; no tradable legs were invented. S4 MINI identity/profile checks passed, but this does not close the full cross-strategy acceptance matrix.
- Therefore the common and strategy-focused regression coverage is substantially expanded, but the full strategy-by-strategy fault-injection matrix and integrated T4 acceptance remain open until S3/S5 prerequisites and natural-signal/runtime evidence are available.

## T4 X3 follow-up — S3 authoritative basis source regression correction (2026-11-20)

- No.956 and current code were rechecked. `KISTrack3RuntimeInputSource` correctly uses paired authoritative KIS H0IFCNT0/H0IFASP0 Futures and KOSPI200 index 2001 observations, 2-second source-time pairing, common volatility/regime, and basis normalization. The existing source had two defects: `_latest_total` selected the numerically largest fee/premium rather than the latest timestamp; historical basis pairing could select an index observation later than the Runtime `as_of` time.
- Corrected `_latest_total` to select by timestamp and restricted historical nearest-index candidates to `<= as_of`. No spread formula, 2-second threshold, policy threshold, or strategy entry permission was changed.
- Added `tests/infrastructure/kis/test_track3_runtime_input_source.py` covering Futures-minus-Index basis history, timestamp-ordered fee/premium totals, common-regime market stability, and rejection when the only matching index observation is in the future.
- S3/S4/S5 focused batch: 41 passed. `compileall`, scoped Ruff F821/F401, `git diff --check` passed.
- S3 execution remains blocked because two economically valid tradable spread legs/sides/quantities/identities are not approved; no same-contract opposite orders were invented. S5 remains entry-blocked: R6 D1 Option-primary + 1 initial gap-fill option / 1 opposite option hedge structure is recorded, but D2-D8 thresholds, strike/expiry selection, costs, risk and lifecycle priorities remain unapproved. No policy activation or runtime entry was enabled.
- No KIS/REAL_VTS/Live/account API, new collection, real order/cancel/liquidation. Original market data unchanged.
## 2026-11-20 T4 X3 continued strategy/common Runtime regression

- Track5 analytics and option contract source; Track7/Track9 contract source; Track7/8/9 policy and lifecycle focused batch: 108 passed.
- Track4 MINI identity; Track6 close/marks; S7 group close/reconciliation; S8 natural normal and multi-contract partial-fill Runtime; S9 retry/partial-reject and Virtual retry/PnL focused batch: 49 passed.
- Separate batches may overlap earlier runs. Do not sum as unique tests or describe as integrated T4 acceptance. T4 branch remained clean at starting SHA `faf1c6e71e41998520d2a7fd4a909d54101f0c00` before documentation updates.
- No policy or S3 spread legs invented. S3 economic legs and S5 D2-D8 remain unapproved; P5 `runtime_use=PROHIBITED`. No KIS/REAL_VTS/Live/account API, actual orders/cancels/liquidations, or new data collection.
- Additional guard/spec batch: KRX futures identity, quote-only evaluation, S3 spread-leg fail-closed contract, Track4 hedge cap, Track1/2/3/4/6 spec alignment, Track6 cutoff/order/trailing lifecycle, and S7 exit policy: 66 passed in 0.43s. This does not approve S3 economics or S5 D2-D8; separate focused batch only.
- S2 source-root precedence correction: T4 `project_root` and R10 original files matched byte-for-byte for all five pinned source inputs. Updated stale test expectation to accept project-root exact-hash resolution or original-root fallback; hash and identity assertions remain. U16/U19 + S2 identity/source/recovery batch: 225 passed. py_compile, Ruff F821/F401, diff-check passed. No source data or production behavior changed.
## 2026-11-20 T4 strategy/common regression extension — No.1670

- Separate focused batches: freshness/no-lookahead + S1 + Track2 + S1/S2 verification 72 passed; X2 auto-stop/evidence/invariant/ledger/provider/VSSF/lineage/candidate/Track6 state 95 passed; S5/S7/S8 adapters + Track2/6 adapters + virtual identity/replay 60 passed; Track1-8 specs + Track9 policy/recovery + Track6/7/8 lifecycle 140 passed.
- Counts are separate invocations, may overlap with earlier work and are not an integrated acceptance or unique-test sum. Synthetic validation-only only. S3 economic legs and S5 D2-D8 unapproved; P5 runtime use prohibited.
- compileall and Ruff F821 passed; changed S2 test F821/F401 passed. Repo-wide Ruff F401 identified 17 unused imports in existing files outside this change; no broad cleanup performed. No production or raw data changes.
## 2026-11-20 T4 cross-source + OMS race regression — No.1671

- Separate synthetic validation-only batches: cross-source/orderbook/H0IFCNT0/no-lookahead/S2 evidence/candidate restart/source diagnostics/KIS capability **44 passed**; freshness restart/OMS cancel-replace/fill-cancel race/router guard/S7 pending identity/S8 multi-partial natural runtime/S9 partial reject/Track6 cancel **34 passed**.
- Counts may overlap previous batches; not a unique-test sum or integrated acceptance. No missing-source skip in these selected runs.
- compileall, repo-scoped Ruff F821, diff-check passed. No production or raw data changed. Cross-source consistency is not broker/account authority; OMS recovery tests do not enable entries or submissions.
- S3 economic spread legs/S5 D2-D8 unapproved; P5 runtime prohibited. No Live/account API or actual orders.
## 2026-11-20 T4 U19 snapshot identity + full-stream/cold-start recovery — No.1672

- Separate synthetic validation-only batches: U19 aggregate identity digest/persistence/REST snapshot reconciliation 69 passed; deterministic full-stream Virtual replay 1 passed; offline OMS cold-start + Track2 U19 + Track9 recovery 57 passed; KIS cumulative-snapshot recovery service (injected mock transport) 9 passed.
- KIS REST cumulative order snapshots stay in reconciliation inbox, not individual execution journal or position mutation. No live transport/API or real order. Mock router release is test-only.
- compileall, repo-scoped Ruff F821, diff-check passed. No code or raw/canonical/accepted data changed. Batches may overlap earlier tests and do not establish integrated acceptance.
- S3 economic spread legs/S5 D2-D8 unapproved; P5 runtime prohibited. Full T4 integrated acceptance OPEN.
## 2026-11-20 T4 replay trace + synthetic adapter boundary — No.1673

- Replay observer/trace contract/synthetic replay adapter/Track2 validation runner wrapper: 24 passed in 0.78s.
- Trace file collision and write-failure handling, stable trace schema, mock observer non-interference, source-row immutability, namespaced synthetic identity and validation-only runner flags verified. No standard identity promotion; Live/REAL_VTS/order submission remain disabled.
- compileall, repo-scoped Ruff F821 and diff-check passed. No code or raw/canonical/accepted data changed. Wrapper/unit checks are not natural-signal, market-performance or integrated T4 acceptance.
## 2026-11-21 T4 U19 restart/snapshot/offline recovery — No.1674

- Separate synthetic focused batches: U19 identity/persistence/account snapshot 69; full-stream Virtual replay 1; offline cold-start 3; Track2 U19 45; Track9 independent recovery 9; R9 S2 U19 restart E2E 2; bridge/VSSF/U19 2; Track6 restart budget 3; Track2 ledger snapshot builder 24; candidate multi-leg restart 2; KIS REST cumulative snapshot mock-only boundary 9 passed.
- Batches may overlap earlier coverage; no unique-test sum or integrated T4 acceptance claim. KIS test was inspected: injected in-memory mock transport, `virtual=True`; snapshots remain reconciliation inbox events, not execution fills or Position mutations. Unresolved events retain recovery gates.
- Initial missing test path was corrected using repository inventory to `tests/core/test_track2_u19_recovery.py`; 45 passed. No product failure inferred from the absent path.
- compileall, repo-scoped Ruff F821, diff-check passed. No production/raw/canonical/accepted data changed. No Live/account API or actual order activity. S3 economic legs/S5 D2-D8 unapproved; P5 runtime prohibited.
## 2026-11-21 T4 candidate isolation + identity-tamper matrix — No.1675

- Separate synthetic focused batches: candidate scope/restart identity 8; candidate/quote identity tamper + multi-leg asset identity 28; U19 aggregate identity digest/cross-candidate checkpoint replay 7; candidate multi-leg duplicate/ledger conflict/pending-order isolation 2 passed.
- Confirms identity mismatch rejection, candidate-specific U19 aggregate/replay isolation, idempotent duplicate delivery, conflicting PositionLot/Fee replay rejected without mutation, and unresolved A pending order does not leak into B flat checkpoint. Counts may overlap previous suites; not unique-test total or integrated acceptance.
- compileall, repo-scoped Ruff F821, diff-check passed. No production/raw/canonical/accepted data changed. No Live/account API or actual order activity. S3/S5 approvals and P5 runtime prohibition unchanged.
## 2026-11-21 T4 shared StrategyHub / option-risk boundary — No.1676

- Shared StrategyHub Runtime E2E: 13 passed; validation-only option risk budget: 4 passed, separate focused batches.
- These do not prove shared-capital pool allocation or simultaneous cross-strategy capital competition. Repository inventory found no dedicated allocator/test; no priority, strategy budget, leverage, margin, or risk thresholds invented. Shared-capital competition remains an explicit X3 gap pending approved policy and implementation/test contract.
- compileall, repo-scoped Ruff F821, diff-check passed. No production/raw data changed; no Live/account API or actual order activity.
## 2026-11-21 T4 X3 S6 state-store integrity fault injection ? No.1679

- S6 existing restart budget/state store/option risk/freshness/gate/order lifecycle focused batch: 48 passed before the additional fault cases.
- Reproduced a real integrity gap: an already-cached in-memory head let `append()` skip revalidation of the existing JSONL file; after external on-disk tampering, another record could be appended.
- Fixed `Track6ValidationStateStore.append()` to reload and validate the persisted chain before every append whenever the file exists. Added tests for broken previous-hash chain, sequence gap, and tampered cached-head append rejection.
- Full Track6 test inventory: 13 files, **67 passed**. Combined focused S6 invocation: **51 passed**. `compileall`, scoped Ruff F821/F401, and `git diff --check` passed.
- Changed only `environments/high_speed/track6_validation_state_store.py` and `tests/environments/high_speed/test_track6_validation_state_store.py`, plus project documentation. No raw/canonical/accepted data, risk profiles, operational configuration, or production/live integration changed.
- Synthetic validation-only. No KIS/REAL_VTS/Live/account API, real order/cancel/liquidation, or new data collection. S3 economic legs/S5 D2-D8 remain unapproved; P5 runtime use prohibited; shared-capital allocation/competition unresolved. Full T4 X3 fault matrix and integrated acceptance remain OPEN.

## 2026-11-21 T4 X3 S6 fsync/short-write/restart fault injection ? No.1680

- Follow-up fault injection covered `fsync()` failure and a simulated short write in the Track6 append-only validation state store.
- `fsync()` failure is propagated. Since a complete record may already be visible before durability confirmation fails, the safe recovery path is to create/reopen the store, validate the persisted chain, then append. Synthetic regression confirms the visible record reloads at sequence 1 and a later append becomes sequence 2. This is not proof of survival across an actual power loss after fsync failure.
- Short-write injection found missing byte-count validation. Added exact `stream.write()` length check and `TRACK6_VALIDATION_STATE_WRITE_INCOMPLETE`. Partial tail remains preserved; restart load and append fail closed with `TORN_RECORD`. No silent truncation or automatic rewrite.
- Full Track6 test inventory: 13 files, **69 passed**. `compileall`, scoped Ruff F821/F401, and `git diff --check` passed.
- Only `environments/high_speed/track6_validation_state_store.py`, its test file and project documentation changed. No raw/canonical/accepted data, manifests, risk profiles, operating configuration or production/live integration changed.
- Synthetic validation-only. No KIS/REAL_VTS/Live/account API, actual order/cancel/liquidation or new data collection. Full T4 X3 fault matrix and integrated acceptance remain OPEN.

## 2026-11-21 T4 X3 S6 persistence failure -> X2 stop propagation ? No.1681

- Inspection found StrategyOrchestrator converts strategy exceptions to `StrategyRunFailure`; the Runtime previously only counted generic strategy failures and continued toward signal collection/arbitration. Track6 state persistence failure therefore did not explicitly latch X2.
- Added `Track6LifecyclePersistenceError`; `_persist_lifecycle()` wraps underlying append/fsync exceptions and retains the original cause.
- `AutomatedVirtualTradingLoop.on_tick()` now detects that typed failure for `track6_daily_tail_insurance` immediately after StrategyHub execution and trips `X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED` before signal collection/arbitration. Existing RiskGuard/RiskEngine latches then deny new admission and route paths. No auto-cancel or liquidation behavior.
- Added tests for OSError wrapping and stop-trip ordering before signal collection.
- Combined Track6 inventory (13 files) + X2 admission/auto-stop suites: **97 passed**. Separate focused Track6/X2 batch: 77 passed. compileall, scoped Ruff F821 and `git diff --check` passed. Six F401 unused imports were reproduced on baseline HEAD; unchanged.
- Validation-only synthetic. No raw/canonical/accepted data, manifests, risk profiles, operating config, Live/account API, actual orders/cancels/liquidations or new collection. Full T4 X3 matrix/integrated acceptance remains OPEN.

## 2026-11-21 T4 X3 S6 recovery read/restore failure -> X2 stop ? No.1682

- Follow-up source inspection found `load_latest()` and `Track6OrderLifecycle.restore_snapshot()` errors during strategy initialization were not covered by the new persistence wrapper and could remain generic StrategyHub failures.
- Added `Track6LifecycleRecoveryError` around state-store load, chain/snapshot validation and restore, retaining the original exception as `__cause__`.
- Runtime now detects both Track6 persistence and recovery error types and trips distinct X2 reasons before signal collection/arbitration: `X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED` and `X2_TRACK6_LIFECYCLE_STATE_RECOVERY_FAILED`.
- Added regression tests for read failure wrapping and X2 stop-trip ordering.
- Full Track6 inventory (13 files) + X2 admission/auto-stop suites: **99 passed in 6.95s**. Separate focused batch: 55 passed. `compileall`, scoped Ruff F821, and `git diff --check` passed.
- Closes inspected Track6 store write/read/restore exception propagation only. Does not prove real power-loss durability, concurrent multi-process writer safety or integrated T4 acceptance. Synthetic validation-only; no raw/canonical/accepted data, risk profile, operating config, Live/account API, actual order/cancel/liquidation or new collection.

## 2026-11-21 T4 X3 S6 multi-process writer collision guard ? No.1683

- A deterministic race probe using two independent store instances with the same run_id reproduced the defect: both read sequence 1, both appended sequence 2, and reopening failed with `TRACK6_VALIDATION_STATE_SEQUENCE_INVALID`.
- Added a per-run OS-level non-blocking lock around the complete reload/chain-validation/sequence-allocation/append/fsync transaction. Windows uses `msvcrt.locking`; POSIX uses `fcntl.flock`. A competing writer fails closed with `TRACK6_VALIDATION_STATE_WRITER_LOCKED`; handle release occurs in `finally`.
- `.jsonl.lock` is intentionally retained for stable lock identity; do not remove it while any runtime may be active. One writer is enforced per run_id. Different run_ids are not coordinated; network filesystem lock semantics are unverified; readers racing an incomplete write continue to fail closed.
- Added a spawned second-process test proving competing writer rejection without a JSONL mutation and successful append after lock release.
- Full Track6 inventory (13 files) + X2 admission/auto-stop suites: **100 passed in 7.39s**. compileall, scoped Ruff F821/F401 for changed store/test, adjacent Track6 F821 and diff-check passed.
- Synthetic validation-only. No raw/canonical/accepted data, manifests, risk profiles, operating config, Live/account API, actual order/cancel/liquidation or new collection. Full T4 X3 matrix/integrated acceptance remains OPEN.

## 2026-11-21 T4 X3 S6 process-crash + concurrent-reader recovery boundary ? No.1684

- Spawned child process acquired the per-run OS writer lock and was forcibly terminated while holding it. A fresh process then acquired the same lock, appended sequence 1, and a new reader validated the chain. This verifies process-exit lock release on the current Windows host only; it is not a power-loss or network-filesystem test.
- Deterministic reader/writer overlap: writer flushed a partial JSONL record and paused; concurrent reader rejected it with `TRACK6_VALIDATION_STATE_TORN_RECORD`. Writer returned `TRACK6_VALIDATION_STATE_WRITE_INCOMPLETE`; partial bytes were preserved and subsequent read remained fail-closed.
- Added lifecycle integration test: persisted torn tail becomes `Track6LifecycleRecoveryError` with original cause preserved. Existing Runtime X2 recovery-failure stop-before-signal-collection test remains in the suite.
- Focused store + lifecycle gate tests: 23 passed. Full Track6 inventory (13 files) + X2 admission/auto-stop suites: **103 passed in 7.70s**. compileall, scoped Ruff F821/F401 and git diff-check passed.
- No production source change in this batch (tests/docs only). Readers do not acquire writer lock; they validate and fail closed on torn/incomplete records. Process-exit lock release is verified on current Windows host only; power-loss durability, network filesystem locking and full T4 integrated acceptance remain unproven/open.
- Synthetic validation-only. No raw/canonical/accepted data, manifests, risk profiles, operating config, Live/account API, actual order/cancel/liquidation or new collection.

## 2026-11-21 T4 X3 S6 crash-during-append + per-run lock isolation ? No.1685

- Spawned writer acquired the run lock, flushed an intentionally incomplete JSONL record, and was forcibly terminated before completion. A fresh writer acquired the released lock, but append and fresh read both rejected the preserved tail with `TRACK6_VALIDATION_STATE_TORN_RECORD`. No truncation/repair occurred.
- Confirmed run A's held lock does not block run B from appending and reopening sequence 1. This is per-run storage lock isolation only; it does not establish cross-run account/capital coordination.
- Full Track6 inventory (13 files) + X2 admission/auto-stop suites: **105 passed in 8.11s**. compileall, scoped Ruff F821/F401, adjacent Track6 F821 and diff-check passed.
- Tests only; no production source changes. OS lock release verified on current Windows host. Power-loss durability, network filesystem locking and full T4 integrated acceptance remain open.
- Synthetic validation-only. No raw/canonical/accepted data, manifests, risk profiles, operating config, Live/account API, actual order/cancel/liquidation or new data collection.

## 2026-11-21 T4 X3 S6 writer-lock contention -> X2 ? No.1686

- Using the actual `Track6ValidationStateStore`, a competing writer held the per-run lock while Track6 lifecycle persistence attempted append. Store returned `TRACK6_VALIDATION_STATE_WRITER_LOCKED`; lifecycle wrapped it as `Track6LifecyclePersistenceError`, preserved the store exception as `__cause__`, and created no JSONL record.
- Combined with the existing Runtime failure regression, lock contention reaches the X2 stop-before-signal-collection path. No cancel/liquidation/live action.
- Focused store + lifecycle gate tests: 26 passed. Full Track6 inventory (13 files) + X2 admission/auto-stop suites: **106 passed in 9.32s**. compileall, scoped Ruff F821/F401, adjacent Track6 F821 and diff-check passed.
- Tests only; no production source changes. Synthetic validation-only; no raw/canonical/accepted data, risk profile, operating config, Live/account API, actual order activity or new collection. Full T4 X3/integrated acceptance OPEN.

## 2026-11-21 T4 X3 S6 same-tick pending processor ordering audit — No.1687

- Latest No.1686~1681, No.1671, No.1674, No.1534 and current Runtime/factory code were compared. The current `on_tick()` order is pending processor -> StrategyHub -> Track6 failure detection -> X2 trip -> signal collection -> arbitration.
- Factory pending processing includes Track6/7 lifecycle cancellation, pending quote processing, U16 repair/flatten reconciliation and repair processing, S9 entry retries and Track2 entry progress. Therefore, a same-tick pending action can precede detection of a Track6 persistence failure and its X2 trip.
- Once X2 is latched, existing checks block subsequent pending processing and multi-leg submission. Focused Track6/X2 ordering and pending/multi-leg blocking tests: 3 passed. compileall, scoped Ruff F821 and diff-check passed. Synthetic in-memory control-flow probe only.
- No production source/test changes. Three pre-existing F401 findings in `automated_virtual_trading_loop.py` were recorded, not auto-fixed. No KIS/Live/account API, real order/cancel/liquidation or new data collection.
- This is an ordering/design gap, not missing source data. Next design step is to split pending observation/reconciliation from repair/retry/new-order side effects while preserving current fill/position freshness. Do not reorder production flow until effects and replay parity are mapped. Full T4 X3 integrated acceptance remains OPEN.

## 2026-11-21 T4 X3 pending processor side-effect inventory — No.1688

- `process_pending_quotes()` reconciles already-routed VSSF order reports/fills into execution, PositionLot and Fee evidence. Track6/7 lifecycle clock branches can cancel pending orders. U16 coordinator may call injected validation-only repair/flatten submit ports. S9 retry logic can cancel timed-out BUY orders and later `execute()` the remaining quantity. Track2 entry progression can `execute()` the next leg after confirmed zero-fill cancel and flat position/lot reconciliation. Track2 mark/PnL refresh is state mutation only.
- Four focused synthetic tests: U16 repair, S9 delayed retry, Track2 next-leg progression, VSSF pending fill reconciliation — **4 passed in 4.13s**. Initial guessed pytest node absent; repository inventory found the actual test name and corrected invocation passed. compileall, scoped Ruff F821 and diff-check PASS.
- No production source/test changes. This confirms the pending callback combines reconciliation and side-effect-capable operations. Next design: split observation/reconciliation from cancel/repair/retry/entry side effects while preserving fill/position freshness and replay parity. No KIS/Live/account API, real order/cancel/liquidation or new collection. Full T4 X3 integrated acceptance OPEN.

## 2026-11-21 T4 X3 pending processor phase separation — No.1689

- Runtime pending work split into three phases. Observation before StrategyHub reconciles existing VSSF order reports/fills and refreshes Track2 group marks; it performs no cancel/repair/retry/flatten/new submit and continues after X2 for late-fill PositionLot/Fee truth. Planning before StrategyHub, only if X2 admission is open, evaluates Track6/Track7 lifecycle clocks and queues cancel intents without sending them. Action after StrategyHub Track6 failure detection and X2 recheck executes queued cancels, U16 repair/flatten/reconciliation, S9 retry, and Track2 sequential next-leg progression.
- Track6 lifecycle persistence/recovery failure in planning trips X2 before StrategyHub. A Track6 failure returned by StrategyHub trips X2 before the action phase. Track6 persistence/recovery errors in deferred action processing also trip X2 before signal collection. X2-latched ticks retain observation but skip planning and actions.
- Latest No.1661 independent S9 ATM PUT+CALL BUY/BUY scope unchanged. No strategy policy, approved input, risk profile or operating config changed.
- Regression batches (separate and potentially overlapping): Track6 13-file + X2 suites 111 passed; focused Track6/X2/U16/S9/evidence 77 passed; R4/Fresh31/S7 9 passed; Fresh62/Fresh63 2 passed; shared StrategyHub/S8 19 passed; Track6 cancel/Track2 progression/R4 lifecycle 25 passed; AST phase-boundary 3 passed. compileall, scoped Ruff F821, test F401 and diff-check passed. One pre-existing factory F401 (`Track9OptionContractSource`) left unchanged.
- Synthetic validation-only. No raw/Canonical/accepted/manifest changes, KIS/REAL_VTS/Live/account API, actual order/cancel/liquidation or new data collection. Full T4 X3 strategy/fault matrix and integrated acceptance OPEN.

## T4 X3 Track7 aggregate restart snapshot boundary (2026-11-21, No.1692)

- Test-only JSON encode/decode round-trip of all 23 Track7State fields passed, including tagged Decimal and timezone-aware datetime values. Existing Track7 lifecycle/cutoff/pending-identity/terminal-close/validation-only Runtime regression: 15 passed.
- A synthetic multi-expiry strategy instance held two expiry states, two group-to-expiry bindings and one exit-pending expiry. Restoring only the active Track7State into a fresh strategy instance lost the group map, second expiry state and exit-pending set. A single Track7State snapshot is insufficient for aggregate restart recovery.
- Aggregate snapshot candidate must account for legacy state, active expiry, states_by_expiry, group_expiry, legacy exit-pending and exit_pending_expiries. Strategy identity/version, config and snapshot integrity require separate review. This is structural synthetic evidence, not an approved persistence or broker-reconciliation policy. Do not add blind cancel/retry or infer broker state.
- Next test-only verification: multi-expiry/group aggregate round-trip, version/corruption/duplicate-binding cases and X2-latched restore ordering. No code/policy/raw-data changes; no Live/account API, actual order/cancel/liquidation, collector restart or new collection. Full T4 X3 acceptance remains OPEN.

## T4 X3 Track7 aggregate snapshot contract probe (2026-11-21, No.1693)

- Compared latest Notion No.1692, No.1691, No.1690, No.1689, No.1546, Current Baseline and No.1534 source/provenance rules before implementation. Current T4 branch and origin T4/Project200 HEAD were both `5f2ce2e5ca1bd1dfd3d6e6edd579a3896f5f036f`; Project200 existing dirty/untracked items were left untouched.
- Added `tests/core/test_track7_aggregate_snapshot_contract.py` as a test-only fixture. Candidate envelope covers schema version, strategy ID/version, validation config, legacy Track7State, active expiry, states_by_expiry, group_expiry, legacy exit-pending and expiry-scoped exit-pending. Tagged Decimal/datetime values and SHA-256 envelope integrity are exercised.
- Synthetic cases: 2-expiry/2-group round-trip with legacy state and pending markers; unsupported schema version; checksum corruption; missing Track7State field; duplicate group binding; unknown group expiry; X2-latched restore preserves state but marks side-effect actions disallowed.
- Tests: new fixture **6 passed**; adjacent Track7 lifecycle/cutoff/spec/exit regression **19 passed**. Separate batches; do not sum as unique integrated coverage. `py -m compileall -q tests/core/test_track7_aggregate_snapshot_contract.py`, `py -m ruff check ... --select F821,F401`, and `git diff --check` passed.
- This is a test-only serialization contract, not production persistence, approved recovery policy, Runtime restore wiring or broker reconciliation. No blind cancel/retry, actual broker state inference, KIS/REAL_VTS/Live/account API, actual order/cancel/liquidation, collector restart, new data collection, raw/canonical/accepted source, manifest, policy or operating config was changed.
- Next boundary: compare the test-only aggregate contract against any future approved persistence/reconciliation decision, then extend fault tests for strategy/config mismatch and restore ordering only without side effects. Full T4 X3 fault matrix and integrated acceptance remain OPEN.

## T4 X3 Track7 aggregate snapshot follow-up — No.1694 (2026-11-21)

- Additional test-only fault cases cover strategy identity/version mismatch, validation-config mismatch, and restore → authoritative-observation reconciliation → action-gate ordering. X2-latched flow preserves restored state and permits observation reconciliation while suppressing side-effect actions.
- This does not approve production persistence or broker-reconciliation policy. No live/account API, real orders/cancels/liquidation, collector restart, new data collection, or raw/canonical/accepted data changes.

## T4 X3 Track7 aggregate serialization edge validation — No.1695 (2026-11-21)

- Compared No.1694/1693/1692, No.1546, Current Baseline, No.1652 candidate/account aggregate checkpoint boundary and No.1534 source/provenance rules. No.1652's candidate-scoped/account aggregate checkpoint behavior is a separate existing boundary; it was not conflated with Track7 strategy aggregate state.
- Extended the test-only Track7 aggregate snapshot contract with negative cases for duplicate expiry-state records, duplicate exit-pending expiry entries, malformed Decimal/datetime values, unknown serialization tags, malformed tagged-value envelopes and bool-as-int config type confusion.
- Aggregate contract suite: **16 passed**. Adjacent Track7 lifecycle/cutoff/spec/exit regression: **19 passed**. compileall, scoped Ruff F821/F401 and `git diff --check`: PASS. Separate batches; not a single integrated acceptance count.
- Authoritative broker-state reconciliation policy remains unapproved. No precedence/freshness/order-position matching policy was invented. No production persistence/Runtime restore wiring, broker calls, cancel/retry, real order/liquidation, KIS/REAL_VTS/Live/account API, collector restart, new data collection, Raw/Canonical/accepted data or manifest changes.
- Track7 strategy-state restart recovery and Full T4 X3/integrated acceptance remain OPEN.
