기준일: 2026-11-09 (KST)
기준 브랜치: `cleanup/p2-quarantine-20261026`
기준 HEAD: `4bd9d67c24ccd4c450e735031b60809b6a6c4f1a`
상태: A6 C03에서 작성한 단일 기준 문서. 이 문서의 SHA-256은 로컬 파일과 Notion 본문이 동일해야 한다.

## 1. 권위 및 적용 순서

1. 사용자의 직접 지시
2. 본 문서 Current Baseline v2
3. 본 문서가 유효하다고 명시한 확정 Decision Log 항목
4. 기준 브랜치의 `AGENTS.md`
5. 현재 코드·데이터
6. 신규 검증 결과

과거 Q&A, 구 Current Baseline, 승인되지 않은 초안·이전 지시문은 역사 참고 자료다. 본 문서와 충돌하면 본 문서를 우선하며, 확정 Decision Log의 충돌은 임의 변경하지 않고 C04 결정 카드로 올린다.

## 2. 프로젝트 범위 및 안전 경계

- Q25 검증은 PSB(가상·검증 전용) 기준이다. `PSB_PASS`는 해당 validation-only 범위의 통과이며 Production/실거래 준비 완료를 뜻하지 않는다.
- 전략 대상 범위: S1, S2, S5, S6, S7, S8, S9. S3/S4는 현재 대상에서 제외한다.
- A6 C01–C10 기준 정리 완료 전 A5 전략 단계 실행은 일시 중지한다. A6의 bare `승인`은 다음 대기 C단계 하나만 실행하고 멈춘다.
- KIS Live, REAL_VTS, 실계좌, 실주문·정정·취소·잔고·증거금 API 호출 금지.
- 운영 설정, .env/비밀정보, 권한, 스케줄러, collector 및 원본 데이터 변경 금지. 원본 작업폴더의 기존 dirty/untracked 항목은 보존한다.
- Git 작업은 격리 worktree에서 수행한다. 허용 대상은 `cleanup/p2-quarantine-20261026`뿐이며 non-force push만 허용한다. `Project200`/ `master` push, force push, merge, history rewrite 금지.
- 삭제 금지. Notion 역사 기록의 상태 배너·이동·대체 표시는 C04 승인 또는 사용자 명시 승인 범위에서만 수행한다.

## 3. 현재 기준선 및 검증 원칙

- 기준 HEAD: `4bd9d67c24ccd4c450e735031b60809b6a6c4f1a`; 커밋 메시지: `fix(q25): gate retired S5 entries and validate anchored quotes`.
- S5 신규 진입은 BLOCKED. No.1168의 OPTION BUY 2-only 진입안은 폐기 상태이며 재사용하지 않는다. 이미 열린 포지션의 close lifecycle은 보존한다.
- Synthetic/derived 입력은 명시적인 유효 KIS anchor, provenance, manifest 및 validation-only 경계가 있을 때만 보완 검증에 사용한다. `SYNTHETIC:DERIVED_SCENARIO`를 Production authoritative input으로 승격하지 않는다. anchor 없는 계약은 `UNAVAILABLE`.
- KIS-only authoritative runtime data 원칙 유지. KIS multiplier 등 누락 필드를 상수·KRX·다른 상품으로 대체하지 않는다.
- PSB 결과는 전략·시나리오·입력·런타임 범위를 구분해 기록한다. Scenario catalog 생성 PASS, plumbing PASS, natural-signal Runtime E2E PASS는 서로 대체할 수 없다.
- FAST/DETAILED 동등성은 해당 실행에서 명시적으로 검증된 경우에만 PASS로 기록한다.

## 4. 전략별 현재 상태

| 전략 | 기준 및 확인된 상태 | 제한·미완료 |
| --- | --- | --- |
| S1 | A5 S15a signal-generation-only 완료; S15b 단일 OPTION leg 자연신호 Virtual Runtime 검증은 validation-only PSB_PASS. | S15b 전체 PLUMBING_ONLY. 단일 short CALL 범위이며 multi-leg/base strangle, fee schedule, exit/realized PnL, Production OPTION route 미검증. |
| S2 | A5 S02 4조합 matrix에서 FAST/DETAILED 동등 및 Rank 5 검증. | Rank 6 Runtime 연결 미확인, PSB_UNVERIFIED. |
| S5 | No.1473 gap matrix BLOCKED_SPEC/PSB_UNVERIFIED. No.1474 최신 코드 정렬 후에도 신규 진입 BLOCKED. S21 시나리오 카탈로그 54개 생성(24 DESIGNED / 20 BLOCKED_SPEC / 10 BLOCKED_INPUT). | S21은 catalog generation only, Runtime PASS 아님. No.1132/1134 grouped terminal close 및 authoritative remaining-quantity gap 존재. S22 대기. |
| S6 | A5 S03 validation-only synthetic take-profit/trailing/15:10 force-close E2E PSB_PASS. | S02 Rank 6 미연결 및 synthetic contract identity owner 미해결. |
| S7 | A5 S06–S08 validation-only synthetic Runtime E2E/exit/fee-aware 결과 PSB_PASS. | 운영·Production 검증 아님. 각 단계의 원본 기록 및 제한을 유지. |
| S8 | S10 validation-only synthetic exit E2E PSB_PASS. S11b natural-signal retry Runtime E2E PSB_PASS_VALIDATION_ONLY_SYNTHETIC. | 600초 TIMEOUT_10M + terminal CANCELLED 확인 후에만 레그별 최대 3회, 3거래일 창, 3일차 15:00 cutoff. 부분체결·일반 취소·거절·상태 불명 blind retry 금지. |
| S9 | No.1439 승인 독립형 v0.3. ATM PUT+CALL BUY/BUY, 15:00 KST 진입, 다음 거래일 공식 시가와 전일 공식 종가의 절대 변동률 1% 기준으로 양 레그 청산 또는 손절. A5 S19 validation-only synthetic E2E 및 cold-start 복구 증거 있음. | 야간거래 18:00–06:00 사용 안 함. 공식 KIS multiplier/거래가능 여부/전일 종가/익일 시가/옵션 호가/거래일 달력은 미확인. 승인 명세의 미확정 파라미터를 임의 확정하지 않음. |

## 5. 데이터·계약·시간 기준

- WS 원본은 provenance를 유지한 원본 증거로 취급한다. REST 성공은 WS 지원 또는 동시시점 tick 대체의 증거가 아니다. REST, WS, REAL_VTS, SYNTHETIC, DERIVED_SCENARIO를 서로 다른 source/provenance로 구분한다.
- No.1424의 2026-11-06 WS raw: 223,609행, manifest record_count 및 SHA-256 일치. H0IOASP0 200,302건, H0UPCNT0 23,307건, 고유 instrument 87개(지수 1 + 표준 옵션 86개). 해당 파티션에는 H0IOCNT0 프레임이 없다.
- No.1424의 REST option probe는 응답/필드 존재 확인에는 유효하나 source timestamp/freshness가 부족한 사례가 있어 runtime/replay fresh quote로 승격하지 않는다. REST minute bars는 확인된 미니 옵션 데이터이므로 표준 옵션 WS tick의 대체 자료로 사용하지 않는다.
- Canonical 관측 데이터의 observation_id 중복 및 observed_at/received_at 시간 의미 문제는 해결된 것으로 간주하지 않는다. replay eligibility는 별도 증거 전까지 미확인이다.
- 표준 옵션과 Mini 옵션, Mini Futures, KOSPI200 지수는 서로 다른 instrument identity다. 정확한 KIS contract identity·expiry·multiplier·tradability·source timestamp를 확인할 수 없으면 BLOCKED/UNAVAILABLE로 둔다.
- 거래일·휴장일·공식 시가/종가의 authoritative source와 자동화 적용 여부는 미확인 항목으로 남긴다. 추정 달력·가격을 authoritative input으로 사용하지 않는다.

## 6. Runtime·Risk·OMS 공통 경계

- 주문/체결/포지션/손익의 authoritative linkage는 contract/leg/order/group/quantity 및 execution provenance를 대조해야 한다.
- Partial fill, cancel race, late fill, unknown terminal state는 대사 전 신규 주문·blind retry를 차단하고 fail-closed 한다.
- S8 retry 정책은 No.1397 확정 범위만 적용한다. S9의 BUY/BUY timeout·복구 정책은 별도 S9 최신 승인·구현 기록을 따른다. 두 전략의 retry 정책을 혼용하지 않는다.
- 운영 RiskConfig, runtime_config_verified, risk_limits_available의 fail-closed 기본값을 임의 완화하지 않는다.
- Virtual Runtime의 validation-only synthetic calendar/quote/orderbook은 검증 입력이며 Production data source가 아니다.

## 7. A6 정리 단계

C01 current snapshot 및 C02 old-baseline findings 완료. C03 본 SSOT 작성. 이후 C04 Supersession Register/결정 카드, C05 Notion 역사 기록 정리, C06 [AGENTS.md](http://AGENTS.md), C07 [README.md](http://README.md), C08 테스트·주석 정책 정합성 검토, C09 verification gate, C10 A5 진행표 동기화 및 대상 브랜치 non-force push 순서로 진행한다. 각 승인당 대기 단계 하나만 실행한다.

## 8. 확인된 근거 페이지

- [[No.1424 답변내용요약] VTS WS 부족 데이터의 REST 보완 가능성 재검증 (2026-11-07)](https://app.notion.com/p/4105f4f6eaa181f29d5ad6f1b5582305)
- [[No.1397 답변내용요약] Q25 S8 10분 간격·최대 3회 Runtime 재시도 구현 및 검증 (2026-11-04)](https://app.notion.com/p/40e5f4f6eaa18132a8c6d16b8a769af7)
- [[No.1439 답변내용요약] S9 독립형 전략 명세 v0.3 사용자 승인 (2026-11-08)](https://app.notion.com/p/4115f4f6eaa181c88075f52d6cd57bc0)
- [[No.1473 답변내용요약] Q25 A5 S20 Strategy 5 명세-코드 Gap Matrix (2026-11-09)](https://app.notion.com/p/4135f4f6eaa18140ad65fefdcf46eaeb)
- [[No.1474 답변내용요약] Q25 S5 최신 정책 코드 정렬 및 validation-only 입력 검증 (2026-11-09)](https://app.notion.com/p/4135f4f6eaa18154b762eb3e98624981)
- [[No.1475 답변내용요약] Q25 A5 S21 Strategy 5 시나리오 설계·생성 (2026-11-09)](https://app.notion.com/p/4135f4f6eaa1818dbe9cedf4d48f5d18)
- [[No.1415 답변내용요약] Q25 A5 단계 진행표 (2026-11-06)](https://app.notion.com/p/4105f4f6eaa181e2aa67dfa7ec9612af)
- [[No.1476 답변내용요약] Q25 A6 기준 정리 진행표 (2026-11-09)](https://app.notion.com/p/4135f4f6eaa1817fb644c2280e813de1)

## 9. 미확인 및 별도 결정 필요

- KIS 공식 contract multiplier, tradability, option quote freshness, previous close/next open, authoritative holiday/calendar source.
- Canonical observation identity/time semantics 및 replay eligibility.
- S2 Rank 6 연결, S1 multi-leg/Production route, S5 신규 진입/hedge/re-entry 정책 및 S22 gap 정렬, S9 미확정 정책 파라미터.
- 3개월 자동화·scheduler·Control Tower 확장 및 Calendar/휴장일 자동화의 현재 유효성. 스케줄러 변경은 별도 명시 승인 전 금지.