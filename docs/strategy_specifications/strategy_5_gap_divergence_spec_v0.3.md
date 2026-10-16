# Strategy 5 — Gap Divergence 명세 v0.3

- 작성일: 2026-10-12
- 상태: **draft / unverified / unapproved — 구현 기준 사용 금지**
- 기준 브랜치/HEAD 조사값: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 선행 자료: v0.2(보존), 사용자 확정 의도(2026-10-12), AGENTS.md, 관련 Decision Log/Q&A
- 범위: 문서 갱신만. 코드·테스트·commit/push·KIS Live 주문 없음.
- 폐기 규칙: Decision Log는 삭제하지 않는다. No.1168의 BUY2는 폐기된 안이며 S5 설계에 재사용하지 않는다.

## 1. 목적 및 사용자 확정 의도

S5의 목적은 시가 갭 상승/하락을 수익 기회로 연결하는 것이다. 장 시작부터 약 30분만 운용한다. 가격 방향을 예측하거나 갭메움/갭추종 이중 판단 로직을 만들지 않고, 설정된 시간대·가격 기준을 규칙대로 실행한다.

- 전일 종가 대비 갭이 거의 없으면 거래하지 않는다.
- 갭이 `min_gap_pt` 이상이면 갭 방향의 ATM 옵션을 매수한다: 갭 상승은 CALL BUY, 갭 하락은 PUT BUY.
- 갭 방향으로 `advance_pt` 이상 진행하기 전 반전하면 반대 옵션 `hedge_contracts`를 매수해 중립화한다.
- `advance_pt` 이상 진행한 뒤 반전하면 헤지가 아니라 갭 방향 옵션의 이익 청산 규칙을 적용한다. 고점 대비 반전 폭은 갭 크기의 `reversal_ratio`이며, 예를 들어 갭 2.5pt × 10% = 0.25pt다. 최소 반전 폭은 별도 설정으로 검증한다.
- 방향이 다시 틀어지는 재반전에서는 헤지 포지션을 청산하고 원래 옵션의 이익을 취한다. 선물 매수/매도 시나리오는 목표 로직에서 제거한다.
- 헤지는 반대 옵션 1계약을 기본 초안으로 하며 휩소 한도는 2회다. 한도 도달 시 당일 신규 거래를 중단하고 당일 잔여 포지션을 청산하는 방향을 사용자 의도로 기록한다. 청산 완료는 실제 체결·포지션 대사로 확인해야 한다.
- 기존 미니선물 5계약은 주 수익원이 아니라 방향 오판 시 위험 방어 목적이었다. 자본·증거금 부담 때문에 옵션 헤지로 대체한다. 5선물을 옵션 5계약으로 치환하거나 델타 환산으로 옵션 수량을 임의 정당화하지 않는다.
- 30분 종료 동작, 반전 최소폭, 진행 전 반전 폭, 손절 정책, 갭 임계값은 설정값으로 두고 REAL_VTS 검증 후 확정한다. 값이 null 또는 PROVISIONAL이면 신규 진입을 차단한다.
- 설정 버전과 설정 hash를 각 실행에 기록하고 튜닝 기간과 독립 검증 기간을 분리한다.

## 2. 설정 스키마 (PROVISIONAL)

```yaml
strategy5:
  status: PROVISIONAL
  session_minutes: 30
  min_gap_pt: 1.0
  entry_option: ATM
  advance_pt: 1.0
  reversal_ratio: 0.10
  reversal_min_pt: null
  hedge_contracts: 1
  whipsaw_limit: 2
  hedge_reversal_pt: null
  session_end_action: null  # close_all | hold | close_hedge_only 후보; 확정 아님
  stop_loss_enabled: false
  stop_loss_pt: null
```

Fail-closed: `status != APPROVED`, 설정 누락/null, 형식·단위·범위 오류, 미검증 config hash, authoritative 기준가격/계약/호가/포지션 누락이면 신규 주문을 차단한다. `stop_loss_enabled: false`는 명시적 false일 때만 손절 미사용 후보로 해석한다. 키 누락 또는 null은 false로 보정하지 않고 차단한다. `stop_loss_enabled: true`이면 `stop_loss_pt`가 유효한 양수여야 한다.

| 설정 | 의미 | 현재 값/상태 | 검증 설계 |
|---|---|---|---|
| session_minutes | 세션 시작 기준 신규 진입/관리 창 | 30, 잠정 | 29:59 / 30:00 / 30:01, 공식 시각·수신시각 분리 |
| min_gap_pt | 전일 종가 대비 최소 갭 | 1.0 잠정 | 0.99 / 1.00 / 1.01 및 후보값 비교 |
| entry_option | 진입 옵션 선정 | ATM | authoritative Option Master, ATM tie-break와 계약 identity |
| advance_pt | 이익 추종 구간 진입 기준 | 1.0 잠정 | 0.99 / 1.00 / 1.01, 방향별 대칭 |
| reversal_ratio | 갭 크기 대비 고점 반전 비율 | 0.10 잠정 | 후보 5%, 10%, 15% 등 별도 튜닝 후 고정 검증 |
| reversal_min_pt | 잡음 방지용 최소 반전폭 | null | 후보 0.10/0.15/0.20pt 등 비교하되 사전 승인된 후보군으로 한정; 값 확정 전 차단 |
| hedge_contracts | 반대 옵션 중립화 수량 | 1 사용자 의도 | 주문·체결 수량 1계약, 부분체결/거절 처리 |
| whipsaw_limit | 휩소 중단 횟수 | 2 사용자 의도 | 첫 회/두 번째 회/초과 회 경계, 당일 중단 |
| hedge_reversal_pt | advance 도달 전 헤지로 볼 반전 폭 | null | 후보별 비용·손실·노출·체결 가능성 비교; null이면 차단 |
| session_end_action | 30분 종료 시 포지션 처리 | null | close_all / hold / close_hedge_only 각각 시나리오 비교; 확정 금지 |
| stop_loss_enabled | 손절 사용 여부 | false 잠정 | 명시적 true/false 비교; 누락/null은 차단 |
| stop_loss_pt | 손절 폭 | null | enabled=true일 때만 후보별 검증; 미설정 시 차단 |

## 3. 검증 프로토콜

1. 데이터 분할은 시간순으로 튜닝 구간과 검증 구간을 분리한다. 동일 거래일/동일 이벤트가 양쪽에 섞이지 않게 한다.
2. 설정 후보와 데이터 범위, 코드/데이터 provenance, config version/hash를 사전에 기록한다. 검증 결과를 보고 후보군을 사후 변경해 같은 검증 구간에 재적합하지 않는다.
3. 후보 비교 지표: 거래당 순손익(실제 옵션 premium/fill 기반), 수수료·슬리피지 포함 손익, 최대 낙폭, 최대 단일 손실, 휩소 횟수, 헤지 후 잔여 노출, 미체결/부분체결률, quote freshness 실패, 계좌·전략별 프리미엄/증거금/최대손실, 세션 종료 잔여 포지션.
4. 결과는 REAL_VTS provenance가 확인된 관측만 REAL_VTS로 분류한다. SYNTHETIC/DERIVED_SCENARIO/Virtual 결과를 REAL_VTS 결과로 부르지 않는다.
5. 결과가 부족하거나 설정·데이터가 미확정이면 UNVERIFIED/BLOCKED. 검증 완료만으로 사용자 승인을 대체하지 않는다.

## 4. F01–F29 재분류표

분류: **확정** = 사용자 의도가 직접 정해짐(실제 운영값 승인과는 별개), **검증값** = 설정으로 튜닝/검증 후 확정, **사용자 확인 필요** = 현 단계에서 의미/외부 근거를 더 정해야 함. 이 표는 코드의 현재 동작을 요구사항으로 승격하지 않는다.

| ID | 판단요소 | v0.3 목표/분류 | 근거·미해결 |
|---|---|---|---|
| F01 | 목적·경제적 역할 | 확정 | 갭 방향 옵션 수익 + 옵션 헤지로 오판 위험 방어; 선물 5는 수익원 해석 오류 |
| F02 | 시장·상품 범위 | 확정 | KOSPI200 일반 옵션; 정확한 계약 identity는 authoritative source 필요 |
| F03 | 세션/lifecycle | 확정+검증값 | 장 시작부터 약 30분; 세션 시작 timestamp의 authoritative 정의는 검증 필요 |
| F04 | 기준가격·시점 | 사용자 확인 필요 | 전일 종가·공식 시가·갭 산출 source/as-of/freshness 계약 필요 |
| F05 | 진입 임계값 | 검증값 | min_gap_pt, ATM, 갭 방향 CALL/PUT BUY; 경계는 테스트 |
| F06 | 중복 진입·재진입 | 사용자 확인 필요 | 당일 재진입 횟수와 헤지 이후 원래 포지션 재진입 범위 추가 정의 필요 |
| F07 | 주문 ACK/취소/재주문 | 사용자 확인 필요 | per-leg 주문상태·idempotency·취소 경합 계약 필요 |
| F08 | 옵션 계약 identity | 사용자 확인 필요 | exact expiry, strike, multiplier, broker symbol, tradability 검증 |
| F09 | ATM·tick·호가 품질 | 사용자 확인 필요 | ATM tie-break, tick, quote age/spread/depth 기준 미확정 |
| F10 | 가격 단위·갭 산출 | 검증값 | pt 단위, 갭 절대값/방향, source provenance; 값은 검증 후 확정 |
| F11 | advance/반전 trigger | 검증값 | advance_pt, reversal_ratio, reversal_min_pt; equality/우선순위 테스트 |
| F12 | 수량·자본·비용 | 확정+사용자 확인 필요 | hedge_contracts=1, whipsaw_limit=2; premium/margin/fees/account caps authoritative 설정 필요 |
| F13 | 주문 가격·재가격 | 사용자 확인 필요 | limit price, collar, reprice interval/횟수 미확정 |
| F14 | 그룹 위험 preflight | 확정 | 모든 레그 전 group risk/quote/cost/capital preflight; 미충족 시 차단 |
| F15 | 부분체결·거절·미체결 | 확정 | leg별 독립 상태, 실제 filled/remaining quantity 기반, 불명확하면 reconciliation/BLOCKED |
| F16 | 헤지 역할/선물 대체 | 확정 | mini futures 5는 보호 수단; 옵션 헤지 대체; 선물→옵션 동일수량 치환 금지; No.1168 BUY2 비재사용 |
| F17 | 포지션/노출 대사 | 확정 | 체결·open lots·잔여 수량과 일치 전 추가 주문 금지 |
| F18 | 손절/최대손실 | 검증값 | stop_loss_enabled/stop_loss_pt 설정; 계좌 위험 한도는 별도 설정·승인 |
| F19 | 이익 청산/트레일링 | 검증값 | advance 이후 고점 대비 갭×ratio 반전; reversal_min_pt 조합은 후보만 |
| F20 | 시간 종료/만기 | 확정+사용자 확인 필요 | 약 30분 창 확정; 종료 시 기존 포지션 처리와 expiry/overnight는 미확정 |
| F21 | 헤지/재반전 청산 순서 | 확정+사용자 확인 필요 | 재반전 시 헤지 청산 및 원 옵션 이익 실현; 체결 경합/실현 가능한 순서는 검증 필요 |
| F22 | P&L·비용 | 확정 | 옵션 premium/fills/승수/수수료/슬리피지 기준; underlying proxy를 옵션 P&L로 취급 금지 |
| F23 | trigger 우선순위 | 사용자 확인 필요 | 같은 snapshot에서 advance, reversal, stop, session end 동시 발생 시 우선순위 |
| F24 | provenance/config logging | 확정 | run/group/leg/order/execution/position + config version/hash 기록 |
| F25 | restart/중복 신호 복구 | 확정 | 시작 전 open orders/fills/positions 재대사; 불일치 시 신규 주문 금지 |
| F26 | 전략 간·계좌 위험 | 확정+사용자 확인 필요 | S1/S9 포함 premium/margin/stress exposure 합산; 한도값·중복 계산 계약 미확정 |
| F27 | 데이터 오류 | 확정 | stale/missing/conflicting authoritative inputs → fail-closed |
| F28 | 설정·버전 | 확정 | external editable config, null/PROVISIONAL fail-closed, 실행별 version/hash |
| F29 | 테스트/수용 | 확정+검증값 | 요구사항-명세-코드-테스트 추적; REAL_VTS evidence와 사용자 승인 별도 |

## 5. 상태 전이표

| 상태 | 이벤트/가드 | 다음 상태 | 동작/실패 처리 |
|---|---|---|---|
| DISABLED | 사용자 설정 활성화, status/config 검증 | WAITING_FOR_SESSION 또는 BLOCKED | PROVISIONAL/null/invalid이면 BLOCKED |
| WAITING_FOR_SESSION | 공식 거래일·세션 시작·전일 종가 source 확인 | GAP_CHECK | source/time 불명확하면 UNAVAILABLE |
| GAP_CHECK | abs(open-prev_close) < min_gap_pt | NO_TRADE_TODAY | 해당 세션 진입 없음; 임의 gap logic 추가 금지 |
| GAP_CHECK | abs(gap) >= min_gap_pt 및 모든 preflight 통과 | ENTRY_PLANNED | 갭 상승 CALL BUY, 하락 PUT BUY; ATM identity/ask/비용 확인 |
| ENTRY_PLANNED | idempotency/group 저장 후 주문 제출 | ENTRY_WORKING | 주문 접수는 체결 아님 |
| ENTRY_WORKING | 전량 체결 및 position reconciliation | TRACKING_PRE_ADVANCE | 실제 fill/position lot만 노출로 기록 |
| ENTRY_WORKING | 부분체결/거절/미체결/취소 경합 | PARTIALLY_EXPOSED 또는 RECONCILIATION_REQUIRED | 체결된 leg/수량 보호; 미체결을 체결로 간주하지 않음 |
| TRACKING_PRE_ADVANCE | 갭 방향 진행이 advance_pt 미만, 반전폭 < hedge_reversal_pt | TRACKING_PRE_ADVANCE | 관찰 지속; null 설정이면 진입 자체 차단 |
| TRACKING_PRE_ADVANCE | advance 도달 전 반전 >= hedge_reversal_pt | HEDGE_ENTRY_PLANNED | 반대 옵션 hedge_contracts=1 매수 계획; 위험·호가 preflight |
| HEDGE_ENTRY_PLANNED | 헤지 전량 체결·대사 | HEDGED_PRE_ADVANCE | 실제 양 레그 노출 재계산 |
| HEDGE_ENTRY_PLANNED | 부분체결/거절/미체결 | PARTIALLY_EXPOSED 또는 BLOCKED | blind retry 금지; 위험 노출에 따라 안전 조치/대사 |
| TRACKING_PRE_ADVANCE | 갭 방향으로 advance_pt 이상 진행 | TRACKING_POST_ADVANCE | 최고가/고점 watermark 갱신; 이후 반전은 이익 청산 trigger |
| TRACKING_POST_ADVANCE | 고점 대비 반전 >= max(gap×reversal_ratio, reversal_min_pt) 후보 | PROFIT_EXIT_PLANNED | max 조합은 검증 후보, 승인된 config가 없으면 차단 |
| HEDGED_PRE_ADVANCE | 가격 방향이 다시 원 옵션 방향으로 재반전 | REHEDGE_EXIT_PLANNED | 헤지 청산 계획; 실제 fill/remaining lots로 수량 결정 |
| REHEDGE_EXIT_PLANNED | 헤지 flat 확인 | TRACKING_OR_PROFIT_EXIT | 원 옵션 이익 여부는 actual option P&L/trigger 기준으로 평가 |
| any active | 휩소 발생 | WHIPSAW_COUNTED | 정의된 카운트 단위/재발생 기준이 미확정이면 상태 BLOCKED; 임의 카운트 금지 |
| WHIPSAW_COUNTED | count < whipsaw_limit | appropriate tracking/hedge state | 실제 노출 대사 후에만 재개 |
| WHIPSAW_COUNTED | count >= 2 | DAILY_STOP_EXIT | 당일 신규 진입 전면 중단 및 포지션 청산 계획 |
| PROFIT_EXIT_PLANNED / DAILY_STOP_EXIT | close order(s) | EXIT_WORKING | per-leg 주문/체결 상태 독립 추적 |
| EXIT_WORKING | 전량 flat 및 execution/P&L reconciliation | CLOSED_TODAY | config hash, fills, costs, reason 기록 |
| any active | session_minutes 경과 | SESSION_END_PENDING | session_end_action null이면 BLOCKED; 후보 행동 중 하나를 임의 선택하지 않음 |
| SESSION_END_PENDING | 승인된 close_all / hold / close_hedge_only | SESSION_END_MANAGED | 각 후보의 실제 시나리오 검증과 승인 필요; hold는 잔여위험·overnight 규칙 필요 |
| any state | restart/API/data/position mismatch | RECONCILIATION_REQUIRED | restore orders/fills/positions/config before strategy evaluation |
| RECONCILIATION_REQUIRED | authoritative reconciliation 성공 | prior safe state or BLOCKED | 불일치 잔존 시 신규 주문 금지 |

### 헤지 집행·레그별 상태 계약

헤지 계획은 원 옵션과 반대 옵션을 하나의 `group_id` 아래 묶되 각 `leg_id`의 주문·체결·취소·잔여수량은 독립 관리한다. Group plan 제출은 원자적 체결을 보장하지 않는다. 각 주문은 client_order_id/idempotency key를 보존한다.

- 주문 ACK/WORKING ≠ FILLED; 취소 요청 ≠ 취소 완료.
- 부분체결은 체결된 수량만 포지션에 반영하고 남은 주문은 별도 상태로 추적한다.
- 한쪽 레그만 체결되면 즉시 실제 net exposure/손실 시나리오를 재계산하고 추가 신규 진입을 막는다. 정의된 안전 회복 정책이 없거나 quote/position source가 불명확하면 BLOCKED/RECONCILIATION_REQUIRED로 멈춘다.
- 미체결/거절은 실제 포지션이 없는 것이 확인되기 전까지 무포지션으로 가정하지 않는다.
- 취소 경합 중 fill은 반드시 execution report와 position lot에 반영한다. 중복 주문을 blind retry하지 않는다.
- 청산은 요청 수량이 아니라 authoritative remaining quantity를 기준으로 한다. flat 판정은 모든 관련 lot이 0이고 read model과 execution ledger가 대사된 경우에만 한다.
- 주문 가격·재가격·timeout·취소 후 복구 값이 미확정이면 신규 주문 차단.

## 6. 코드-의도 차이표 (읽기 전용 정적 조사)

| 대상 | 현재 관찰 사실 | 의도 대비 분류 | 필요한 후속 |
|---|---|---|---|
| `core/strategy/track5_gap_divergence.py` | 기존 로직은 z-score/expected-move/mean-reversion 후보, CALL/PUT와 Futures 방향, mini futures qty=5, stop/target proxy, evaluation-call timeout을 포함 | **불일치**: 갭 방향 ATM 매수 대신 반전(mean reversion) 방향 해석이 중심; 선물 5 수익원/실행 레그로 취급; 옵션 실제 premium 기반 trigger 미확인 | 승인 전 수정 금지. F01/F05/F11/F16/F19/F20 대조 |
| `Track5ExecutionInput` 및 `Track5State` (같은 파일) | `mini_futures_quantity=5`, `futures_side`, futures close flags 등 선물 상태 존재 | **잔재(폐기 대상)**: 사용자가 확정한 옵션 헤지 대체 의도와 불일치 | 선물 5 로직을 S5 목표에서 재사용 금지 |
| runtime_factory / `resolve_track5` | 이번 읽기 조사에서는 정확한 파일 경로와 해당 함수 본문을 확인하지 못함 | **미구현/미확인**으로 단정 불가; 조사 미완료 | runtime_factory 실제 경로와 resolver call chain 확인 필요 |
| `tests/strategy/test_strategy5.py` | 파일 존재 및 478줄 전략 파일 읽기 확인; 테스트 본문 전체는 이번 출력에서 온전하게 확인되지 않음 | **미확인**; 기존 테스트를 신규 의도 승인/검증으로 사용 금지 | 테스트 이름·fixture·assertion을 읽기 전용으로 매핑 |
| 설정/위험 preflight | 설정 스키마는 PROVISIONAL; authoritative quote/contract/cost/capital 검증과 runtime enforcement 증거 없음 | **미구현/차단** | null/PROVISIONAL fail-closed와 계좌 aggregate risk 확인 |
| BUY2 | No.1168은 폐기됨 | **잔재/재사용 금지** | 문서·설정·테스트 목표로 재도입하지 않음 |

## 7. v0.2 U/G/I 레지스터 대조 원칙

v0.2 본문은 D01–D10 명칭을 사용하며, 이 사본에서 U01–U15/G 게이트/I01–I16의 원문 레지스터 전체를 식별하지 못했다. 따라서 아래 표는 원문 U/G/I를 확인했다고 가장하지 않는 **신규 매핑 초안**이다. 누락 없는 대조를 위해 matrix v0.4의 해당 레지스터 원문과 추가 대조가 필요하며, 이 확인 전에는 완전성 PASS를 선언하지 않는다.

| 초안 ID | 항목 | 분류 | 근거 |
|---|---|---|---|
| U01 | 공식 시가/첫 tick/전일 종가 기준 | 사용자 확인 필요(출처·시각 검증) | F03–F04 |
| U02 | min_gap_pt 값과 경계 | 설정 이관 | F05, 사용자 의도 3/8 |
| U03 | advance_pt 값·경계 | 설정 이관 | F11, 사용자 의도 4 |
| U04 | hedge_reversal_pt | 설정 이관 | F11, 사용자 답변 4.1 |
| U05 | reversal_min_pt 및 ratio 결합 | 설정 이관 | F11, 사용자 답변 4.4 |
| U06 | session_end_action | 설정 이관 | F20, 사용자 답변 4.2 |
| U07 | stop_loss_enabled/stop_loss_pt | 설정 이관 | F18, 사용자 답변 4.3 |
| U08 | ATM 동률/계약 identity/tick | 사용자 확인 필요 | F08–F09 |
| U09 | 주문 가격·재가격·취소 규칙 | 사용자 확인 필요 | F07/F13 |
| U10 | 부분체결·한쪽 레그 체결 recovery | 확정 해결 방향, 구현 전 검증 필요 | F14–F17 |
| U11 | 휩소 발생·카운트 정의 | 사용자 확인 필요 | whipsaw_limit=2는 확정 의도이나 카운트 이벤트 정의 미정 |
| U12 | 재반전 시 헤지 청산과 원 옵션 이익 판정 | 사용자 확인 필요 | F21/F23 |
| U13 | 30분 종료 후 hold/overnight/expiry | 사용자 확인 필요 | F20 |
| U14 | S1/S9와 premium·margin·stress risk 합산 | 사용자 확인 필요 | F26, No.1151 |
| U15 | REAL_VTS 샘플 수·검증 기간·승인 수용 기준 | 사용자 확인 필요 | F29, 사용자 의도 8/9 |

### G 게이트 미충족 항목

| Gate 초안 | 현재 판정 | 근거/요구 |
|---|---|---|
| G01 config validity/status | 미충족 | status PROVISIONAL/null 설정 차단 구현 증거 없음 |
| G02 authoritative open/previous close/calendar | 미충족 | 공식 시가·전일 종가 provenance/freshness |
| G03 option master/ATM/expiry/multiplier/quote | 미충족 | 실제 계약·호가 identity |
| G04 premium/fees/slippage/margin/capital | 미충족 | authoritative cost inputs 및 계좌/전략 한도 |
| G05 leg-level order/fill/cancel race | 미충족 | partial/reject/unfilled/cancel-race recovery |
| G06 actual option P&L and reversal watermark | 미충족 | premium/fill/mark/cost 기반 계산 |
| G07 session end/stop/expiry policy | 미충족 | 후보 시나리오 및 승인 |
| G08 account aggregate exposure incl. S1/S9 | 미충족 | double-count-free position provenance |
| G09 REAL_VTS tuning/holdout evidence | 미충족 | 튜닝/검증 기간 분리, 반복 가능 증거 |
| G10 traceability/user approval | 미충족 | 코드-명세-테스트 map과 별도 사용자 승인 |

### S5 관련 I01–I16 상호작용 초안

| ID | 상호작용 | 처리 원칙 |
|---|---|---|
| I01 | S5 ↔ S1: tail-defense 옵션/헤지 중복 | 계약·방향·expiry·group provenance로 중복 노출 확인 |
| I02 | S5 ↔ S9: overnight/event insurance와 같은 방향 옵션 중복 | S5 세션 종료 후 잔여 포지션을 S9의 포지션으로 간주하지 않음; 대사 필요 |
| I03 | S5 ↔ S1/S9: premium 합산 | 실제 체결/잔여 수량으로 계좌 premium cap 합산, 원장/position 중복 금지 |
| I04 | S5 ↔ S1/S9: margin/capital | authoritative margin/capital source 없으면 신규 진입 차단 |
| I05 | S5 ↔ 공통 Risk: max loss/stress | 옵션 hedge를 선물과 동일수량/동일위험으로 가정하지 않음 |
| I06 | S5 ↔ Option Master | exact expiry/strike/type/multiplier identity 일치 필수 |
| I07 | S5 ↔ MarketDataHub | official open, previous close, quote as-of/freshness 동기화 |
| I08 | S5 ↔ OMS | group plan과 leg order 상태 분리 |
| I09 | S5 ↔ ExecutionReport | execution_id/filled qty/remaining qty 대사 |
| I10 | S5 ↔ PositionLotStore | 부분 청산·헤지 청산의 remaining lots 보존 |
| I11 | S5 ↔ Session/Calendar | KST session start와 30분 종료를 공식 거래일 기준으로 처리 |
| I12 | S5 ↔ Config registry | version/hash가 실행과 모든 결정에 연결 |
| I13 | S5 ↔ restart/recovery | 복구 전 신규 신호/주문 차단 |
| I14 | S5 ↔ whipsaw daily stop | 한도 2 도달 후 같은 날 신규 진입 금지 |
| I15 | S5 ↔ P&L ledger/Control Tower | 실제 option premium P&L와 account P&L 구분 |
| I16 | S5 ↔ REAL_VTS evidence | VTS/derived/synthetic provenance를 혼합하지 않고 tuning/holdout 분리 |

## 8. 완전성 및 승인 게이트

- F01–F29는 모두 분류했지만, 일부는 사용자 확인 필요 또는 검증값이다.
- 설정으로 이관한 값은 확정 운영값이 아니다. null/PROVISIONAL이면 신규 거래 차단.
- v0.2의 U/G/I 원문 레지스터 전체 대조는 **BLOCKED**이며, 이 문서는 이를 완료했다고 주장하지 않는다.
- 승인 전 코드 구현·전략 테스트·commit/push는 금지.
- 상태: **draft / unverified / unapproved**.

## 9. 정정 부록 — 기존 통합표 레지스터와 원격 resolver 조사 (2026-10-12)

이 절은 §7의 임시 U/G/I 매핑을 정정하고 우선 적용한다. 실제 `02_decision_factor_integrated_design_matrix_v0.4.md` 원문에는 U01–U15, I01–I16, G01–G12가 존재한다. §7에서 U01–U15를 새로 재번호화한 매핑은 폐기한다. 기존 ID를 보존하고 신규 모호점만 U16 이후에 추가한다.

### 기존 U01–U15 중 S5 관련 항목

| 기존 ID | 원문 범위 | S5 분류 | 근거/후속 |
|---|---|---|---|
| U01–U04 | S1–S4 전략별 미결 | 변경 없음 | S5에서 재사용/재번호화하지 않음 |
| U05 | S5 Futures role/qty/terminal sequence | **확정 해결(의도)** + 검증 필요 | Futures 5는 헤지 수단이며 옵션 헤지로 대체. 반대 옵션 1계약, whipsaw 2회, advance 전/후 반전 분기. 실제 주문/비용/상태 구현은 미검증 |
| U06–U09 | S6–S9 전략별 미결 | 변경 없음 | S5 결정으로 전파하지 않음 |
| U10 | 계좌 자본 및 전략/계좌 위험 수치 | **설정 이관** + 사용자 확인 필요 | 외부 설정 schema와 검증 설계. 실제 자본/프리미엄/최대손실/증거금 숫자 확정 아님 |
| U11 | 공통 주문·부분체결·취소·재시작 상태 지속성 | **확정 해결 방향** + 검증 필요 | 공통 상태 계약은 적용하되 S5의 모든 leg/state 조합 runtime evidence 필요 |
| U12 | 계좌 전체 노출/상관/상계 정책 | **사용자 확인 필요** | S1/S9 포함 premium·margin·stress exposure 합산과 중복 제거 |
| U13 | authoritative P&L/fee/multiplier source | **사용자 확인 필요** | 실제 option fill/mark/fees/slippage/multiplier source |
| U14 | exact expiry/session/rollover common service | **사용자 확인 필요** | 30분 진입창 종료와 보유 포지션 종료 정책, exact YYYYMMDD expiry |
| U15 | Shrimp Resume Context access/update | **UNAVAILABLE** | 이번 세션에 Shrimp/graft 도구가 노출되지 않아 실제 상태 확인/갱신 불가; 갱신했다고 주장하지 않음 |

### 기존 G01–G12 수용 게이트

| Gate | S5 판정 | 증거/필요 조건 |
|---|---|---|
| G01 목적/경제적 역할 | 의도 해결, 구현 미검증 | gap-direction option alpha와 option hedge role 명세 |
| G02 진입/추가/청산 신호 | 검증값/미완료 | min_gap, advance, reversal, stop, session end 경계 시나리오 |
| G03 계약/만기/수량/승수 | 미충족 | authoritative Option Master/expiry/ATM/multiplier/quote |
| G04 부분체결/거절/취소/timeout | 미충족 | 각 leg 독립 주문·체결 상태 및 cancel-race recovery |
| G05 헤지/재조정/overlay | 의도 해결, runtime 미검증 | opposite option 1 contract; Futures 5 제거; No.1168 BUY2 비재사용 |
| G06 손절/목표/트레일링/시간청산 | 설정 이관/미완료 | null 설정 차단; session_end_action 후보별 비교 |
| G07 세션/만기/롤오버 | 미충족 | 30분 경계, 종료 후 포지션 정책, exact expiry |
| G08 자본/프리미엄/최대손실/계좌 위험 | 미충족 | editable settings, authoritative fee/margin/cost, account aggregation |
| G09 실패/재시작/복구 | 설계 방향 확정, 증거 미충족 | restore orders/fills/lots and reconcile before re-entry |
| G10 요구사항-명세-코드-테스트 추적 | 부분 작성, 미완료 | 모든 F01–F29를 실제 코드/test IDs/evidence에 연결 |
| G11 authoritative source/freshness | 미충족 | open/previous close/option quote/contract identity freshness |
| G12 사용자 승인 및 버전 경계 | 확정 규칙, 현재 미승인 | v0.3 초안은 승인 전 구현 불가 |

### I01–I16 상호작용 레지스터 정정

S5 관련 영향은 다음과 같다: I01 account capital/premium/max-loss/margin; I02 shared Futures identity; I03 option holdings/delta attribution; I04 insurance-pair overlap including S1/S9; I05 multi-leg partial fill/cancel race; I06 strategy/account P&L; I07 expiry/session/overnight; I08 risk-vs-profit/hedge exit priority; I09 data freshness; I10 restart/duplicate/state restore; I11 S5 Futures-role/option alternative; I16 editable-config consistency. I12(S3), I13(S4), I14(S8), I15(S6/S7/S9 re-entry)는 S5 설계로 바꾸지 않으며 cross-strategy account risk의 입력 범위에서만 관련될 수 있다. 각 원본 I ID는 보존하고, 이 명세는 새 번호로 대체하지 않는다.

### Resolver / test static evidence update

- Runtime resolver 위치 확인: `application/composition/automated_virtual_runtime_factory.py`, `resolve_track5` line 445; resolver purpose labels include `TRACK5_GAP_HEDGE_FUTURES_EXIT`, `TRACK5_GAP_HEDGE_TERMINAL_EXIT`, `TRACK5_GAP_HEDGE_OPTION_EXIT`, and registry registration near line 497. This confirms the current composition path explicitly contains Futures-exit lifecycle branches; it does not prove every branch executes at runtime.
- `tests/strategy/test_strategy5.py` includes tests asserting option BUY 1 + mini futures 5, Futures-first close, quantity 5, evaluation-count timeout, and grouped exit behavior (e.g. test names around lines 70–355). These assertions are historical implementation coverage, not validation of the newly specified intent.
- This investigation did not execute tests. Runtime factory and test code remain unchanged.

### 신규 미결 U16–U20 (이번 명세 작성 중 새로 식별)

| ID | 신규 모호점 | 필요한 확인/검증 | 상태 |
|---|---|---|---|
| U16 | whipsaw 1회로 카운트하는 이벤트의 정확한 정의(가격 교차, hedge 진입, 방향 전환 중 무엇인지) | 동일 시세 반복·중복 신호를 포함한 이벤트 정의와 idempotency 시나리오 | 사용자 확인 필요 |
| U17 | ATM 동률·호가 없는 경우의 계약 tie-break | authoritative Option Master/quote 기준의 결정적 선택; 대체 계약 추정 금지 | 사용자 확인 필요 |
| U18 | 동일 snapshot에서 stop, reversal, profit exit, session end가 동시에 성립할 때 우선순위 | 상호 배타적 우선순위와 전이표 | 사용자 확인 필요 |
| U19 | 헤지 청산 후 당일 원 옵션을 계속 보유/청산/재진입하는 범위 | 재진입 횟수·신호 idempotency·daily stop 상호관계 | 사용자 확인 필요 |
| U20 | “장 시작” 기준 시각을 공식 거래소 개장 시각, 공식 시가 timestamp, 첫 유효 관측 중 무엇으로 삼는지 | source timestamp/received timestamp와 지연·누락 시 처리 | 사용자 확인 필요 |

U16–U20은 기존 U01–U15를 변경하지 않는 신규 ID다. 값이나 규칙을 추측해 채우지 않는다.
