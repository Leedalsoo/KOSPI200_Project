기준일: 2026-11-10 (KST)
기준 브랜치: `cleanup/p2-quarantine-20261026`
기준 HEAD: `3cc0e677848f99315e002b448c771ca2ffc72813`
상태: A6 C01–C10 및 A5 S28 완료 상태를 반영한 단일 SSOT. S2 통합 명세 v0.5와 No.1491–1499, No.1501–1505의 사용자 확정 정책을 반영했다. 이 문서의 SHA-256은 로컬 파일과 Notion 본문이 동일해야 한다.

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
- A6 C01–C10 기준 정리는 2026-11-10 완료했다. A5/A4 단계는 자동 재개하지 않으며, 다음 실행 범위는 사용자의 별도 직접 지시를 따른다.
- KIS Live, REAL_VTS, 실계좌, 실주문·정정·취소·잔고·증거금 API 호출 금지.
- 운영 설정, .env/비밀정보, 권한, 스케줄러, collector 및 원본 데이터 변경 금지. 원본 작업폴더의 기존 dirty/untracked 항목은 보존한다.
- Git 작업은 격리 worktree에서 수행한다. 허용 대상은 `cleanup/p2-quarantine-20261026`뿐이며 non-force push만 허용한다. `Project200`/ `master` push, force push, merge, history rewrite 금지.
- 삭제 금지. Notion 역사 기록의 상태 배너·이동·대체 표시는 C04 승인 또는 사용자 명시 승인 범위에서만 수행한다.

## 3. 현재 기준선 및 검증 원칙

- 기준 HEAD: `3cc0e677848f99315e002b448c771ca2ffc72813`; S28 보고서 파일 수 정정 커밋이다. S28 통합 회귀 보고서 SHA-256은 `593CDB1851C1F888ECF1DDCE80550966C9C441A726BA9ED22A038643C210E79A`이다.
- S2 통합 명세 v0.5 및 지원 문서 3종은 No.1500에서 사용자 승인되었다. 승인은 명세/정책 기준에 한정되며 코드 구현, Runtime/OMS 연결, Runtime E2E, Replay 또는 주문 실행 승인이 아니다.
- S28 최종 종합 판정은 COMPLETED_WITH_BLOCKERS / PSB_UNVERIFIED; Production readiness가 아니다. 전체 pytest는 496 passed / 29 failed / 1 skipped, 활성 전략 회귀는 224 passed(36개 파일)이다. 29개 실패는 기존 synthetic dataset/manifest 누락 계열이며 full-suite PASS가 아니다.
- S5 신규 진입은 BLOCKED. No.1168의 OPTION BUY 2-only 진입안은 폐기 상태이며 재사용하지 않는다. 이미 열린 포지션의 close lifecycle은 보존한다.
- Synthetic/derived 입력은 명시적인 유효 KIS anchor, provenance, manifest 및 validation-only 경계가 있을 때만 보완 검증에 사용한다. `SYNTHETIC:DERIVED_SCENARIO`를 Production authoritative input으로 승격하지 않는다. anchor 없는 계약은 `UNAVAILABLE`.
- KIS-only authoritative runtime data 원칙 유지. KIS multiplier 등 누락 필드를 상수·KRX·다른 상품으로 대체하지 않는다.
- PSB 결과는 전략·시나리오·입력·런타임 범위를 구분해 기록한다. Scenario catalog 생성 PASS, plumbing PASS, natural-signal Runtime E2E PASS는 서로 대체할 수 없다.
- FAST/DETAILED 동등성은 해당 실행에서 명시적으로 검증된 경우에만 PASS로 기록한다.

## 4. 전략별 현재 상태

| 전략 | 기준 및 확인된 상태 | 제한·미완료 |
| --- | --- | --- |
| S1 | S28 최종 판정 PLUMBING_ONLY. S15b 단일 short CALL 자연신호 validation-only E2E 및 FAST/DETAILED parity 범위. | Base strangle/multi-leg/exit/fee-inclusive PnL/Production OPTION route 미검증. |
| S2 | No.1500에서 통합 명세 v0.5 승인. S26 4-leg validation controls 및 S27 preflight 수행. 정책 U16–U21은 No.1491–1499, No.1501–1505 기준으로 확정된 범위까지 반영. | BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED. Runtime progression 미연결, authoritative 4-contract identity/group risk/PnL/pricing/restart 미확인, S2 Runtime E2E 미실행. |
| S5 | S28 최종 판정 PSB_PASS_VALIDATION_ONLY_SYNTHETIC (close-only). StrategyHub natural exit → Virtual close fill → PositionLot flat 및 FAST/DETAILED parity, focused 51 tests. | Seed는 synthetic이며 실제 과거 fill이 아니다. 신규 진입은 계속 BLOCKED. |
| S6 | S28 PSB_PASS (S03 검증 범위). first_rank=5 / per_order 조건의 take-profit·trailing·15:10 force-close 검증. | Rank 6 및 나머지 matrix 조합, authoritative contract identity/calendar/운영 설정 미검증. |
| S7 | S28 PSB_PASS (validation-only synthetic). 자연 StrategyHub 신호 8건, FAST/DETAILED parity, 월·목 만기별 Position/PnL 대사. | Synthetic identity/expiry/calendar 및 fee 범위 한정. Production 승격 아님. |
| S8 | S28 PSB_PASS (validation-only synthetic subset). STOP/TRAILING/EXPIRY exit 및 No.1397 정책 기반 자연신호 retry E2E. | No.1398 multi-contract partial-fill은 PLUMBING_ONLY. 일부 정책 및 계약 데이터 미확인. |
| S9 | S28 PSB_PASS (validation-only synthetic subset). 독립형 ATM PUT+CALL STOP_LOSS, cold-start 복구, 5분 timeout/retry natural-signal E2E 및 73 tests. | Retry timer의 프로세스 재시작 복원, 비대칭 fill/reject 후 repair/flatten, 공식 KIS 계약·시장 데이터 미확인. |

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
- S2 승인 명세의 4-leg 진입 순서는 PUT BUY → CALL BUY → PUT SELL → CALL SELL이다. 그룹은 4개 레그의 목표 수량이 모두 체결되고 대사된 뒤에만 ACTIVE가 된다.
- S2-U16: 부분체결/거절/취소 경합 시 원주문 취소·종료 상태, 체결 및 포지션을 먼저 대사하고 확인된 실제 체결량 기준으로 부족 수량만 보정한다. 상태 불명은 RECONCILIATION_REQUIRED로 차단한다. 보정 가격은 BID/ASK 기반 지정가, 최초 보정 주문 이후 추가 재시도 최대 3회, 최초 보정 제출부터 최대 120초를 함께 적용한다. 재시도 전 재대사하며, 최종 실패 시 기체결 레그 전체 청산 정책 및 그룹 차단을 적용한다. 실제 청산 주문 제출은 승인되지 않았다.
- S2-U17: ATM 행사가 동률이면 지수 가격 이하의 낮은 행사가를 선택한다.
- S2-U18: 옵션 평가는 MID, 순비용 분모는 최초 그룹 순프리미엄 수취액, 수수료·슬리피지는 실현/평가 손익 모두 반영한다. 손절은 누적 순손실/최초 순프리미엄 비율, 트레일링은 최대 누적 순이익 대비 되돌림 비율 구조를 사용하되 구체 비율은 미확정이다.
- S2-U19: 재시작 시 브로커/거래소 보유 포지션이 authoritative이며 저장 execution ledger는 보조 근거다. 실제 포지션과 ledger 불일치 시 조정·중단·재개 절차는 미확정이다.
- S2-U20: 레그 취소 확인, 0체결 확인 및 주문/포지션 대사가 끝난 뒤 다음 레그로 진행한다. 취소 확인 전 다음 레그 진행 금지.
- S2-U21: BID/ASK 누락·stale·허용 스프레드 초과 시 보수적 대체가격을 사용하고 유효한 대체가격이 없으면 차단한다. 최대 호가 경과시간·스프레드·fallback 산식·우선순위·tick 반올림은 미확정이다.
- S2 U16 보정 재시도 간격 및 가격 재산정 시점은 미확정이다. 정책 결정은 구현·테스트·Runtime/OMS 연결 또는 실제 주문 실행을 승인하지 않는다.

## 7. A6 정리 단계

A6 C01–C10 전체 완료(2026-11-10). C09 verification gate 및 C10 A5 진행표 동기화까지 완료되었다. A6 완료는 A5/A4 자동 재개 또는 S2 구현·Runtime 검증 승인을 의미하지 않는다. 다음 단계는 사용자의 별도 직접 지시 및 별도 승인 범위에 따른다.

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
- [No.1424 VTS WS 부족 데이터의 REST 보완 가능성 재검증](https://app.notion.com/p/4105f4f6eaa181f29d5ad6f1b5582305)
- [No.1397 S8 10분 간격·최대 3회 Runtime 재시도](https://app.notion.com/p/40e5f4f6eaa18132a8c6d16b8a769af7)
- [No.1439 S9 독립형 전략 명세 v0.3 사용자 승인](https://app.notion.com/p/4115f4f6eaa181c88075f52d6cd57bc0)
- [No.1473 S5 명세-코드 Gap Matrix](https://app.notion.com/p/4135f4f6eaa18140ad65fefdcf46eaeb)
- [No.1474 S5 최신 정책 코드 정렬 및 validation-only 입력 검증](https://app.notion.com/p/4135f4f6eaa18154b762eb3e98624981)
- [No.1475 S5 시나리오 설계·생성](https://app.notion.com/p/4135f4f6eaa1818dbe9cedf4d48f5d18)
- [No.1415 Q25 A5 단계 진행표](https://app.notion.com/p/4105f4f6eaa181e2aa67dfa7ec9612af)
- [No.1476 Q25 A6 기준 정리 진행표](https://app.notion.com/p/4135f4f6eaa1817fb644c2280e813de1)
## 9. 미확인 및 별도 결정 필요

- KIS 공식 4개 옵션 계약 identity, exact monthly expiry, multiplier, tradability 및 source timestamp/freshness.
- Canonical observation identity/time semantics 및 replay eligibility.
- S2: 손절 비율·trailing 되돌림 비율의 구체 수치; 상장 행사가 존재 여부·strike/tick rounding·정확한 월물 만기; 최대 quote age·spread 한도/단위 및 fallback 산식·우선순위·tick rounding; U16 보정 재시도 간격·가격 재산정 시점; 브로커 포지션과 execution ledger 불일치 시 조정·중단·재개 절차.
- S2 Runtime progression/OMS 연결, group PnL exit signal wiring 및 durable recovery의 통합 증거 미확인. 현재 evaluate_trap()은 empty tuple을 반환하며 S2 Runtime E2E는 실행되지 않았다. 상태는 BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED.
- S1 multi-leg/base strangle·exit·fee-inclusive PnL·Production OPTION route, S5 신규 진입·hedge·re-entry, S8 일부 partial-fill 정책, S9 미확정 운영 계약/시장 데이터는 각 전략의 최신 승인 명세와 검증 근거에 따라 별도 관리한다.
- Calendar authoritative source 및 3개월 자동화·scheduler·Control Tower·Calendar/휴장일 자동화의 현재 유효성. scheduler 변경은 별도 명시 승인 전 금지.
