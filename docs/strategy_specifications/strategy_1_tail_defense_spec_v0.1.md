# Strategy 1 — Tail Defense 신규 상세 명세 v0.1

- 문서 상태: **초안(작성 중)**
- 작성일: 2026-10-12
- 저장소/브랜치: Leedalsoo/KOSPI200_Project / Project200
- 조사 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 승인 상태: **미승인 — 구현 기준으로 사용할 수 없음**
- 구현/주문 상태: 이 문서 작성 중 전략 코드 변경, 테스트 실행, KIS 주문 실행은 하지 않음

> 아래의 “현재 코드에서 확인된 사실”은 현 구현의 설명일 뿐, 새 전략의 요구사항이나 승인으로 간주하지 않는다. 목표 전략 로직은 검토·검증·사용자 승인 전까지 확정되지 않는다. 미정의 동작은 임의 추정으로 구현하지 않고 BLOCKED로 남긴다.

## 1. 전략의 상위 정의

### 1.1 이름과 범위

- 전략 ID(현 코드): TRACK1_TAIL_DEFENSE
- 현 구현 버전: 1.1.0
- 주요 파일:
  - core/strategy/track1_tail_defense.py
  - application/composition/track1_runtime_input_provider.py
  - application/composition/standard_runtime_input_provider.py
  - application/composition/automated_virtual_runtime_factory.py
  - core/strategy/strategy_execution_proposal.py
  - core/risk/delta_hedge_quantity.py 및 core/delta_hedge_quantity.py
  - contracts/position_provenance.py 및 MultiLegBridge/PositionLotStore 실행 경계

### 1.2 목적과 역할 — 검토 필요

“Tail Defense”라는 이름과 현 구현은 옵션 fence와 조건부 선물 헤지를 사용하려는 의도를 시사한다. 그러나 이름이나 기존 코드만으로 사용자의 최종 목적, 허용 손실, 목표 payoff, 보호 대상 포지션, 월물별 유지 정책을 확정하지 않는다.

미정 사항:
1. 전략의 1차 목적: 급격한 하락 tail-risk 보호, 양방향 급변 보호, 프리미엄 수익 또는 다른 목적 중 무엇인가.
2. 보호 대상: Strategy 1이 직접 만든 옵션만인지, 다른 전략/계좌의 short-option 노출까지 포함하는지.
3. CALL/PUT 각 레그의 목적과 손익 역할.
4. 월물 시작부터 만기까지 유지할지, 매 거래일 초기화할지, 매일 조건에 따라 재구성할지.
5. 허용 최대손실·프리미엄·증거금·헤지 빈도·최대 노출.
6. 목표 payoff 및 보호 성능을 판정할 정량적 기준.

### 1.3 상품·계정 범위

- 프로젝트 기본 범위인 KOSPI200 옵션을 대상으로 한다. 일반 옵션/미니 상품을 혼용하거나 다른 상품을 자동 추가하지 않는다.
- 옵션 유형, 행사가, 정확한 만기일 YYYYMMDD, 종목 identity, 승수 및 거래 가능 여부는 authoritative Option Master/계약 데이터로 확인한다.
- 현 StrategyExecutionProposal에는 옵션 유형과 행사가가 있으나, 이것만으로 정확한 만기/브로커 종목 identity가 확정되지는 않는다.
- 현재 실행 환경은 Virtual/VTS 검증이다. 별도 명시적 승인이 없는 한 KIS Live 주문은 금지한다.

## 1.4 현재 유효 확정 결정과 범위 경계

최근 확정 Decision Log를 조회해 Strategy 1 명세와 직접 관련된 현재 기준을 반영한다. 아래 결정은 코드의 옛 동작을 승인한다는 뜻이 아니며, 새 전략의 세부 규칙은 별도 명세와 사용자 승인으로 정한다.

- **No.1151 (2026-10-12):** Strategy 1~9를 자본금·증거금·거래비용 관점에서 재설계한다. Futures를 일괄 제거하지 않고 실제 역할을 PRIMARY_ALPHA/SPREAD와 HEDGE로 분류하며, 옵션 기반 전환은 헤지 목적 leg부터 검토한다. 선물 수량을 같은 수량의 옵션으로 단순 치환하지 않는다. 계약 identity, quote, Greeks/수량 근거, 프리미엄 예산, 최대손실 및 비용 gate가 필요하다.
- **No.1131 (2026-10-10):** 기존 투자 원리는 아키텍처 리팩터링만으로 임의 변경하지 않는다. 현재 사용자의 새 지시는 Strategy 1~9의 상세 명세를 새로 작성하라는 것이므로, 이번 초안은 코드와 lifecycle을 재정립하되 Strategy 1의 원래 투자 목적을 확인 없이 바꾸지 않는다. 목적/투자 thesis 변경이 필요하다고 판단되면 별도 쟁점으로 보고한다.
- **No.1132/No.1134 (2026-10-10):** grouped execution, leg별 authoritative fill/provenance, partial/reject/unknown reconciliation을 적용한다. 주문 요청만으로 완료 처리하거나 실제 flat 확인 전에 상태를 reset하지 않는다.
- **No.1070 (2026-10-05):** 옵션 선택 대상은 일반 KOSPI200 옵션이다. Mini KOSPI200 옵션은 사용하지 않으며, Mini KOSPI200 선물은 별도 Futures identity 경계에서 검토할 수 있다.
- **No.1119 (2026-10-08):** 만기 identity는 authoritative Option Master로 해소한 exact YYYYMMDD를 사용한다. YYYYMM을 실제 만기일로 임의 변환하지 않는다.
- **No.1046 (2026-10-03):** 검증 판단은 현재 코드 → 현재 확정 결정 → 현재 AGENTS.md → 실제 데이터/source → 새 검증 순서로 한다.

따라서 이 문서는 전략 상세 초안이며 투자 thesis 변경, 헤지 구조 변경, 자본/손실 수치 확정 또는 구현 승인이 아니다. 해당 변경이 필요하면 근거와 영향을 명시해 사용자에게 확인받는다.
## 2. 현재 코드의 확인된 동작 — 요구사항이 아님

### 2.1 입력과 상태

Track1Input 입력:
- momentum_confirmed
- days_to_expiry
- current_time
- active_vol, base_vol
- coverage_ratio
- short_option_net_delta

Track1State 상태:
- base_price, fence_distance
- active_fence_type, active_fence_strike, active_fence_tag
- futures_hedge_count, hedge_count_date
- active_hedge, hedge_entry_price, active_hedge_quantity
- profit_buffer, market_opened

현 코드의 initialize/reset은 상태를 초기화한다. 소스에는 _hedge_exit_pending 초기화가 4회 중복되어 있고 on_execution_result 메서드도 2회 중복 정의되어 있다. Futures entry 신호 생성 시 active_hedge/hedge quantity/일일 횟수를 fill 확인 전에 설정하며, on_execution_result는 FUTURES_UNWIND만 처리한다. Futures entry의 reject/partial/unknown을 state에 반영하는 경로가 없다. 이는 코드 품질 및 lifecycle 위험이지 신규 명세의 요구사항이 아니다.

### 2.2 최초 fence 생성

첫 평가에서 기초가격을 base_price로 저장하고 아래 세 신호를 반환한다.

| 레그(현 코드) | 자산/방향 | 수량 | 행사가 계산 |
|---|---|---:|---|
| 바깥 CALL | OPTION BUY | 1 | 최초 평가 가격 + 12.5 후 strike tick 반올림 |
| 바깥 PUT | OPTION SELL | 1 | 최초 평가 가격 - 12.5 후 strike tick 반올림 |
| 안쪽 PUT | OPTION SELL | 1 | 최초 평가 가격 - 7.5 후 strike tick 반올림 |

이 표는 현 코드 동작이다. 3-leg 구조를 신규 명세의 최종 구조로 채택할지는 별도 검토가 필요하다.

첫 평가 가격이 공식 정규장 시초 가격이라는 보장은 없다. 변동성에 따른 fence_distance 변경은 최초 strike 구성에 반영되지 않는다. 최초 세 레그 중 현 상태에 추적되는 active fence는 안쪽 PUT 하나뿐이다. 실행 resolver resolve_track1은 Futures proposal만 직접 처리하고 OPTION proposal에는 None을 반환한다. RuntimeStrategyToDecisionAdapter는 이 경우 SINGLE_ORDER plan으로 fallback하므로 최초 세 option leg는 하나의 grouped MultiLegExecutionPlan이 아니라 서로 분리된 단일 주문으로 제출된다. 레그 간 partial-fill/cancel-race/그룹 flat 확인이 이 전략 resolver에서 조정되지 않는다.

### 2.3 변동성 규칙

현 코드 상수:
- INITIAL_FENCE_DISTANCE = 7.5
- OUTER_FENCE_DISTANCE = 12.5
- VOLATILITY_EXPANSION_MULTIPLIER = 1.15
- FENCE_APPROACH_RATIO = 0.9

active_vol > base_vol * 1.15이면 fence_distance=12.5, 아니면 7.5로 변경된다. 이 값은 이후 fence 접근 임계값에 쓰이지만 최초 세 레그의 strike 구성은 고정 계산식을 사용한다.

신규 명세에서는 active_vol/base_vol의 출처, 단위, 산식, 관측 시각, 갱신 주기, 결측/오래된 값 처리 및 변동성 변경 시 보유 레그 재구성 여부를 정해야 한다.

### 2.4 Fence 접근과 모멘텀

현재 접근 조건:
- 활성 fence가 PUT이면 price <= base_price - fence_distance * 0.9
- 활성 fence가 CALL이면 price >= base_price + fence_distance * 0.9

접근 상태에서 momentum_confirmed=True, 일일 헤지 횟수가 한도 미만이고 활성 헤지가 없을 때 선물 헤지 후보를 생성한다.

Track1RuntimeInputProvider는 최근 12개 간격을 둔 ROC를 계산한다. 기록 부족 또는 분모 0이면 None을 반환하고, 전략 입력에서는 bool로 취급되어 false가 될 수 있다. 현재 momentum 방향 판정은 fence_type이 CALL이면 ROC 양수, PUT이면 ROC 음수다. 최종 의도와 일치하는지는 미확정이다. Track1RuntimeInputProvider는 strategy_id가 같은 모든 open lots를 모으지만 OptionInstrumentIdentity/FuturesInstrumentIdentity를 구분하지 않는다. short_target은 모든 SELL lot을 합산하고, delta 계산도 모든 SELL lot의 identity에서 expiry/option_type/strike를 읽는다. 동일 전략의 Futures SELL lot이 포함되면 옵션 identity 전용 필드 접근 실패 또는 잘못된 delta source 조회가 발생할 수 있다. coverage_ratio는 계산되어 전달되지만 현재 Track1TailDefense.evaluate에서 사용되지 않는다.

### 2.5 선물 헤지와 되돌림 청산

현 코드 상수:
- HEDGE_REVERSION_POINTS = 1.5
- max_hedge_allowed 기본값 20회/일
- 헤지 수량은 short_option_net_delta를 delta_to_mini_futures_qty에 전달해 계산한다.

활성 fence가 PUT이면 선물 SELL, CALL이면 선물 BUY 방향을 설정한다. 헤지 수량이 양수가 아니면 신호를 만들지 않는다. 진입가격 대비 유리한 방향으로 1.5포인트 되돌림 조건이 충족되면 FUTURES_UNWIND 신호를 생성한다.

automated_virtual_runtime_factory.py의 resolve_track1에서 FUTURES_UNWIND는 open-lot 기반 close plan으로 연결되고, 그 외 선물 제안은 futures single-leg plan으로 연결된다. 헤지 횟수와 active hedge state는 주문 체결 전 증가/설정되므로 주문 거절 또는 부분체결 시 내부 상태와 실제 Futures position이 어긋날 수 있다.

새 명세에서는 델타 부호·단위·승수·선물 승수·헤지 방향·반올림·최대 수량·재헤지·부분청산·체결가 기준·거래비용·손익 기준을 수식으로 확정해야 한다. 현 구현 수치와 이름만으로 승인된 정책이라 취급하지 않는다.

### 2.6 만기 잔존일수(DTE) 처리

현 코드는 days_to_expiry <= 4.0이면 active fence가 있을 경우 해당 active_fence_type/strike/tag에 대해 옵션 청산 후보를 한 건 만들고, 바로 내부 active_fence 상태를 지운 뒤 평가를 반환한다. 해당 OPTION proposal도 resolve_track1에서 grouped close plan을 만들지 않으므로 SINGLE_ORDER fallback에 의존한다.

문제 및 제한:
- 최초 생성한 세 레그 중 현재 활성 상태로 추적되는 것은 안쪽 PUT 하나다.
- 청산 신호 생성은 주문 접수/체결/잔여 수량 0 확인과 다르다.
- 실제 포지션 identity/잔여 수량 및 체결 완료 확인 전에 상태를 지운다.
- CALL과 바깥 PUT의 만기 생명주기가 이 경로에서 함께 보장되지 않는다.
- DTE는 float 입력이며 정확한 계약 만기일과 세션 cutoff를 직접 명시하지 않는다.

따라서 DTE 4일은 현 코드의 관찰값일 뿐 최종 강제청산 정책으로 확정되지 않았다. 모든 필수 레그의 실제 flat 확인 전 전략 종료/상태 초기화는 금지한다.

## 3. 신규 명세의 공통 필수 조건

다음은 사용자의 현재 작업 지시에서 정한 안전·완전성 기준이며, Strategy 1 고유의 시장 판단 규칙과 구분한다.

1. 모든 판단은 timestamp가 있는 authoritative input snapshot을 기준으로 한다.
2. 계약 identity는 상품, 옵션 유형, 행사가, 정확한 만기일, 종목 ID, 승수와 함께 유지한다.
3. 주문 제안, 주문 접수, 부분체결, 체결, 취소 요청, 취소 확인, 취소 중 체결을 서로 다른 상태로 기록한다.
4. 전략 레그는 독립적으로 주문·체결 상태를 추적하되 그룹 전체 노출과 위험을 함께 계산한다.
5. timeout/통신 오류는 미체결의 증거가 아니다. broker/order/execution/position을 대사하기 전에 같은 주문을 재전송하지 않는다.
6. 청산 수량은 신호의 원래 수량이나 cached quantity가 아니라 authoritative open lots의 실제 잔여 수량으로 계산한다.
7. 각 체결은 run_id, strategy_id, group_id, leg_id, client_order_id, execution_id, instrument identity와 연결한다.
8. 실제 포지션과 내부 상태가 불일치하거나 입력이 누락/오래된 경우 BLOCKED 또는 RECONCILIATION_REQUIRED로 중단한다.
9. 모든 필수 레그의 잔여 포지션이 0임을 확인하기 전 전략 상태를 초기화하거나 다음 lifecycle을 시작하지 않는다.
10. 계좌 전체 위험 한도와 다른 전략의 중복 노출을 고려한다. 런타임 강제 증거가 없으면 위험 검증 PASS를 선언하지 않는다.
11. 가상/모의 결과를 Live 주문 검증으로 표현하지 않는다.

## 4. 목표 lifecycle 초안

아래는 검토용 개념 모델이며 현재 코드에 전부 구현되어 있다는 뜻이 아니다.

1. DISABLED — 전략 비활성화 또는 운용 허가 없음.
2. WAITING_FOR_SESSION — 공식 거래일/세션 및 계약 확인 대기.
3. DATA_WARMUP — 가격 이력·변동성·모멘텀·옵션 체인/호가 입력 축적 중.
4. PRE_ENTRY_CHECK — 계좌 위험, 계약, quote freshness, 자본/비용, 기존 포지션 중복 확인.
5. ENTRY_PLANNED — 의도한 레그와 목표 수량 확정, 주문 제출 전.
6. ENTRY_WORKING — 레그별 주문 접수/대기 중.
7. PARTIALLY_EXPOSED — 일부 레그 또는 수량만 체결되어 불완전한 구조가 노출됨.
8. PROTECTED_ACTIVE — 승인된 보호 구조의 필수 수량 체결 및 포지션 대사 완료.
9. HEDGE_WORKING — 선물 헤지/조정 주문 진행 중.
10. EXIT_PENDING — 청산 조건 발생, 주문/체결/대사 진행 중.
11. EXPIRY_MANAGEMENT — 계약 만기/최종 거래 세션 청산 관리.
12. RECONCILIATION_REQUIRED — 주문·체결·포지션 데이터 불일치 또는 결과 미확정.
13. BLOCKED — authoritative source, 위험 판단 또는 전이 규칙이 없음.
14. FLAT_CONFIRMED — 모든 전략 소유 레그의 실제 잔여 포지션 0 확인.
15. CLOSED — flat 상태와 최종 손익/수수료가 대사되고 lifecycle 종료.

### 4.1 재시작 규칙

프로세스 재시작 시 메모리 상태를 초기화해 신규 진입하지 않는다. broker/Virtual Broker 주문 상태, fills, open lots, contract identity 및 strategy/group provenance를 복원·대사한다. 복원 불가능하면 RECONCILIATION_REQUIRED/BLOCKED로 둔다.

### 4.2 월물/거래일 경계

명세는 월물 시작, 각 거래일 장 시작 전·시초·장중·장 종료, overnight, 다음 거래일 시초 갭, 만기 7/4/1일 전 및 만기 당일을 다룬다. 정확한 거래소 세션/최종거래시간은 authoritative calendar와 contract master를 기준으로 한다. 각 경계에서 진입·유지·축소·청산 중 무엇을 할지는 미결정 사항을 확정하기 전까지 정하지 않는다.

## 5. 레그별 계약·주문 명세 틀

신규 전략이 승인되기 전에는 현 3-leg 구조를 목표로 고정하지 않는다. 최종 구조 확정 시 모든 레그에 아래 필드를 채운다.

| 필드 | 필수 정의 |
|---|---|
| leg_id / 역할 | CALL 보호, PUT fence, short exposure, futures hedge 등. 손익/위험 설명과 함께 승인 |
| 자산/방향 | OPTION/FUTURES 및 BUY/SELL |
| 계약 identity | 상품, option type, strike, exact expiry, instrument ID, multiplier |
| 수량 | 산식, 최소/최대, 반올림, 추가·축소 규칙 |
| 진입 | 신호 조건, quote preflight, 주문 유형, limit 가격 및 재가격 규칙 |
| 체결 | partial/no-fill/reject/cancel-request/cancel-confirm/cancel-race 처리 |
| 보호/헤지 관계 | 보호 대상 레그, 커버 수량 산식, 잔여 uncovered exposure 제한 |
| 청산 | trigger, close side, authoritative remaining qty, order type, timeout/retry |
| 만기 | 최종 거래 세션, cutoff, 미체결/부분체결 처리, flat 확인 |
| 회계 | fill price, fees, slippage, multiplier, realized/unrealized P&L, provenance |
| 실패 안전 | 차단 사유, 수동 조치 필요 여부, 재개 조건 |

## 6. 주문 및 부분체결 시나리오 — 필수 검증

| 시나리오 | 필수 처리 결과 |
|---|---|
| 모든 진입 레그 preflight 통과 | 승인된 plan 생성. 실제 제출/체결은 별도 상태 |
| 하나라도 계약/quote/위험 검증 실패 | 그룹 제출 전 차단; 사유와 입력 provenance 기록 |
| 첫 레그만 체결 | PARTIALLY_EXPOSED; 실제 노출 재계산 후 승인된 대기/취소/보정/청산 정책 적용 |
| 일부 수량만 체결 | fill 수량만 position에 반영, 미체결 수량은 별도 관리 |
| 주문 거절 | 거절 레그/그룹을 기록; 이미 체결된 다른 레그는 승인된 정책으로 관리 |
| 미체결/timeout | 미체결로 단정하지 않고 broker state 조회 및 reconciliation |
| 취소 요청 중 체결 | 취소 요청과 체결 이벤트를 재조정하고 실제 잔여 수량 기준으로 처리 |
| hedge 일부 체결 | 실제 futures lot 기준으로 uncovered/overhedged exposure 재계산 |
| 청산 일부 체결 | EXIT_PENDING 유지; 실제 잔여 lot 수량으로 남은 close 계산 |
| 포지션 0 확인 전 재시작 | 주문/체결/lot 복원 전 신규 진입 금지 |
| 만기 cutoff에 주문 미체결 | broker 상태와 실제 open lots 대사; 만기 후 위험을 추정하지 않음 |
| stale/missing Greeks 또는 quote | 신규 헤지/진입 차단; 기존 포지션 위험 상태는 BLOCKED |
| 여러 전략의 동일 계약 노출 | strategy ownership과 계좌 aggregate exposure를 함께 계산; 자동 netting 금지(명시 규칙 전) |

## 7. 위험·손익 모델 — 미확정

필요한 모델:
- 각 옵션 leg의 실제 체결 프리미엄, bid/ask 또는 authoritative mark, tick size, 수수료, 슬리피지.
- 각 옵션 계약의 multiplier와 정확한 만기 identity.
- 선물 헤지의 실제 계약 identity/multiplier, 체결가, 수량, 증거금 및 스트레스 손익.
- 전략별 총 premium at risk, 최대손실 또는 정의된 스트레스 손실, delta/gamma/vega/theta 노출.
- 다른 전략 및 계좌 전체 포지션을 합산한 총위험.
- 부분체결 상태의 현재 노출과 최악의 추가 체결/취소 race 시나리오.

현 코드의 profit_target=500000, profit_buffer, coverage_ratio는 목표 정책이 검증되었다는 증거가 아니다. 현재 evaluate 경로에서 profit_target, profit_buffer 및 coverage_ratio는 전략 판단에 사용되지 않는 필드/값으로 보인다. 위험 한도는 설정 파일/패널로 조정 가능하게 설계할 수 있으나, 수치와 enforcement 위치는 승인 및 런타임 검증 전에는 확정하지 않는다.

## 8. 데이터 계약

| 데이터 | 목적 | 필수 유효성 검사 | 누락/오류 시 |
|---|---|---|---|
| Underlying quote/tick | 기준 가격·접근 조건 | source, event/received time, freshness, positive price | 신규 판단 차단 |
| Official trading calendar/session | 거래일/세션/시초/종료 | timezone KST, session ID, holiday/expiry rules | BLOCKED |
| Option Master | exact contract identity | product/type/strike/expiry/instrument ID/multiplier | 주문 금지 |
| Option quote/orderbook | premium, liquidity, limit price | bid/ask validity, timestamp, tick, crossed/empty market | 해당 레그 주문 금지 |
| IV/volatility | fence regime | formula, source, unit, timestamp, baseline window | regime 전환/신규 진입 차단 |
| Underlying history | momentum/ROC | ordered timestamps, lookback completeness, duplicate/gap handling | warmup 또는 UNAVAILABLE |
| Open lots/position | current exposure/close qty | run/strategy/group/leg identity, remaining qty, side, role | reconciliation |
| Option Greeks/delta | hedge sizing | contract match, as-of timestamp, source and units | 신규 헤지 차단 |
| Order/execution reports | order/fill lifecycle | unique IDs, cumulative-vs-delta semantics, sequence | reconciliation |
| Fees/margin/risk config | net P&L/risk gate | config version, effective time, runtime enforcement evidence | BLOCKED |

## 9. 코드-명세 추적 기준

| 요구사항 ID | 명세 영역 | 현재 관련 코드 | 신규 검증 산출물 |
|---|---|---|---|
| S1-GEN-01 | 전략 상태/평가 | core/strategy/track1_tail_defense.py | 상태 전이표 + 단위/시나리오 테스트 |
| S1-IN-01 | Runtime input | application/composition/track1_runtime_input_provider.py | source provenance/freshness 테스트 |
| S1-IN-02 | 입력 조립 | application/composition/standard_runtime_input_provider.py | unavailable propagation 테스트 |
| S1-ORD-01 | Futures hedge/close resolver | application/composition/automated_virtual_runtime_factory.py (resolve_track1) | plan→order→fill→position E2E |
| S1-OPT-01 | 옵션 계약/레그 계획 | core/strategy/strategy_execution_proposal.py 및 Option Master 경계 | exact expiry/instrument identity 테스트 |
| S1-RISK-01 | 델타/수량 | core/risk/delta_hedge_quantity.py, core/delta_hedge_quantity.py | sign/unit/multiplier/rounding 테스트 |
| S1-LIFE-01 | 만기/세션 | Strategy 1 + calendar/expiry source | 월물/거래일/만기 경계 시나리오 |
| S1-REC-01 | 복구/대사 | execution bridge, PositionLotStore, execution callback | restart/duplicate/partial/cancel-race 테스트 |

관련 테스트 파일을 확인했다: tests/strategy/test_strategy1.py 및 tests/strategy/test_strategy_contract_safety.py. 현재 test_strategy1.py는 최초 3개 option signal과 missing delta의 Futures hedge 차단만 검사하며, resolver에서의 SINGLE_ORDER fallback, 그룹 체결, partial fill, cancel-race, DTE close 후 실제 flat, Futures entry reject 후 state reconciliation은 검사하지 않는다. 기존 테스트의 존재/과거 PASS는 신규 명세의 승인이나 검증을 뜻하지 않는다.

## 10. 미결정 목록 — 승인 전 확정 금지

- D1: 전략의 공식 목적과 보호 대상 노출.
- D2: 최종 옵션 구조. 현 CALL BUY + PUT SELL + PUT SELL을 유지할지, 각 레그의 보험/수익/헤지 역할.
- D3: 기준 가격의 의미: 정규장 시초, 전략 활성화 시점, 월물 기준 가격 중 무엇인지.
- D4: fence 거리/strike rounding과 변동성 적응식.
- D5: 변동성 지표 정의, 기준 창, threshold, regime 변경 중 보유 레그 처리.
- D6: momentum 계산의 lookback, ROC/방향/확인 기간 및 데이터 공백 처리.
- D7: 선물 헤지의 역할, 방향, 수량 공식, 델타 단위/승수, 상한, 재헤지와 unwind 조건.
- D8: 헤지 횟수 제한이 주문 시도/접수/실제 체결 중 무엇을 카운트하는지.
- D9: 수익 목표·손절·최대손실·최대 프리미엄·계좌 전체 위험 수치.
- D10: 월물 시작부터 만기까지 유지할 레그와 일별 reset/재진입 규칙.
- D11: DTE 7/4/1일 전 및 만기 당일의 각 레그별 종료 정책과 cutoff.
- D12: 주문 유형, limit/reprice interval, timeout, cancel/retry 및 partial-fill 후 hedge/rollback 정책.
- D13: option quote/mark/Greeks/fees/margin authoritative provider와 freshness SLA.
- D14: 다른 전략/계좌의 동일 계약 포지션과 분리·집계 규칙.
- D15: 전략 OFF, 재시작, 연결 끊김, 거래일 전환 및 월물 교체 중 기존 포지션 관리.
- D16: profit_target, profit_buffer, coverage_ratio의 의미와 런타임 사용 여부.
- D17: 전략 성공/보호 성능을 판정할 객관적 scenario set 및 acceptance criteria.

## 11. 초기 시나리오 검증 목록

- 정상 월물 첫 진입 및 모든 레그 체결.
- 공식 시초 전 데이터와 시초 직후 데이터 구분.
- 시초 gap 및 첫 tick 지연.
- 변동성 기준 바로 아래/동일/바로 위.
- fence 임계값 직전/정확히 일치/초과.
- momentum lookback 부족, 중복/누락 timestamp, stale input.
- short-option delta 양수/음수/0/누락, 승수 누락 및 stale Greeks.
- hedge 수량 0/1/상한/상한 초과.
- 헤지 주문 거절, 부분체결, timeout, cancel-race, 중복 평가.
- 1.5-point 되돌림 직전/정확히 일치/초과(현 동작 관찰용이며 최종 trigger 미확정).
- DTE 5/4/3/1/0 및 exact expiry/session cutoff.
- 3개 옵션 레그 중 하나/둘/모두 부분체결, 한 레그 거절.
- 만기 청산 중 한 레그만 체결, 취소 중 체결, stale position snapshot.
- 프로세스 재시작 후 주문/체결/lot 복원.
- 같은 계좌 내 다른 전략의 동일 계약 노출 및 aggregate risk.
- 모든 필수 레그 flat 확인 후 새 lifecycle 재개.
- 가격/계약/달력/위험 소스 오류 복구 후에만 재개.

## 12. 초안 판정과 다음 절차

- 상태: **초안**.
- 현 코드 사실 매핑: 부분 완료. Strategy 1 직접 코드, runtime input provider, context 조립 및 Futures resolver 경로를 확인했다.
- 전략 의도/target policy: 미확정.
- 명세 완전성 검증: 미완료.
- 시나리오 검증: 계획만 작성, 실행하지 않음.
- 사용자 승인: 없음.
- 구현 가능 여부: **BLOCKED — 미승인 초안이며 핵심 전략 결정이 남아 있음**.

다음 작업은 미결정 목록을 전략 목적/레그 역할/시간축/헤지 정책 순서로 정리하고 검토를 반영해 v0.2로 갱신하는 것이다. 이후 공통 lifecycle/state machine과 Strategy 1 규칙의 모순을 검증한다. 사용자 승인 전에는 전략 코드를 수정하지 않는다.
