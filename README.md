# KOSPI200 Project200

KOSPI200 옵션 데이터·전략·가상 검증 프로젝트입니다. 현재 검증 기준과 작업 범위는 **Current Baseline v2**를 단일 SSOT로 사용합니다.

- 기준 문서: [`docs/CURRENT_BASELINE.md`](docs/CURRENT_BASELINE.md)
- 작업·안전 지침: [`AGENTS.md`](AGENTS.md)
- 기준 Notion: [Current Baseline v2 — SSOT (2026-11-09)](https://app.notion.com/p/4135f4f6eaa181f7ac42dea70e10fa42)
- 정리 진행표: [Q25 A6 기준 정리 진행표 — No.1476](https://app.notion.com/p/4135f4f6eaa1817fb644c2280e813de1)

## 현재 범위와 검증 상태

Q25의 현재 검증은 PSB(validation-only) 범위입니다. `PSB_PASS`는 명시된 가상·합성 입력과 검증 경로의 결과이며 Production, 실계좌 또는 Live 준비 완료를 뜻하지 않습니다. 현재 전략 범위는 S1, S2, S5, S6, S7, S8, S9이며 S3/S4는 제외합니다.

| 전략 | 기준 상태 | 제한 사항 |
|---|---|---|
| S1 | S15a signal-only 완료; S15b 단일 short CALL plumbing 검증 `PSB_PASS` | 단일 leg validation-only. Multi-leg·Production route 미검증 |
| S2 | Rank 5 검증 | Rank 6 Runtime 미연결, `PSB_UNVERIFIED` |
| S5 | 신규 진입 `BLOCKED`; S21 시나리오 카탈로그 54건 생성 | 카탈로그 생성은 Runtime PASS가 아님; S22 대기 |
| S6 | Synthetic validation-only E2E `PSB_PASS` | Production 검증 아님 |
| S7 | Synthetic validation-only Runtime/exit/fee-aware E2E `PSB_PASS` | Production 검증 아님 |
| S8 | S10 exit E2E `PSB_PASS`; S11b natural-signal retry `PSB_PASS_VALIDATION_ONLY_SYNTHETIC` | No.1397의 제한된 timeout/retry 정책 적용 |
| S9 | No.1439 독립 v0.3 승인 기준: ATM PUT+CALL BUY/BUY, 15:00 진입 | 야간 세션 미사용; 미확정 KIS 계약·가격 입력은 fail-closed |

전략별 세부 상태, 데이터 범위, 근거 및 미해결 항목은 Current Baseline v2를 확인하십시오. 시나리오 카탈로그, fixture 관찰, 단일 plumbing 검증만으로 자연 신호 기반 Runtime E2E 완료를 주장하지 않습니다.

## 데이터와 검증 원칙

- Runtime/contract의 authoritative source는 공식 KIS API 및 공식 KIS 종목 Master 범위입니다. KIS 값의 누락을 다른 공급자나 추정값으로 대체하지 않습니다.
- REST, WebSocket, REAL_VTS, SYNTHETIC, DERIVED_SCENARIO는 source/provenance를 구분합니다. Synthetic/derived 입력은 유효한 KIS anchor, provenance, manifest/hash가 보존된 validation-only 보완 검증에만 사용하며 Production authoritative 입력으로 취급하지 않습니다.
- 관측 identity/time semantics 및 replay eligibility가 입증되지 않은 데이터는 검증 가능하다고 간주하지 않습니다.
- 계약 identity, expiry, strike, option type, broker symbol, multiplier, tradability 및 source timestamp가 확인되지 않으면 `UNAVAILABLE` 또는 구체적인 `BLOCKED_*`로 fail-closed 처리합니다.
- `PSB_PASS`, `PLUMBING_ONLY`, `PSB_UNVERIFIED`, `BLOCKED_*`는 각각 검증 범위를 구분해 기록합니다. 과거 테스트 결과는 현재 기준의 재검증을 대신하지 않습니다.

## 안전 경계

- KIS Live, REAL_VTS, 실계좌의 주문·정정·취소·잔고·체결·증거금 API 호출은 금지합니다.
- credential/secret, `.env`, 운영 RiskConfig, runtime 권한, scheduler, collector 설정 및 원본 데이터를 임의로 변경하지 않습니다.
- 검증 산출물은 원본과 분리된 경로에 저장하고, 원본 데이터 및 기존 dirty/untracked 작업물을 보존합니다.
- Git 작업은 격리 worktree에서 수행합니다. 승인된 대상은 `cleanup/p2-quarantine-20261026`이며 non-force push만 허용됩니다. `Project200`/`master` push, force push, merge 및 history rewrite는 금지됩니다.
- 불명확한 authoritative source, 상충하는 승인 결정, 원본 손상 위험 또는 운영 설정 변경 필요성이 발견되면 중단하고 보고합니다.

## 작업 절차

세부 작업 순서와 승인 규칙은 [`AGENTS.md`](AGENTS.md)를 따릅니다. A6 C01–C10 기준 정리 중에는 A5 전략 실행 단계를 재개하지 않습니다. A6 승인 한 번은 대기 중인 C 단계 하나만 실행하며, 해당 단계가 끝나면 멈춥니다.

Windows에서 Python 명령은 `py`를 사용합니다. 실제 실행 명령, 출력, 종료 코드 및 관련 증거를 기록하고, 실행하지 않은 검증을 완료한 것으로 보고하지 않습니다.

## 별도 결정 대기 항목

3개월 자동 E2E/Replay, scheduler 및 Control Tower 운영 범위와 Calendar/휴일 자동화의 세부 요구사항은 현재 확정된 작업 요건으로 간주하지 않습니다. A6 결정 카드 DC-03/DC-04의 사용자 결정 전에는 이를 근거로 운영 설정이나 scheduler를 변경하지 않습니다.

---

이 README는 프로젝트 개요입니다. 최신 기준은 Current Baseline v2이며, 충돌 시 README의 설명보다 SSOT와 `AGENTS.md`의 우선순위를 따릅니다.
