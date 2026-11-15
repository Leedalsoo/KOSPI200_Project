# Current Baseline v2 — SSOT

> Notion decision source: `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`. This repository file is the synchronized state snapshot. Detailed chronological updates are maintained separately in the A8 update log; the pre-rewrite SSOT is preserved in the linked archive.

## 기준 헤더 — 2026-11-15 (KST)

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

### K-1 — anchor 없는 계약의 UNAVAILABLE와 accepted synthetic contract의 관계

- 충돌 근거: Decision Log No.1469는 유효 anchor가 없는 계약을 `UNAVAILABLE`로 유지한다. No.1535는 실제 수집 데이터를 기반으로 생성·보완한 합성 데이터도 공식 프로젝트 검증 입력으로 인정한다. 11/14 S2 sidecar는 `SYNTHETIC_CONTRACT:S2:` namespace를 사용한다.
- 상태: 사용자 결정 대기. No.1469 또는 No.1535의 확정 상태를 임의 변경하지 않는다.
- 선택 A (추천): No.1535를 프로젝트 검증 데이터 자격에 우선 적용한다. 합성 계약은 명시적인 `SYNTHETIC_CONTRACT:` namespace와 provenance를 유지한 validation input으로 허용하되, 실제 KIS 계약 identity 또는 Production authoritative로 승격하지 않는다. No.1469의 anchor 요건은 실제 KIS authoritative identity/production 경계에 유지한다.
- 선택 B: No.1469의 anchor 없는 계약 `UNAVAILABLE`를 합성 계약에도 동일 적용한다. No.1535의 일반 데이터 인정은 계약 identity 생성에 적용하지 않는다.
- 선택 C: 계약 identity와 market observation 보완을 별도 정책으로 분리해 추가 Decision Log로 확정한다.
- 추천 사유: No.1535의 검증 데이터 인정 결정을 보존하면서 No.1469의 실제 KIS 계약 권위·Production 안전 경계를 약화시키지 않는다.
- 주의: A8 P1의 사용자 승인은 이 결정 카드의 선택을 대신하지 않는다.

## 4. 전략별 현재 상태

| 전략 | 현재 판정 | 검증 범위 및 잔여 제한 |
| --- | --- | --- |
| S1 | `PLUMBING_ONLY` | 단일 short CALL plumbing만. base strangle, multi-leg, exit, fee-inclusive PnL 미완료. |
| S2 | `PSB_UNVERIFIED` | 11/14 synthetic sidecar-backed validation-only Virtual Runtime에서 4-leg 순차 진입·가상체결 4/4 확인. 정책 fixture는 승인값이 아니다. U17 volatility boundary, U18 numeric stop/trailing ratios 및 net-premium denominator, U19 mismatch handling, U21 age/spread/fallback/tick, fee/slippage/margin 모델 미결. 12개 운영 위험한도 null 유지. 자연 신호·전략 성능·Production/Live 인증 아님. |
| S5 | `PSB_PASS_VALIDATION_ONLY_SYNTHETIC` (close-only) | 기존 포지션 close lifecycle 검증 범위. 신규 진입 BLOCKED. |
| S6 | `PSB_PASS` (rank 5 범위) | rank 6 및 나머지 matrix 조합 미완료. |
| S7 | `PSB_PASS` (validation-only synthetic) | 승인된 검증 subset 범위만. Production 승격 아님. |
| S8 | `PSB_PASS` (subset) | No.1398 다중계약 partial-fill 승격 미완료. |
| S9 | `PSB_PASS` (subset) | retry timer 재시작 복원 및 비대칭 체결 repair/flatten 미완료. |

### S2 11/14 검증 사실과 한계

- Market-calibrated synthetic sidecar v2: 21 candidate snapshots, 84 quote rows, 48 synthetic contract IDs.
- Validation-only Runtime 결과: signals 1, approved 1, routed 4, filled 4, rejected 0, runtime failures 0. 판정은 synthetic sidecar-backed Virtual Runtime 4-leg lifecycle에 한정한다.
- 다른 validation fixture의 quote age 5초, spread 0.20 및 12개 위험한도 등은 테스트 입력이며 사용자 승인 정책값이 아니다.
- Production `risk_profile.v1.json`의 12개 위험한도는 null로 유지하고 fail-closed 한다. 실제 주문 제출·flatten, KIS Live, REAL_VTS, 실계좌 API 호출은 금지한다.
- U18 Runtime exit lifecycle은 NOT_CERTIFIED. 순프리미엄 분모 의미, 수수료·슬리피지 및 quote freshness 증거가 해결되지 않았다.

## 5. Runtime·Risk·OMS 안전 경계

- 주문/체결/포지션/PnL의 identity·수량·group/leg/order/execution provenance를 대조한다. 상태 불명, partial fill, cancel race, late fill, mismatch는 fail-closed.
- Validation-only fixture는 테스트 입력으로 주입할 수 있으나 운영 기본값이나 production risk profile에 복사·승격하지 않는다.
- 운영 risk limits null, Live/REAL_VTS/order submission flags false를 유지한다. 실제 repair/flatten order submission은 별도 명시 승인 전 금지.
- KIS Live, REAL_VTS, 실계좌, 주문·정정·취소·잔고·증거금 API 호출 금지.
- 운영 설정, 권한, scheduler, `.env`, credential/token cache 변경·출력·커밋 금지.
- 신규 REST/WS 수집, collector 재시작, 예약작업 활성화 금지.
- Raw/Canonical/manifest/accepted dataset/synthetic tree는 read-only 입력으로 취급한다. 신규 산출물은 versioned 신규 경로만 사용한다.

## 6. 미해결 및 후속 단계

- K-1 정책 충돌: No.1469와 No.1535의 적용 범위에 대한 사용자 결정 필요.
- Canonical v2: 10/12·10/13의 ID 충돌 0 및 BSOP_HOUR/receive-time 분리는 산출물과 코드 경로에서 확인. 상위 manifest와 sidecar SHA 불일치는 여전히 미해결.
- S2: U17 volatility boundary, U18 stop/trailing ratios 및 net-premium denominator, U19 mismatch recovery, U21 quote age/spread/fallback/tick, fee/slippage/margin 모델 및 12개 위험한도.
- S2 실제 4-leg 데이터 후보 21건은 실제 동시·신선한 네 레그 호가 커버리지가 충분하지 않다. 합성 quote를 실제 quote로 주장하지 않는다.
- 백업·재생성 가능성, 단일본 데이터, C: 저장공간 위험은 P3에서 read-only로 확인하고 K-2를 제출한다.
- A8 후속 단계는 No.1546 진행표만 기준으로 한다. A5(No.1415), A6(No.1476), A7(No.1517)은 역사 참고다.

## 7. 확인된 근거

- No.1469: [anchor 없는 계약 UNAVAILABLE 및 validation-only synthetic 원칙](https://app.notion.com/p/4125f4f6eaa181d29441f757645d1ca9)
- No.1535: [기존 수집·합성 데이터 인정 및 추가 수집 중단 결정](https://app.notion.com/p/4185f4f6eaa18106ac1cc19962c109a7)
- No.1537: [S2 10/12·10/13 실제 4-leg 데이터 커버리지 검증](https://app.notion.com/p/4185f4f6eaa18177861be9960ef72097)
- No.1538: [S2 시장보정형 합성 4-leg 데이터 및 Runtime 검증](https://app.notion.com/p/4185f4f6eaa181689b07c6e919b30fc4)
- No.1544: [Project200 브랜치 통합 및 작업폴더 최신화](https://app.notion.com/p/4185f4f6eaa18184a3cfd728c080e34e)
- No.1545: [Project200 단일 기준 및 브랜치 보존·정리 원칙](https://app.notion.com/p/4185f4f6eaa1816b80c9ce740c8ba37d)
- A8 진행: [No.1546](https://app.notion.com/p/4195f4f6eaa1811a9da1d2072a9b3fd1)
- A8 변경 로그: [Current Baseline v2 update log](https://app.notion.com/p/4195f4f6eaa181869a49c12e5aa83076)
