# Current Baseline v2 — SSOT

> Mirrored from Notion page `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`. Notion remains the decision source; this file is the repository snapshot used for SHA-linked traceability.

## 최신 상태 갱신 — C1·C2·C3 완료 (2026-11-12)

- A7 C1 archive 통합은 완료됐다. C1 merge commit은 `d1aef6aab7ce49ec2ad83a837f93c199f2d7c23f`이다. C1 push 당시 local/remote SHA가 일치했으며, C2 문서 복원 후 최신 통합 브랜치 SHA는 C2 종료 기록(No.1529)을 따른다.
- C2 문서 복원 완료. C3 원본 dirty 작업폴더 읽기 전용 분류 완료: 원본 224 status entries, HEAD 및 파일 상태 보존. 상세는 No.1530 및 C3 repo report 참조.
- 원본 작업폴더 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` 및 dirty/untracked 224건은 보존한다.
- S2 판정은 `PSB_UNVERIFIED`로 유지한다.

---

기준일: 2026-11-12 (KST)
기준 브랜치: `cleanup/p2-quarantine-20261026`
기준 HEAD: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`
작업 기준: 로컬 작업폴더 HEAD. S2 통합 작업 브랜치 `integrate/q25-s2-20261111`는 A2에서 생성했고, C3 종료 후 현재 통합 HEAD는 `916fd4feadd36f7dcbc63aeb86a65e24cf0bc400`이다.
CB2 ID: `4135f4f6-eaa1-81f7-ac42-dea70e10fa42`
Status: A1/A2/A3/B1/B2/B3/B4/C1/C2/C3 completed. C4 is the next pending step and requires separate user approval; C2 document restoration and C3 read-only dirty-tree classification are complete; B1/B2/B3/B4 and X+1 are complete. S2 remains PSB\\\_UNVERIFIED; no S2 natural-signal Runtime E2E PASS is claimed.

## 코드 근거 위치표 (A7, 2026-11-11)

| 작업 구간 | 근거 위치 | 상태 |
| --- | --- | --- |
| S26 | archive commit `46bc639bb87e5d69e72d94abcd2d24892d5d1f1c` | commit object 확인 |
| S27 | archive commit `f1638baf0bfd0592547dbb2eb3e2d2ed7fcfa4be` | commit object 확인 |
| S28 | archive commit `3cc0e677848f99315e002b448c771ca2ffc72813` | commit object 확인 |
| S30–S33 | `C:\Users\white\AppData\Local\Temp\Q25_A5_S22_S5_GROUP_CLOSE_20261109`, branch `q25-a5-s22-s5-group-close-20261109`, preservation commit `fdda3617604e4007638fddeb3088727f09171ee9` | 56개 파일 자체 브랜치에 보존 커밋 완료; S2 관련 38개 파일을 `integrate/q25-s2-20261111`의 `c526b9a5f5465828372a99862b0c7a9c6fb637c0`에 선별 이식 |

## 1. 권위 및 적용 순서

1. 사용자의 직접 지시
2. 본 문서 Current Baseline v2
3. 본 문서 §8에 연결된 사용자 확정 Decision Log 및 승인 명세 (No.1491–1505)
4. 기준 브랜치의 `AGENTS.md`
5. 현재 코드·데이터
6. 신규 검증 결과

과거 Q&A, 구 Current Baseline, 승인되지 않은 초안·이전 지시문은 역사 참고 자료다. 본 문서와 충돌하면 본 문서를 우선하며, 확정 Decision Log의 충돌은 임의 변경하지 않고 C04 결정 카드로 올린다.

## 2. 프로젝트 범위 및 안전 경계

- Q25 검증은 PSB(가상·검증 전용) 기준이다. `PSB_PASS`는 해당 validation-only 범위의 통과이며 Production/실거래 준비 완료를 뜻하지 않는다.
- 전략 대상 범위: S1, S2, S5, S6, S7, S8, S9. S3/S4는 현재 대상에서 제외한다.
- A6 C01–C10 기준 정리는 2026-11-10 완료했다. A7에 따라 S2 트랙(A1→A2→A3→B1→B2→B3→B4)을 먼저 진행하고, 통합 마무리 C1–C5는 S2를 막지 않는 후속 트랙으로 둔다. 단계별 사용자 승인 없이 자동 재개·연속 실행하지 않는다.
- KIS Live, REAL\_VTS, 실계좌, 실주문·정정·취소·잔고·증거금 API 호출 금지.
- 운영 설정, .env/비밀정보, 권한, 스케줄러, collector 및 원본 데이터 변경 금지. 원본 작업폴더의 기존 dirty/untracked 항목은 보존한다.
- 작업은 로컬 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`에서 만든 격리 worktree의 `integrate/q25-s2-20261111`에서 수행한다. 원본 작업폴더에서 pull/checkout/reset/clean/stash/merge를 하지 않는다. archive는 읽기·cherry-pick만 허용하고, 임시 worktree 변경은 자체 브랜치에 먼저 커밋해 보존한 뒤 필요한 파일만 선별 이식한다.
- 검증 후 로컬 커밋하고, A7 진행표에서 푸시 단계로 지정된 경우에만 동일 커밋을 `cleanup/p2-quarantine-20261026`에 non-force fast-forward 푸시한다. `Project200`/`master` push/merge, force push, history rewrite 금지.
- 삭제 금지. Notion 역사 기록의 상태 배너·이동·대체 표시는 C04 승인 또는 사용자 명시 승인 범위에서만 수행한다.

## 3. 현재 기준선 및 검증 원칙

- 기준 HEAD: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` (No.1515에서 확정한 로컬 작업폴더 HEAD). `3cc0e677848f99315e002b448c771ca2ffc72813`는 과거 SSOT 헤더 기준으로만 보존한다. S28 통합 회귀 보고서 SHA-256은 `593CDB1851C1F888ECF1DDCE80550966C9C441A726BA9ED22A038643C210E79A`이다.
- S2 통합 명세 v0.5 및 지원 문서 3종은 No.1500에서 사용자 승인되었다. 승인은 명세/정책 기준에 한정되며 코드 구현, Runtime/OMS 연결, Runtime E2E, Replay 또는 주문 실행 승인이 아니다.
- S28 baseline verdict remains COMPLETED\_WITH\_BLOCKERS / PSB\_UNVERIFIED; not production-ready. After S32, full pytest is 546 passed / 29 failed / 1 skipped; the 29 failures remain existing S5/S7/S8 synthetic dataset/manifest failures.
- S5 신규 진입은 BLOCKED. No.1168의 OPTION BUY 2-only 진입안은 폐기 상태이며 재사용하지 않는다. 이미 열린 포지션의 close lifecycle은 보존한다.
- Synthetic/derived 입력은 명시적인 유효 KIS anchor, provenance, manifest 및 validation-only 경계가 있을 때만 보완 검증에 사용한다. `SYNTHETIC:DERIVED_SCENARIO`를 Production authoritative input으로 승격하지 않는다. anchor 없는 계약은 `UNAVAILABLE`.
- KIS-only authoritative runtime data rule remains. Use the KIS official product specification for multiplier, monthly expiry rule and option tick rules with explicit source URL and master-hash binding. Never substitute unsupported constants, KRX data or another product.
- PSB 결과는 전략·시나리오·입력·런타임 범위를 구분해 기록한다. Scenario catalog 생성 PASS, plumbing PASS, natural-signal Runtime E2E PASS는 서로 대체할 수 없다.
- FAST/DETAILED 동등성은 해당 실행에서 명시적으로 검증된 경우에만 PASS로 기록한다.

## 4. 전략별 현재 상태

| 전략 | 기준 및 확인된 상태 | 제한·미완료 |
| --- | --- | --- |
| S1 | S28 최종 판정 PLUMBING\_ONLY. S15b 단일 short CALL 자연신호 validation-only E2E 및 FAST/DETAILED parity 범위. | Base strangle/multi-leg/exit/fee-inclusive PnL/Production OPTION route 미검증. |
| S2 | No.1500 approved S2 spec v0.5. U17 monthly STANDARD 4-leg identity binding and U20 sequential validation-only progression implemented. S33 adds BID/ASK MID group marks, quote provenance, Runtime PnL snapshot feed, and S2 TRAP\_CLOSE terminal group accounting; 115 targeted tests across 12 files PASS. KIS master/product spec resolve all four identities, expiry 20261112 and multiplier 250000. | PSB\_UNVERIFIED. Net PnL/exit remains blocked by fee/slippage and quote-freshness evidence plus numeric stop/trailing ratios. U16 retry schedule/repricing and validation-only fail-closed repair state machine are implemented; actual order submission/flatten remains unapproved. U19 validation-only durable restart-recovery gate and U21/U18 validation-only evaluators are implemented. Production quote age/spread/fallback/tick rules, current tradability/volatility boundary, broker snapshot provider and automatic Runtime restore remain unverified. B4 Runtime E2E and FAST/DETAILED parity executed on 2026-11-12; no natural signals were observed across 7 trading dates, so no natural-signal PASS is claimed. S2 remains PSB\_UNVERIFIED. |
| S5 | S28 최종 판정 PSB\_PASS\_VALIDATION\_ONLY\_SYNTHETIC (close-only). StrategyHub natural exit → Virtual close fill → PositionLot flat 및 FAST/DETAILED parity, focused 51 tests. | Seed는 synthetic이며 실제 과거 fill이 아니다. 신규 진입은 계속 BLOCKED. |
| S6 | S28 PSB\_PASS (S03 검증 범위). first\_rank=5 / per\_order 조건의 take-profit·trailing·15:10 force-close 검증. | Rank 6 및 나머지 matrix 조합, authoritative contract identity/calendar/운영 설정 미검증. |
| S7 | S28 PSB\_PASS (validation-only synthetic). 자연 StrategyHub 신호 8건, FAST/DETAILED parity, 월·목 만기별 Position/PnL 대사. | Synthetic identity/expiry/calendar 및 fee 범위 한정. Production 승격 아님. |
| S8 | S28 PSB\_PASS (validation-only synthetic subset). STOP/TRAILING/EXPIRY exit 및 No.1397 정책 기반 자연신호 retry E2E. | No.1398 multi-contract partial-fill은 PLUMBING\_ONLY. 일부 정책 및 계약 데이터 미확인. |
| S9 | S28 PSB\_PASS (validation-only synthetic subset). 독립형 ATM PUT+CALL STOP\_LOSS, cold-start 복구, 5분 timeout/retry natural-signal E2E 및 73 tests. | Retry timer의 프로세스 재시작 복원, 비대칭 fill/reject 후 repair/flatten, 공식 KIS 계약·시장 데이터 미확인. |

## 5. 데이터·계약·시간 기준

- WS 원본은 provenance를 유지한 원본 증거로 취급한다. REST 성공은 WS 지원 또는 동시시점 tick 대체의 증거가 아니다. REST, WS, REAL\_VTS, SYNTHETIC, DERIVED\_SCENARIO를 서로 다른 source/provenance로 구분한다.
- No.1424의 2026-11-06 WS raw: 223,609행, manifest record\_count 및 SHA-256 일치. H0IOASP0 200,302건, H0UPCNT0 23,307건, 고유 instrument 87개(지수 1 + 표준 옵션 86개). 해당 파티션에는 H0IOCNT0 프레임이 없다.
- No.1424의 REST option probe는 응답/필드 존재 확인에는 유효하나 source timestamp/freshness가 부족한 사례가 있어 runtime/replay fresh quote로 승격하지 않는다. REST minute bars는 확인된 미니 옵션 데이터이므로 표준 옵션 WS tick의 대체 자료로 사용하지 않는다.
- Canonical 관측 데이터의 observation\_id 중복 및 observed\_at/received\_at 시간 의미 문제는 해결된 것으로 간주하지 않는다. replay eligibility는 별도 증거 전까지 미확인이다.
- 표준 옵션과 Mini 옵션, Mini Futures, KOSPI200 지수는 서로 다른 instrument identity다. 정확한 KIS contract identity·expiry·multiplier·tradability·source timestamp를 확인할 수 없으면 BLOCKED/UNAVAILABLE로 둔다.
- 거래일·휴장일·공식 시가/종가의 authoritative source와 자동화 적용 여부는 미확인 항목으로 남긴다. 추정 달력·가격을 authoritative input으로 사용하지 않는다.

## 6. Runtime·Risk·OMS 공통 경계

- 주문/체결/포지션/손익의 authoritative linkage는 contract/leg/order/group/quantity 및 execution provenance를 대조해야 한다.
- Partial fill, cancel race, late fill, unknown terminal state는 대사 전 신규 주문·blind retry를 차단하고 fail-closed 한다.
- S8 retry 정책은 No.1397 확정 범위만 적용한다. S9의 BUY/BUY timeout·복구 정책은 별도 S9 최신 승인·구현 기록을 따른다. 두 전략의 retry 정책을 혼용하지 않는다.
- 운영 RiskConfig, runtime\_config\_verified, risk\_limits\_available의 fail-closed 기본값을 임의 완화하지 않는다.
- Virtual Runtime의 validation-only synthetic calendar/quote/orderbook은 검증 입력이며 Production data source가 아니다.
- S2 승인 명세의 4-leg 진입 순서는 PUT BUY → CALL BUY → PUT SELL → CALL SELL이다. 그룹은 4개 레그의 목표 수량이 모두 체결되고 대사된 뒤에만 ACTIVE가 된다.
- S2-U16: 부분체결/거절/취소 경합 시 원주문 취소·종료 상태, 체결 및 포지션을 먼저 대사하고 확인된 실제 체결량 기준으로 부족 수량만 보정한다. 상태 불명은 RECONCILIATION\_REQUIRED로 차단한다. 보정 가격은 BID/ASK 기반 지정가, 최초 보정 주문 이후 추가 재시도 최대 3회, 최초 보정 제출부터 최대 120초를 함께 적용한다. 재시도 전 재대사하며, 최종 실패 시 기체결 레그 전체 청산 정책 및 그룹 차단을 적용한다. 실제 청산 주문 제출은 승인되지 않았다.
- S2-U17: ATM tie selects the lower listed strike at or below index price. Four-leg identities must be unique STANDARD/MONTHLY contracts with exact expiry/type/strike and KIS standard multiplier. KIS official product specification defines monthly expiry as the second Thursday (previous trading day if holiday), standard multiplier 250000, and premium tick 0.05 for premiums >=10. The four current contracts resolve to expiry 20261112; all four strikes are on the near-month 2.5-point grid. Current tradability and volatility-boundary evidence remain unverified.
- S2-U18: Option-group PnL uses BID/ASK MID and initial group net premium received as denominator; fees and slippage must be included in realized and unrealized PnL. S33 wires MID marks, quote provenance, Runtime group-PnL feed, and TRAP\_CLOSE terminal path. Fee/slippage evidence, quote-freshness verification, and numeric stop-loss/trailing ratios remain unresolved; production net PnL and exit stay BLOCKED.
- S2-U19: 재시작 시 브로커/거래소 보유 포지션이 authoritative이며 저장 execution ledger는 보조 근거다. 실제 포지션과 ledger 불일치 시 조정·중단·재개 절차는 미확정이다.
- S2-U20: Runtime tick processor invokes sequential progression after pending-order reconciliation. Advance only after the previous leg is fully FILLED and reconciled; CANCELLED zero-fill requires terminal cancel, no pending order, no group lot and flat VSSF account position. Partial/reject/unknown/mixed terminal states fail closed. The final zero-fill does not complete the group.
- S2-U21: Use conservative fallback when BID/ASK is missing, stale, or spread exceeds the approved limit; block if no valid fallback exists. S33 stores raw BID/ASK and quote timestamp for MID marks but does not assert freshness. Maximum quote age, spread limit/unit, fallback formula/priority, and tick rounding remain unresolved.
- S2 U16 보정 재시도 간격 및 가격 재산정 시점은 확정됐다(T0 기준 T+30/T+60/T+90초, deadline T+120초; 각 재시도 직전 최신 유효 BID/ASK로 재산정). 미확정 quote 정책 입력이 누락되면 운영 기본값 null로 주문 경로를 차단한다. 정책 결정은 구현·테스트·Runtime/OMS 연결 또는 실제 주문 실행을 승인하지 않는다.

## 7. A6 완료 및 A7 실행 순서

A6 C01–C10 전체 완료(2026-11-10). C09 verification gate 및 C10 A5 진행표 동기화까지 완료되었다. A6 완료 자체는 S2 구현·Runtime 검증 승인을 의미하지 않는다. A7에 따라 S2 A1→A2→A3→B1→B2→B3→B4 순서로 진행하며, 각 단계는 사용자 승인 후 하나씩 수행한다. 현재 A1/A2/A3/B1/B2/B3/B4/C1 완료했고 다음 대기 단계는 C2다. C1 병합 커밋은 d1aef6aab7ce49ec2ad83a837f93c199f2d7c23f이�� 원격 cleanup/p2-quarantine-20261026과 SHA가 일치한다. X+1 registry strategy\_ids 호환성 결함은 2026-11-11 커밋 771894387adb1cbd6063495000ee9405f20b0fe2에서 해결했다. B4는 명시적 S2 strategy selection으로 실행했다. 전체 registry의 Track1 manifest/code version mismatch는 C1에서 manifest 1.2.0 정합 및 default registry 9개 전략 등록 확인으로 해소했다. 통합 마무리 C1–C5는 S2를 막지 않는 후속 트랙이다.

## 8. 확인된 근거 페이지

- [No.1490 S28 통합 회귀 및 최종 판정](https://app.notion.com/p/4145f4f6eaa181b3a60afebfc43c6172)
- [No.1500 S2 통합 명세 v0.5 사용자 승인](https://app.notion.com/p/4145f4f6eaa181a0b13bc0b1772566b7)
- [No.1491 S2-U16 부분체결·거절·취소 경합](https://app.notion.com/p/4145f4f6eaa1818fbba7c50fc36a87d2)
- [No.1492 S2-U17 ATM 행사가 동률](https://app.notion.com/p/4145f4f6eaa1817e895cc03765ad2d9c)
- [No.1493 S2-U18 MID 평가가격](https://app.notion.com/p/4145f4f6eaa1811b9231fc2089a72fcf)
- [No.1494 S2-U18 순비용 분모](https://app.notion.com/p/4145f4f6eaa181e3a6fcec17365f29d3)
- [No.1495 S2-U18 수수료·슬리피지](https://app.notion.com/p/4145f4f6eaa181dda024e87aeb1c53e7)
- [No.1496 S2-U18 손절·트레일링 구조](https://app.notion.com/p/4145f4f6eaa18114aaa9f7c2ca3f1ed3)
- [No.1497 S2-U19 재시작 복구 기준](https://app.notion.com/p/4145f4f6eaa18147ac20e69e4fcbe587)
- [No.1498 S2-U20 0체결 취소 후 레그 진행](https://app.notion.com/p/4145f4f6eaa1817c8857d9fa3b3cba2e)
- [No.1499 S2-U21 호가 유효성·주문가격](https://app.notion.com/p/4145f4f6eaa181e58455eee3be0e5a20)
- [No.1501 U16 보정 실패 시 전체 청산](https://app.notion.com/p/4145f4f6eaa181f8b05ff3b991aed47c)
- [No.1502 U16 재시도 한도·실패 판정](https://app.notion.com/p/4145f4f6eaa1812ab61af69d78fbf8b5)
- [No.1503 U16 최대 3회 추가 재시도](https://app.notion.com/p/4145f4f6eaa181d7bef1c0d6e939568d)
- [No.1504 U16 최대 120초 처리시간](https://app.notion.com/p/4145f4f6eaa181009e25e377b8d2129a)
- [No.1505 U16 BID/ASK 기반 보완 지정가](https://app.notion.com/p/4145f4f6eaa1816289d9f43ee2babeca)
- [No.1511 S2 U17/U20 validation-only implementation and KIS source audit](https://app.notion.com/p/4145f4f6eaa18113bf97ee10f0d282e4)
- [No.1512 S2 KIS product specification expiry and multiplier resolution](https://app.notion.com/p/4145f4f6eaa181b88968de6dc8e2df59)
- [No.1513 S2 group PnL MID marks and Runtime terminal close wiring](https://app.notion.com/p/4145f4f6eaa181a78f06e227aae77427)
- [No.1424 VTS WS 부족 데이터의 REST 보완 가능성 재검증](https://app.notion.com/p/4105f4f6eaa181f29d5ad6f1b5582305)
- [No.1397 S8 10분 간격·최대 3회 Runtime 재시도](https://app.notion.com/p/40e5f4f6eaa18132a8c6d16b8a769af7)
- [No.1439 S9 독립형 전략 명세 v0.3 사용자 승인](https://app.notion.com/p/4115f4f6eaa181c88075f52d6cd57bc0)
- [No.1473 S5 명세-코드 Gap Matrix](https://app.notion.com/p/4135f4f6eaa18140ad65fefdcf46eaeb)
- [No.1474 S5 최신 정책 코드 정렬 및 validation-only 입력 검증](https://app.notion.com/p/4135f4f6eaa18154b762eb3e98624981)
- [No.1475 S5 시나리오 설계·생성](https://app.notion.com/p/4135f4f6eaa1818dbe9cedf4d48f5d18)
- [No.1415 Q25 A5 단계 진행표](https://app.notion.com/p/4105f4f6eaa181e2aa67dfa7ec9612af)
- [No.1476 Q25 A6 기준 정리 진행표](https://app.notion.com/p/4135f4f6eaa1817fb644c2280e813de1)
- [No.1521 Q25 A7 A2 S2 코드 이식](https://app.notion.com/p/4155f4f6eaa18113a0f0ea99271f711b)
- [No.1522 Q25 A7 A3 S2 이식 후 기준선 테스트](https://app.notion.com/p/4155f4f6eaa1819ca1bfdae7601311da)

## 9. 미확인 및 별도 결정 필요

- KIS official MTS master plus KIS official product specification bind all four STANDARD/MONTHLY contract identities, exact monthly expiry 20261112 and multiplier 250000. KIS VTS WS historical frames show same-time two-sided quotes for all four symbols; current tradability and freshness are not proven. Official product specification: [https://m.koreainvestment.com/main/bond/domestic/\_static/TF03bd010100.jsp](https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp).
- Canonical observation identity/time semantics 및 replay eligibility.
- S2 remaining policy inputs: U17 volatility boundary; U18 stop-loss/trailing ratios; U19 position/ledger mismatch handling; U21 maximum quote age/spread and fallback formula/priority/tick rounding. U16 retry timing/repricing is resolved; quote-policy inputs remain unresolved and must be injected explicitly (operating defaults null, therefore fail-closed). Current tradability evidence is also required.
- S2 U17 contract binding and U20 sequential progression are integrated. A2 adds validation-only group PnL MID marks, cost/freshness evidence fields, Runtime snapshot feed and TRAP\\\_CLOSE terminal wiring; A3 regression: S2 focused 75 passed, adjacent 152 passed/8 failed, with 1 net improvement against identical base-HEAD adjacent tests. X+1 registry strategy\_ids compatibility was fixed in commit 771894387adb1cbd6063495000ee9405f20b0fe2; full-registry Track1 manifest/code mismatch remains separate and does not block explicit S2 selection. U16 validation-only repair lifecycle (B1) and U21/U18 validation evaluators (B2) are integrated; actual repair/flatten order submission remains unimplemented, and U19 validation-only durable recovery gate is integrated; production restart recovery remains unverified. B4 actual-data Runtime E2E and FAST/DETAILED parity were executed on 7 trading dates; natural signals were 0, so S2 remains PSB\_UNVERIFIED and no natural-signal PASS is claimed. evaluate\_trap() remains fail-closed while quote freshness, fee/slippage and exit-policy evidence remain unresolved. Status: PSB\_UNVERIFIED.
- S1 multi-leg/base strangle·exit·fee-inclusive PnL·Production OPTION route, S5 신규 진입·hedge·re-entry, S8 일부 partial-fill 정책, S9 미확정 운영 계약/시장 데이터는 각 전략의 최신 승인 명세와 검증 근거에 따라 별도 관리한다.
- Calendar authoritative source 및 3개월 자동화·scheduler·Control Tower·Calendar/휴장일 자동화의 현재 유효성. scheduler 변경은 별도 명시 승인 전 금지.

## 10. S2 validation-only implementation progress (2026-11-11)

상세 기록은 [No.1518 S2 S33 Runtime group-PnL 진행 기록](https://app.notion.com/p/4155f4f6eaa181a39c86c62ef962a36b)으로 이동했다. 기존 기록은 해당 페이지에 보존한다.

## 11. 2026-11-11 사용자 확정 Git 작업 기준 — §2 Git 절차 우선 적용

사용자의 직접 지시에 따라 기존 §2의 Git 작업 방식 중 기준 HEAD 및 작업 위치에 관한 내용은 다음 원칙으로 보정한다. 이 절은 해당 Git 운영 항목에 대해 기존 문구보다 우선한다.

- 개발 기준은 원격 HEAD가 아니라 로컬 작업폴더의 HEAD와 로컬 작업 내용이다.
- 작업폴더: `C:\Users\white\Desktop\MovingProject\KOSPI200_Project`
- 기준 브랜치: `cleanup/p2-quarantine-20261026`
- 2026-11-11 동기화 기준 HEAD: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`
- 이 HEAD는 로컬과 원격 대상 브랜치에서 동일하며 ahead/behind는 0/0이다.
- 기존 원격 HEAD `1ea0129131370109344548827780a1e15b2ab414`는 `archive/remote-head-before-local-sync-20261111` 백업 브랜치에 보존했다.
- 이후 변경은 로컬 작업폴더에서 진행하고, 검증 후 로컬 커밋 → 동일 커밋 원격 푸시 → 양쪽 HEAD SHA 일치 확인 순서로 처리한다.
- 기존 로컬 modified/untracked 항목은 보존하며, 원격 전용 이력이 새로 생기면 백업과 사용자 승인 없이 덮어쓰지 않는다.
- 기존 §2의 안전 경계, 금지 작업, validation-only 한계 및 원본 데이터 보존 원칙은 계속 유효하다.

세부 결정 및 동기화 증거: [[No.1515 답변내용요약] 로컬 작업폴더 기준 및 원격 동기화 원칙 확정 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa1816394b8cb6ee774b1ed).

## 12. 2026-11-11 로컬 기준 작업폴더 재점검 및 S2 다음 단계

상세 기록은 [No.1519 S2 로컬 기준선 및 U16 정책 확정 기록](https://app.notion.com/p/4155f4f6eaa181049825dc61f24d7b69)으로 이동했다. 기존 기록은 해당 페이지에 보존한다.

## 13. S2 U16 구현 전 상태 머신 설계 — 2026-11-11

상세 설계 및 검증 시나리오는 [No.1520 S2 U16 fail-closed 상태 머신 설계 기록](https://app.notion.com/p/4155f4f6eaa18154bc7cd5800e6f8478)으로 이동했다. 기존 기록은 해당 페이지에 보존한다.

## 14. Q25 A7 로드맵 및 진행표

단일 진행표: [No.1517 Q25 A7 로드맵 진행표 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa18119b8b1de27a62c5ea4). A1부터 단계별 승인 및 종료 보고를 이 페이지에서 관리한다.

A1 정합 완료 시점 SSOT 본문 SHA-256 (이 digest 행 자체 제외): `A7D9C628EC24F1D011F877F9A941099B5D395517F64FBB0770D0BEA5A337B290`

## 15. Q25 A7 B1 — U16 validation-only lifecycle 구현 완료 (2026-11-11)

- 구현 커밋: `5ab5f3b224e28a433b324943ad383480bf181d5d` (통합 브랜치 `integrate/q25-s2-20261111`). 원격 `cleanup/p2-quarantine-20261026`에 non-force fast-forward push 완료, 로컬/원격 HEAD SHA 일치.
- U16 전용 fail-closed lifecycle과 테스트 추가. 원주문 terminal/reconciliation, fills/position/중복 execution ID 대사, 부족 수량 계산, T0 기준 30/60/90초 재시도 슬롯 및 120초 deadline, missed slot 건너뜀, 최대 3회 추가 재시도, 4-leg 전체 체결·대사 조건 구현.
- quote policy는 미확정 시 null/미검증으로 차단. deterministic client\_order\_id는 validation-only 식별자로만 산출. 실제 repair/flatten 주문 제출 경로는 없으며 submission flags는 false.
- S2 관련 테스트 9개 파일 106 passed; compileall, diff check, secret scan PASS. Graphify AST 갱신.
- 원본 작업폴더 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` 및 dirty/untracked 224건 보존.
- 상세: [[No.1523 답변내용요약] Q25 A7 B1 U16 validation-only 구현 및 검증 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa18145b437e0939f4352c5).
- S2 전체 판정은 `PSB_UNVERIFIED`. B4 Runtime E2E 및 Fast/Detailed parity 검증 완료. 자연 신호 미관측으로 PSB\_UNVERIFIED 유지. 다음 C1 archive integration은 사용자 별도 승인 전 실행하지 않는다. X+2는 별도 후속 유지.

## 16. Q25 A7 B2 — U21 quote validity + U18 exit validation (2026-11-11)

- 통합 커밋 3932d3757803696b7901302356acef49e3dc05c1, branch integrate/q25-s2-20261111. B2는 로컬 커밋 완료, 원격 push 없음.
- U21 validation-only evaluator는 contract identity, BID/ASK, source-time/capability/provenance, age/spread, alternate-source fallback 및 보수적 BUY ASK / SELL BID tick rounding 검증. 정책 입력 미확정/null이면 차단.
- U18 validation-only evaluator는 complete four-leg MID, fees/slippage, quote freshness, initial net premium denominator 기반 손절/트레일링 경계 평가. 수치 미확정/null이면 차단.
- 모든 결과 주문 제출 disabled. Track2AsymmetricTrap의 STOP\_LOSS\_RATIO, TRAILING\_ACTIVATION\_RATIO, TRAILING\_PULLBACK\_RATIO는 None 유지. Runtime/OMS wiring 변경 없음.
- 후보 매트릭스: reports/synth/Q25\_A7\_B2\_U21\_U18\_VALIDATION\_MATRIX\_[20261111.md](http://20261111.md).
- 12개 S2 관련 테스트 파일 160 passed; compileall, diff check, secret scan PASS. Graphify 갱신. 기존 경고: virtual\_composition\_[root.py](http://root.py) line 54 syntax error 1건 및 무심볼 파일 29개.
- 원격 cleanup/p2-quarantine-20261026은 B1 SHA 5ab5f3b224e28a433b324943ad383480bf181d5d 유지. 원본 작업폴더 HEAD b060fa57d3801e8227e88c8e54df8d2f9ffe7407 및 dirty/untracked 224건 보존.
- 상세: [[No.1524 답변내용요약] Q25 A7 B2 U21 호가 유효성·U18 손절 트레일링 검증 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa1812992a6d8655c07b209).
- 다음 단계 B3 — U19 재시작 복구 + 그룹 PnL/종결 배선. 별도 승인 전 진행하지 않는다. S2 전체 상태 PSB\_UNVERIFIED.

## 16. Q25 A7 B3 — U19 validation-only restart recovery (2026-11-11)

- 로컬 커밋: 8e13ac90220df05ffc124507e9ca40baee60cb17, branch integrate/q25-s2-20261111. B3는 push 단계가 아니므로 원격 cleanup/p2-quarantine-20261026는 B1 SHA 5ab5f3b224e28a433b324943ad383480bf181d5d 유지.
- No.1497 결정: broker/exchange-held positions primary, persisted execution ledger secondary. Broker/ledger positions exact match and same as\_of only then recovery gate passes. Missing/unverified source, timestamp mismatch, pending/unknown order, conflicting duplicate execution ID, invalid quantity or position mismatch blocks. Both sources empty required for FLAT\_CONFIRMED.
- Added core/oms/track2\_u19\_[recovery.py](http://recovery.py), environments/virtual/position/track2\_u19\_recovery\_[store.py](http://store.py), application/composition/track2\_u19\_[recovery.py](http://recovery.py), tests/core/test\_track2\_u19\_[recovery.py](http://recovery.py). SQLite schema v1 append-only checkpoint includes both position views, snapshot IDs/hashes, execution IDs/fingerprints, pending order IDs and verdict; SHA-256 integrity check.
- No automatic mismatch adjustment, runtime restore, new entry or order submission. Only injected VALIDATION\_ONLY snapshots accepted. Real broker/account API, Live and REAL\_VTS not used. Timestamp tolerance and mismatch adjustment policy remain unresolved and fail-closed.
- Existing S33 group PnL MID and TRAP\_CLOSE terminal wiring unchanged; covered by B3 regression tests.
- 12 S2-focused test files 186 passed; compileall, diff check, secret scan PASS; Graphify refreshed. Existing warning: virtual\_composition\_[root.py](http://root.py) line 54 and 29 no-symbol files.
- Original work folder HEAD b060fa57d3801e8227e88c8e54df8d2f9ffe7407 and dirty/untracked 224 items preserved. Integrated worktree clean.
- Detailed report: [[No.1525 답변내용요약] Q25 A7 B3 U19 재시작 복구 validation-only 구현 및 검증 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa181958177c2eab633740c).
- B4 Runtime E2E 및 Fast/Detailed parity 검증 완료. 자연 신호 미관측으로 S2는 PSB\_UNVERIFIED 유지. 다음 C1은 사용자 승인 대기.

## 17. Q25 A7 X+1 — strategy\_ids Registry compatibility (2026-11-11)

- X+1 완료. build\_standard\_strategy\_registry now accepts optional strategy\_ids: Iterable\[str\] \| None. None preserves all-strategy behavior; explicit selection registers only requested strategy IDs and validates selected code versions. Full manifest/code ID-set consistency check remains. Empty/invalid/unknown selections fail-closed.
- Cause: application/composition/automated\_virtual\_runtime\_[factory.py](http://factory.py) passed strategy\_ids=selected\_ids to a registry builder that did not accept the keyword, causing TypeError before selected strategy registration.
- S2-only selection (track2\_asymmetric\_trap v1.0) succeeds against the current manifest. 13 focused S2 test files: 193 passed; compileall, diff check and secret scan PASS. Graphify refreshed; pre-existing extraction warnings remain.
- Separate existing baseline issue: default all-strategy registry still exposes Track1 manifest 1.1.0 vs code 1.2.0 mismatch, already recorded in A3. Not changed as part of X+1.
- Local commit 771894387adb1cbd6063495000ee9405f20b0fe2 on integrate/q25-s2-20261111; clean worktree. No push because X+1 is not an A7 push stage. Remote cleanup branch remains 5ab5f3b224e28a433b324943ad383480bf181d5d. Original working folder HEAD b060fa57d3801e8227e88c8e54df8d2f9ffe7407 and 224 dirty/untracked items preserved.
- Detailed Q&A: [[No.1526 답변내용요약] Q25 A7 X+1 strategy_ids Registry 호환성 수정 (2026-11-11)](https://app.notion.com/p/4155f4f6eaa181f0ba81dd3555888a92).
- Next: C1 archive integration, pending explicit user approval. B4 completed with PSB\_UNVERIFIED; no natural signal was observed.

## 17. A7 B4 Runtime E2E / Fast-Detailed parity (2026-11-12)

- 판정: B4 검증·판정·푸시 완료. S2는 PSB\_UNVERIFIED 유지. 7개 실제 거래일 replay에서 자연 진입 신호가 0건이므로 자연 신호 PASS는 주장하지 않는다.
- 통합 브랜치 integrate/q25-s2-20261111, HEAD 400267909b2277e0339787f220c6bacf3e9f7f5f. 원격 cleanup/p2-quarantine-20261026과 SHA 동일.
- 최신 사용 마스터 fo\_idx\_code\_mts\_[20261014.zip](http://20261014.zip), SHA-256 f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e. Identity 6,510개, expiry cache 23건, 관측 계약 심볼 26/26 정합.
- 2026-10-14 Runtime E2E: 6,840 ticks; projection errors 463; 선물 replay 225,351 events 및 지수 replay 23,320 events 전량 소비. 전략 입력 AVAILABLE 5,807, BASIS unavailable 633, option orderbook unavailable 382, POC unavailable 18.
- 자연 조건 첫 차단: BBW 5,538, volume z-score 260, OBI 9. 모든 진입 조건 동시 통과 0건. 2026-10-02, 10-06, 10-07, 10-08, 10-12, 10-13, 10-14 모두 자연 신호 0건.
- 2026-10-15\~2026-11-11의 존재하는 raw WS 파일은 H0IOASP0/H0UPCNT0는 있으나 H0IFCNT0가 없어 동일 거래일 basis·BBW·volume·POC 구성이 불가. 날짜 간 데이터 혼합은 금지했다.
- FAST/DETAILED validation-only replay 100 events씩 실행, semantic fields 동일. 양쪽 신호/승인/라우팅/체결 0, execution IDs empty, PnL 0. S2 14개 파일 197 passed, S9 인접 4개 파일 46 passed, 합계 18개 파일 243 passed. compileall/diff check/secret scan PASS, Graphify 갱신.
- 기본 gate false를 메모리 내 관찰 전용으로만 활성화. signal\_observation\_only=true, broker orders 0, 외부 네트워크 차단, KIS API 미호출, 실주문 미제출. 원본 데이터 해시 전후 동일.
- 코드 변경: Virtual bootstrap/High-Speed Replay에 명시적 strategy\_keys 전달, 미지원 StandardRuntimeInputProvider 인자 제거, S2 FAST/DETAILED parity 테스트 추가. 전체 registry Track1 version mismatch는 별도 이슈로 유지하되 S2 단독 검증을 중단시키지 않았다.
- 상세 Q&A: [[No.1527 답변내용요약] Q25 A7 B4 자연 Runtime E2E 및 Fast/Detailed parity (2026-11-12)](https://app.notion.com/p/4155f4f6eaa1818d8f5ceb68804e9336).
- 당시 C1은 사용자 별도 승인 대기였으며, 2026-11-12 별도 승인 후 완료했다.

## 18. Q25 A7 C1 — Remaining archive integration (2026-11-12)

- 판정: C1 완료. A5 S1/S5/S7/S8/S9/S15b archive 코드·validation-only 자료·검증 보고서를 S2 A7 통합 브랜치에 병합했다.
- 통합 브랜치: `integrate/q25-s2-20261111`. 병합 커밋: `d1aef6aab7ce49ec2ad83a837f93c199f2d7c23f`. 부모: B4 `400267909b2277e0339787f220c6bacf3e9f7f5f`, archive `4bd9d67c24ccd4c450e735031b60809b6a6c4f1a`.
- 8개 충돌 영역은 S2 최신 Runtime/Registry 변경을 보존하는 방식으로 판단·통합했다. S9 policy runtime DTO를 fail-closed policy kernel에 결합했고 Graphify는 merge tree 기준으로 재생성했다. 미해결 conflict marker 0건, tracked deletion 0건.
- 132 files: 32 modified, 100 added. 새 tracked data는 신규 `data/derived_scenario/` 경로에만 추가됐다.
- 집중 회귀 424 passed: S1/S5/S7/S8 112, S9/S15b 104, S2 197, registry/Track6 4, R4 lifecycle 7. compileall/diff check/secret scan PASS.
- 기본 Strategy Registry 9개 전략 등록 확인. Track1 manifest/code version 1.2.0 정합으로 A3에서 별도 이슈였던 전체 registry mismatch 해소.
- validation-only asset bootstrap은 격리 candidate worktree에서만 수행. 보호 profile 6개 SHA 동일, 데이터셋 inventory 및 manifest 검증 PASS, 모든 자산 `runtime_eligible=false`. KRX fixture 입력 5개는 해당 disposable worktree에만 생성했다.
- 기존 원본 작업폴더 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` 및 dirty/untracked 224건 보존. KIS/REAL\_VTS/Live/실계좌/주문 API 미호출, 외부 주문 0건. `.env`, 운영 RiskConfig, scheduler, collector 변경 없음.
- 원격 `cleanup/p2-quarantine-20261026`에 non-force fast-forward push 완료. local/remote SHA 동일 `d1aef6aab7ce49ec2ad83a837f93c199f2d7c23f`. `Project200` 및 `master` 미변경.
- 상세 Q&A: [[No.1528 답변내용요약] Q25 A7 C1 archive 통합 (2026-11-12)](https://app.notion.com/p/4155f4f6eaa1818285f7cbfea4b569df). Repo report: `reports/synth/Q25_A7_C1_ARCHIVE_INTEGRATION_20261112.md`.
- 다음 단계는 C2 문서 복원이며 사용자 별도 승인 전 시작하지 않는다.

## 19. Q25 A7 C2 — Document restoration (2026-11-12)

- 판정: C2 완료. `AGENTS.md`에 현재 A7 상태를 추가하고, Notion Current Baseline v2를 `docs/CURRENT_BASELINE_V2.md`로 저장소에 복원했다. 과거 문서 내용은 삭제하지 않고 역사 근거로 보존했다.
- 통합 브랜치: `integrate/q25-s2-20261111`.
- C2 문서 복원 commit: `baf45cd2e6c7336e9ceb75e7c211b773635da954`; 후속 mirror sync commit: `bfa82036a781cb9c8d34ab81df20c9f2b032b216`. 최신 local/remote HEAD: `bfa82036a781cb9c8d34ab81df20c9f2b032b216`.
- 원격 `cleanup/p2-quarantine-20261026` non-force fast-forward push 완료. 최종 local/remote SHA 동일: `bfa82036a781cb9c8d34ab81df20c9f2b032b216`.
- `docs/CURRENT_BASELINE_V2.md` SHA-256: `5340338C067B77204D2B5EDB6BF362108229E6BEF75188591FB48B99E1A56EB7`.
- `AGENTS.md` SHA-256: `9120CC7060873B4209E8AB86631EDAAD22C6633F21B2E8F621A36C86506C597F`.
- Repo report: `reports/synth/Q25_A7_C2_DOCUMENT_RESTORATION_20261112.md`.
- 검증: `git diff --check` PASS; conflict marker 0; secret-pattern scan 0. 문서 전용 변경이므로 application pytest는 실행 대상이 아니다.
- 원본 작업폴더 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` 및 dirty/untracked 224건 보존. `Project200`/`master` 미변경.
- C3 dirty 224건 읽기 전용 분류는 다음 단계이며 별도 승인 전 시작하지 않는다.
