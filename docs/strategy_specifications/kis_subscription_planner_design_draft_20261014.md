# KIS WebSocket Subscription Planner — Design Draft

작성일: 2026-10-14  
상태: 초안 / 검증 중 / 사용자 승인 전 / collector 적용 금지

## 1. User-defined hard cap and conservative interpretation

- Official portal pages reviewed: https://apiportal.koreainvestment.com/docs and https://apiportal.koreainvestment.com/apiservice?keyword=ci%EC%BD%94%EB%93%9C. They describe WebSocket/API behavior, but the reviewed public documentation did not conclusively specify whether the 41 cap is per session, appkey, or how quote and trade registrations aggregate.
- The 41 hard ceiling comes directly from the user instruction. Conservative planner assumption: treat 41 as the total count of (TR_ID, symbol) registrations per single WebSocket session, count trade and quote separately, and never open a second session to bypass the cap. Account/appkey scope remains not independently documented in this review.
- (TR_ID, 종목코드) 조합 1개를 등록 1건으로 계산한다. 옵션 체결 H0IOCNT0와 옵션 호가 H0IOASP0는 각각 1건, 미니선물 체결 H0IFCNT0와 호가 H0IFASP0도 각각 1건, KOSPI200 지수 H0UPCNT0 / 2001은 1건이다.
- The configured hard cap is 1..41 registrations, per the current user instruction; 41 is not 41 distinct symbols.

## 2. 기존 수집기 인벤토리 — 읽기 전용 코드 조사

| 항목 | 현재 구성 | 등록 수 | 사용자 범위 판정 |
|---|---|---:|---|
| KOSPI200 월물 옵션 | H0IOCNT0, offset -15,-12.5,-10,-7.5,-5,-2.5,0,2.5,5,7.5,10,12.5,15; CALL+PUT | 26 | 필요 범위. 다만 체결만 구독하며 위클리 및 옵션 호가가 빠져 있음 |
| 표준 선물 | H0IFCNT0, 근월 선택 | 1 | 현재 범위 밖. S3 근월/원월 스프레드 명세 승인 전에는 향후 계획에서 제외 |
| 미니선물 | H0IFCNT0, 근월 선택 | 1 | S3/S4는 보류 상태이므로 전략 진입용 구독은 S3/S4 활성화 전 제외. 현재 S5 manifest에는 미니선물 의존성이 있어 사용자 범위와 충돌하므로 자동 추가하지 않고 BLOCKED 처리 |
| KOSPI200 지수 | H0UPCNT0 / 2001 | 1 | 필요 |
| 월요일 위클리 옵션 | H0IOCNT0 | 0 | 필요하지만 현재 없음 |
| 목요일 위클리 옵션 | H0IOCNT0 | 0 | 필요하지만 현재 없음 |
| 옵션 호가 | H0IOASP0 | 0 | 옵션 호가/유동성 입력이 필요한 전략에 필요하지만 현재 없음 |
| 미니선물 호가 | H0IFASP0 | 0 | S3/S4가 활성화된 경우에만 필요하지만 현재 없음 |
| 현재 구성 합계 | 26 + 1 + 1 + 1 | 29 | 기존 코드 구성 수치이며, 승인된 미래 계획이 아님 |

기존 collector에는 bounded rotation 구현과 plan_subscription_rotation이 있지만, spare capacity가 있으면 신규 구독을 먼저 등록하는 경로가 있고 rotation 이벤트에는 브로커 확인응답이 상관관계로 검증되지 않았다고 기록된다. 신규 계획기는 별도 순수 함수이며 collector에 적용하지 않는다.

## 3. 후보 구독 용량

| 경우 | 등록 수 계산 | 최대 옵션 계약 수 | 판정 |
|---|---|---:|---|
| 지수 + 옵션 체결/호가 | 1 + 2N ≤ 41 | 20 | 용량 상한이며 전략 요구사항 확정이 아님 |
| 지수 + 미니선물 체결/호가 1계약 + 옵션 체결/호가 | 1 + 2 + 2N ≤ 41 | 19 | S3/S4 활성 및 승인 시에만 |
| 보유 포지션/미체결 주문 | 옵션 계약당 체결·호가 각 1건 | 남은 용량 | 최우선. 이 항목만으로 한도 초과 시 critical blocker를 보고하고 조용히 제외하지 않음 |
| 지수 | 1 | — | 보유/미체결 계약 다음 우선순위 |

## 4. 계획기 알고리즘

1. 입력은 timezone-aware 현재 시각, 승인된 거래일 상태, 활성 전략/단계, 보유 포지션·미체결 주문 종목, 지수 수준, 정확한 만기 provenance와 마스터 나이를 가진 계약 identity, 전략별 selector 산출물이다.
2. 보유 포지션과 미체결 주문을 먼저 등록하고, 그 다음 지수를 등록한다.
3. 활성 전략을 명시 우선순위로 순회한다. 모든 필요 identity, 마스터 스냅샷 24시간 이내, 정확한 만기 provenance, 옵션 side/series 및 미만기 여부를 검증한다. 미확인 입력은 해당 전략을 BLOCKED 처리한다.
4. 같은 (TR_ID, 종목) 등록은 전략 간 중복 제거한다. 전략 selector가 ATM 가까운 순서로 종목을 제공해야 한다. 계획기는 ATM이나 전략 레그를 추정하지 않는다.
5. 전략의 전체 필요 구독이 용량에 들어가지 않으면 해당 전략을 BLOCKED로 표시하고 제외 목록과 영향을 기록한다. 불완전한 신호를 조용히 사용하지 않는다.
6. 미니선물은 S3 또는 S4가 활성화된 경우에만 허용한다. 표준 선물은 S3 근월/원월 스프레드 설계가 승인되기 전까지 제외한다. 금지된 선물을 요구하는 전략은 BLOCKED 처리한다.
7. max_quote_age_seconds, minimum_hold_seconds, ATM hysteresis는 UNSET이다. 회전 임계값이 미정이면 자동 재중심화는 비활성화한다.
8. 구독 교체 계획은 해지 → 해지 확인응답 대기 → 신규 구독 순서다. 이 문서는 계획만 생성하며, 실제 collector 확인응답 처리 및 적용은 별도 승인 후 수행한다.

## 5. 구독 계획 드라이런

- 증거 JSON: verification/evidence/kis_subscription_plan_dry_run_v2_20261014.json
- 실제 KIS 마스터와 만기 캐시의 identity를 용량 계산 fixture로 사용했다. 실시간 ATM 가격으로 행사가를 선정한 결과가 아니며, 전략별 최종 selector 결과도 아니다.
- 운영 거래일 상태는 승인되지 않아 BLOCKED다. 드라이런의 trading_day_approved=true는 계획기 용량 테스트를 위한 입력이며 실행 허가가 아니다.
- 실제 보유 포지션·미체결 주문 상태를 입력받지 못해 드라이런에는 해당 최우선 종목이 없다.

## 6. 데이터 신선도와 미해결 사항

- REST aspr_acpt_hour는 HHmmss만 제공한다. 00:45에 수신한 154500은 날짜를 포함하지 않아 같은 날 데이터인지 증명하지 못한다. max_quote_age는 UNSET 유지.
- 기존 collector에서 H0IOASP0 프레임은 관측되지 않았다. 옵션 호가 freshness를 PASS로 판정하지 않는다.
- KIS 공식 type-code 사전을 독립적으로 찾지 못했다. 마스터 행의 코드·이름·CALL/PUT·월/주 라벨은 상호 상관을 보여주지만 별도 공식 코드 사전과 같지 않다. 코드와 라벨이 불일치하거나 모르는 라벨은 제외하고, 매핑 상태는 PARTIAL로 남긴다.
- 계좌 포지션/미체결 주문 입력이 없어 최우선 순위 테스트는 통제된 fixture로만 수행했다.

## 7. 적용 변경안 — 미적용

- 계획기: infrastructure/kis/kis_subscription_planner.py (순수 계산 함수).
- 추후 적용 후보: scripts/kis_vts_websocket_collector.py에서 구독 집합을 생성/회전하는 경계. 정확한 함수와 변경 영향은 통합 전 별도 diff 검토 및 사용자 승인이 필요하다.
- 이번 지시서에서 collector 변경·중지·재시작, 추가 WebSocket 세션, commit/push는 수행하지 않았다.
- 향후 승인된 통합이 있으면 계획기 전용 변경만 롤백 대상으로 삼고, 기존 무관 변경은 되돌리지 않는다.

## 8. 명시적 범위 충돌

- 현재 strategy manifest는 9개 전략이 모두 enabled=true이고 S5는 미니선물 source를 요구한다. 하지만 본 지시서는 S3/S4를 보류하고 미니선물 구독은 S3/S4 활성 시에만 허용한다.
- 권고: 새로 승인된 전략 명세에서 의존성이 정리되기 전까지 미니선물이 필요한 S5 단계는 BLOCKED 처리한다. 사용자 범위를 추정으로 넓히지 않는다.
