# Strategy 2 — Asymmetric Trap 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track2_asymmetric_trap.py v1.0
- 연결: automated_virtual_runtime_factory.py resolve_track2, Track2PlanAdapter, Option Contract Source, common Analytics, MultiLegBridge.

## 1. 목적 — 미확정
현재 구현은 변동성·거래량·미세구조·IV skew를 사용해 short strangle과 더 안쪽 long option을 조합하는 4-leg trap을 시사한다. 최종 목적, 방향별 위험, 손익 목표, premium-neutral 조건은 사용자 확인 전 확정하지 않는다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- 필수 analytics: volatility.bbw, volume.z_score, microstructure.obi, futures.basis, options.put_iv, options.call_iv, volume_profile.poc, volatility.active/base. 누락/unavailable이면 신호 없음.
- 진입 게이트: bbw truthy, volume z-score >3, abs(OBI)>0.5, basis>0.3, abs(price-POC)>1.0.
- 가격이 POC 위면 PUT IV < CALL IV, 아래면 CALL IV < PUT IV 조건을 사용한다.
- active_vol <= base_vol*0.85: short CALL/PUT ATM±10, long CALL/PUT ATM±5. 그 외 short ATM±7.5, long ATM±2.5. 기본 수량 1씩이며 resolver가 4-leg plan을 구성한다.
- 일일 entry cap=2, 손실 후 cooldown=15분. cutoff 시 evaluate_trap을 호출하지만 cutoff만으로 강제청산하지 않는다.
- STOP_LOSS_RATIO=-30%는 underlying current_price/entry_price 변화 기준이며 actual option-pair P&L이 아니다.
- trailing activation +30%; high-watermark tier 50%/100%에 따라 85/88/90% 유지.
- state는 진입 체결 전 _trap_active로 바뀐다. 진입의 partial/reject 결과를 동기화하는 명시적 callback 경로가 부족하다.
- TRAP_CLOSE는 open lots로 종료 plan을 만든다. 만기/expiry 정책은 없다.
- trailing close 후 short-switch timer가 일부 경로에서 초기화되지 않아 다음 lifecycle에 잔존할 수 있다.

## 3. 목표 lifecycle
DISABLED → DATA_WARMUP → PRE_ENTRY_CHECK → ENTRY_PLANNED → ENTRY_WORKING → PARTIALLY_EXPOSED/ACTIVE → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. Partial, reject, timeout, cancel-race, restart는 RECONCILIATION_REQUIRED로 분기한다.

## 4. 필수 데이터와 주문 계약
- underlying/POC/volume/OBI/basis/BBW/IV source, units, timestamps, freshness.
- Option Master의 일반 KOSPI200 option, exact YYYYMMDD, type, strike, instrument ID, multiplier.
- 각 leg의 bid/ask, depth, tick, premium, fill, fees/slippage.
- 4-leg별 독립 주문/체결 상태와 group 전체 net premium, max loss, Greeks/exposure.
- order type, mid-price offset 1 tick, reprice interval, timeout, cancel/replace 규칙은 새로 승인한다.

## 5. 미결정 항목
1. zero-cost wide/narrow trap의 실제 경제적 정의와 선택 목적.
2. 4-leg 유지 여부, 각 leg의 역할/ratio/strike rounding.
3. OBI/basis/IV skew 방향과 결합 논리.
4. STOP_LOSS가 underlying move인지 actual net P&L인지.
5. trailing을 actual option pair MTM 기준으로 바꿀지.
6. daily 2회 카운트 기준, cooldown 시작/손실 판정 source.
7. expiry, cutoff, overnight 규칙.
8. partial entry 후 wait/cancel/reprice/hedge/rollback/close 우선순위.
9. premium budget, max loss, margin, fee/slippage gate와 account risk.
10. pre-fill state를 authoritative fills로 전환하는 방법.

## 6. 검증 시나리오
Feature unavailable/stale/threshold 경계; OBI±0.5, basis 0.3, POC 거리 1.0; wide/narrow 경계; 모든 4-leg fill/partial/reject/timeout/cancel-race; stop/trailing tiers; 15분 cooldown, 날짜 변경, daily cap; expiry; restart; stale quote와 contract identity mismatch; actual flat 전 중복 close 방지.

## 7. 추적/판정
관련 코드: track2_asymmetric_trap.py, build_trap_plan, resolve_track2, Option Contract Source/Track2PlanAdapter, MultiLegBridge/PositionLotStore.
**BLOCKED** — P&L proxy, pre-fill state, expiry 및 partial-fill risk policy 미확정.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

**표 읽기 규칙**
- 현재 사실은 조사 기준 HEAD에서 관찰한 코드·테스트 동작이며 신규 요구사항이나 승인 규칙이 아니다.
- 목표 명세는 공통 안전 계약 및 필요한 설계 산출물이다. 전략 고유 threshold/payoff/leg ratio는 별도 승인 전 미결정이다.
- 미결정/BLOCKED 항목은 구현하지 않는다. 과거 수치·구현·테스트 PASS를 자동으로 신규 기준으로 승격하지 않는다.
- F01~F29 ID는 Strategy 1과 통합설계표에서 같은 의미로 사용한다.

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | short CALL/PUT와 더 안쪽 long CALL/PUT로 4-leg trap을 구성한다. 명칭은 Asymmetric Trap이나 payoff/zero-cost 조건이 정량 정의되지 않았다. | 전략이 노리는 IV/volatility/price regime, 각 레그의 손익·위험 역할, 목표 payoff 및 stress scenarios를 명시한다. | **미결정** — thesis 및 비용 구조 검증 필요 |
| F02 | 적용 시장·상품 | 전략은 OPTION 4-leg를 계획한다. Resolver는 Option Master identity를 이용하지만 일반 KOSPI200과 Mini option을 명시 필터링하는지 추가 확인 필요. | 일반 KOSPI200 옵션만 허용하고 Mini 옵션은 제외한다. 모든 레그에 exact contract identity와 동일 상품군 확인. | **부분 확인 / BLOCKED** — product-class filter 증거 필요 |
| F03 | 운용 주기·활성화 경계 | session date 변경 시 일일 진입 수를 reset하고 MarketSessionPolicy.MARKET_CUTOFF 이후 evaluate_trap으로 넘어간다. 월물/expiry lifecycle은 없다. | 공식 KRX session/calendar와 entry window, daily counter reset, expiry/overnight lifecycle을 분리 정의한다. | **미결정** — cutoff/expiry policy 필요 |
| F04 | 기준가격·기준시점 | 현재 KOSPI200 tick price를 POC와 비교하며 entry_price는 underlying price로 저장한다. MarketSnapshot instrument_identity는 None으로 설정된다. | underlying, POC, volume, OBI, basis, IV 각각 source/as-of/freshness/unit/provenance를 보존하고 동일 snapshot 정합성을 보장한다. | **미결정** — cross-source timestamp and identity contract 필요 |
| F05 | 진입 신호·조건 | required metrics는 BBW, volume z-score, OBI, Futures basis, PUT/CALL IV, POC, active/base volatility. 조건: BBW truthy, z>3, abs(OBI)>0.5, basis>0.3, POC 거리>1.0 및 위치별 IV skew. | 각 feature의 산식/단위/threshold/경계와 조합 논리를 승인하고 stale/missing input은 진입 차단. | **미결정** — 조건의 경제적 근거와 boundary policy 필요 |
| F06 | 추가 진입·재구성 | daily cap=2지만 evaluate 경로에 이미 _trap_active인 경우를 차단하는 guard가 명확히 없다. 진입 시 상태/카운트를 pre-fill로 변경한다. | 활성 그룹 또는 entry pending 상태에서 중복 진입 금지. 추가 진입은 별도 승인된 scale-in rule, budget reserve 및 group ID로만 허용. | **BLOCKED** — duplicate active entry 가능성 |
| F07 | 대기·진입 취소 | 전략은 entry signal/proposal을 반환한다. Strategy 2의 pending entry cancel/replace/partial timeout policy는 없다. | 각 leg별 ACK/working/partial/cancel request/cancel confirm/cancel-race/timeout을 추적하고 idempotent reconciliation 수행. | 공통 execution 계약 확정; Strategy 2 연결 **미검증** |
| F08 | 옵션 계약 선택 | Resolver가 현재 날짜 이후 가장 가까운 만기를 고른 뒤 공통 PUT/CALL strike 중 underlying과 가장 가까운 strike를 ATM으로 선택한다. multiplier 존재·양수·PUT/CALL 동일성을 검사한다. | authoritative Option Master에서 일반 KOSPI200, exact YYYYMMDD, option type, strike, instrument ID, multiplier, tradability를 검증하고 만기 선택 기준을 승인한다. | **부분 확인 / BLOCKED** — product-class, expiry, liquidity selection 미검증 |
| F09 | 행사가·tick·거리 | wide: short ±10, long ±5; narrow: short ±7.5, long ±2.5. strike tick rounding이 build_trap_plan 경계에서 명시되지 않는다. | strike tick/rounding, listed-strike lookup, ATM tie-break, strike spacing 및 unlisted strike rejection을 명시한다. | **미결정** — current offsets are observations only |
| F10 | 변동성·regime | active_vol <= base_vol*0.85이면 wide, 그 외 narrow. BBW evaluator는 window의 마지막 값이 최솟값인지 boolean으로 계산. KIS metrics source는 futures price/volume observations로 BBW/volume/active/base volatility를 파생한다. | BBW/active/base 산식, windows, units, sample sufficiency, regime boundary equality, source timestamp and regime-switch behavior를 고정한다. | **미결정** — current boolean BBW and volatility interpretation require validation |
| F11 | 모멘텀·미세구조·IV skew | abs(OBI)>0.5, basis>0.3, abs(price-POC)>1.0. POC 위에서는 PUT IV<CALL IV, POC 아래/같음에서는 CALL IV<PUT IV 조건. | OBI/basis/POC/IV units, sign convention, strike/expiry matched IV source, boundary equality and simultaneous conditions를 승인한다. | **미결정** — skew direction/threshold rationale 필요 |
| F12 | 수량·자본·비용 | ENTRY_QUANTITY=1 per leg, total 4 legs; MAX_DAILY_ENTRIES=2; 15-minute cooldown. Strategy-specific premium/max-loss/account-capital enforcement는 이 경로에서 입증되지 않음. | editable config로 계좌 총자본, 전략별 최대 프리미엄, 전략별·계좌 전체 최대손실, margin, fee/slippage, max qty를 설정하고 실제 routing 전 enforcement. | **수치 미확정** — 근거·검증 후 별도 승인 |
| F13 | 주문 유형·가격·재가격 | build_asymmetric_trap 결과에 MID_PRICE_OFFSET/1 tick metadata가 있으나 execution plan의 각 leg에 requested limit price를 넣지 않는다. | bid/ask/depth 기반 per-leg limit price, net-debit/credit group constraint, reprice interval/count, cancel/replace and timeout을 정의한다. | **미결정** — pricing metadata만으로 주문 가격이 확정되지 않음 |
| F14 | 그룹 사전검증 | Track2ExecutionPlanAdapter는 approved signal, strategy, group_id 및 4-leg plan 길이를 검사한다. Multi-leg risk gate는 leg별 approval과 전체 fail-closed를 지원한다. 실제 runtime 연결의 모든 조건은 별도 검증 필요. | 4-leg 전체 contract/quote/liquidity/cost/premium/max-loss/Greeks/account-risk preflight가 통과하기 전 어떤 leg도 제출하지 않는다. | 공통 기준 존재; **Strategy 2 runtime E2E 미검증** |
| F15 | 부분체결·거절·미체결·취소 race | _trap_active, entry_price, daily count, entry strike는 entry fill 전 갱신된다. entry execution callback 경로는 확인되지 않으며 close callback만 존재한다. | 4-leg 각자 order/fill/remaining qty/position 상태를 보존하고 partial/reject/cancel-race에서 노출과 worst-case 추가체결 위험을 재계산한다. | **BLOCKED** — pre-fill state와 fill lifecycle 단절 |
| F16 | 헤지·재조정·추가 leg | 4-leg trap 외 별도 hedge/rebalance leg는 확인되지 않는다. | 추가 hedge/overlay를 자동 추가하지 않는다. 필요 시 payoff/stress analysis와 별도 승인 후 role, trigger, qty, unwind를 정의한다. | **미결정** — 임의 hedge 추가 금지 |
| F17 | 보유 상태·노출 | state는 entry underlying price/instrument, short PUT strike, high-watermark ratio와 timers를 저장하며 per-leg fill/identity/quantity를 보유하지 않는다. | 각 4-leg actual lots의 identity/side/qty/fill/mark/role와 group net Greeks/exposure를 대사한다. | **BLOCKED** — per-leg authoritative position state 필요 |
| F18 | 손절·위험 종료 | STOP_LOSS_RATIO=-0.30은 (current underlying - entry underlying)/entry underlying 기준이다. stop 발생 시 _last_loss_at을 fill 확인 전에 설정한다. | hard stop과 max-loss는 actual option group P&L/stress-loss basis로 정의하고 trigger priority와 exit batch를 승인한다. Underlying move는 별도 market trigger로 표시한다. | **미결정** — 현재 -30%는 옵션 손실률이 아님 |
| F19 | 익절·trailing | underlying return ratio의 high watermark가 +30%에서 활성화. high watermark <50%면 85%, >=50%면 88%, >=100%면 90% retention ratio로 close trigger를 계산한다. | actual option pair/group MTM with fills, marks, multiplier and fees를 사용하고 high-watermark update order, tier boundary, giveback, P&L sign을 명시한다. | **미결정** — 현재 trailing은 option P&L proxy |
| F20 | 시간 종료·만기·롤오버 | cutoff 또는 daily cap이면 evaluate_trap을 호출하지만 cutoff만으로 강제청산하지 않는다. exact expiry/last-trading-day close policy 없음. | official session cutoff, exact expiry, overnight holding, next-day risk, final-trading cutoff 및 all-leg flat reset을 정의한다. | **BLOCKED** — expiry policy absent |
| F21 | 청산 범위·수량·방향 | TRAP_CLOSE proposal은 resolver에서 PositionLotStore open lots 기반 close plan으로 변환한다. proposal quantity=1은 실제 close quantity의 source로 취급하면 안 된다. | 실제 open lots의 contract identity/side/remaining qty에서 각 leg의 close direction/quantity를 산출하고 group completion을 authoritative position flat으로 확인한다. | 공통 close principle 확정; Strategy 2 terminal semantics **미검증** |
| F22 | 손익·수수료·슬리피지 | strategy stop/trailing uses underlying price ratio; authoritative option premium MTM, per-leg fees, multiplier and realized/unrealized P&L are not consumed in evaluate_trap. | per-fill premium, authoritative marks, multiplier, fees, slippage, per-leg and combined P&L plus account P&L attribution을 분리한다. | **BLOCKED** — actual option P&L basis missing |
| F23 | 트리거 충돌·종료 우선순위 | _exit_pending 우선 차단. evaluate_trap은 short-switch timeout을 먼저 보고, active/entry checks 이후 stop, high-watermark and trailing. cutoff/daily-cap branch calls evaluate_trap before entry gates. | expiry/hard max-loss/terminal close/stop/trailing/cooldown/entry triggers의 deterministic precedence를 명시. EXIT_PENDING 중 신규 진입 금지. | **미결정** — timer and close reason interactions need resolution |
| F24 | 공통 lifecycle·provenance | entry plan group_id is run_id + canonical signal_id; adapter builds four legs; close callback checks group_complete and position_flat. Per-leg lifecycle persistence isn't shown in strategy state. | run/group/evaluation/exit_batch/leg/client_order/execution IDs and config hash are linked through plan→orders→fills→lots→P&L. | common contract 확정; **full Strategy 2 lifecycle 미검증** |
| F25 | 재시작·중복·timeout 복구 | reset clears counters, high-watermark and short-switch timers; durable state restoration/idempotency is not shown. After trailing close, _short_switch_at can remain after group closes because callback clears it only for SHORT_SWITCH_TIMEOUT_EXIT. | restart restore orders/fills/open lots/timers/counters/config hash; no duplicate group or blind retry; all timers reset only according to approved lifecycle state. | **BLOCKED** — stale timer and restart policy |
| F26 | 전략 간·계좌 전체 위험 | no strategy-specific account aggregate exposure calculation appears in Track2 evaluate. | aggregate 4-leg and all-strategy short/long exposure, margin, premium, correlated stress loss and shared-contract risk; do not silently net positions across strategy ownership. | **미결정** — account-level runtime enforcement evidence required |
| F27 | 오류·데이터 불가 처리 | required feature validation returns no signal when metrics unavailable. Analytics requests declare authoritative source and 1-second freshness; provider builds no snapshot when any required observation is None. | stale/missing/identity-mismatched input maps to UNAVAILABLE/BLOCKED; existing positions remain reconciled and managed; no synthetic zero or inferred quote. | common fail-closed agreed; full data freshness enforcement **미검증** |
| F28 | 설정 한도·자본·재개 | thresholds are class constants/configurable parameters. Runtime-loaded editable total capital, strategy premium cap, strategy/account max-loss and enforced resume guard are not proven here. | versioned editable settings include total capital, per-strategy max premium, per-strategy/account max loss, margin/fees/slippage, daily count/cooldown, effective time and hash. | **수치·강제경로 미확정** — separate validation/approval required |
| F29 | 필수 테스트·수용 기준 | tests/strategy/test_strategy2.py checks 4-leg plan shape and missing analytics fail-closed only. | test every threshold boundary, repeated active entry, 4-leg partial/reject/cancel race, actual P&L, expiry, restart, timer cleanup, config and account-risk boundaries. | **미완료** — existing tests do not prove full lifecycle |

## 9. Strategy 2 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | 명시적 ON + config loaded | WAITING_FOR_SESSION | strategy ON/ENTRY permission/config version 확인 | 설정 불명확이면 BLOCKED |
| WAITING_FOR_SESSION | official session + required sources available | DATA_WARMUP | KRX calendar, source timestamp, feature windows and expiry contract 확인 | UNKNOWN/stale이면 UNAVAILABLE |
| DATA_WARMUP | all features valid and sufficient | PRE_ENTRY_CHECK | unavailable과 false condition 구분 | history 부족이면 warm-up 유지 |
| PRE_ENTRY_CHECK | all gates + 4-leg contracts/quotes/risk pass | ENTRY_PLANNED | approved offsets/qty/strike ticks, premium budget reserve | any leg fails → group 미전송 |
| ENTRY_PLANNED | stable group_id/idempotency key recorded | ENTRY_WORKING | 4 independent leg orders with shared group provenance | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | all required quantities filled and reconciled | ACTIVE | authoritative fills/open lots confirm all four legs | mismatch → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | any partial/reject/no-fill/cancel race | PARTIALLY_EXPOSED | calculate current and worst-case exposure; follow only approved recovery rule | no recovery policy → BLOCKED |
| ACTIVE | stop/trailing/terminal trigger | EXIT_PENDING | exit batch from actual open lots; per-leg close state | missing close plan → BLOCKED |
| ACTIVE | another entry signal while active | ACTIVE | duplicate entry prohibited unless explicit scale-in policy approved | no duplicate order |
| any holding state | expiry/session cutoff | EXPIRY_MANAGEMENT | exact expiry/calendar and terminal policy; no new entry | policy/source absent → BLOCKED |
| EXIT_PENDING / EXPIRY_MANAGEMENT | close fills pending | same state | partial fills/cancel-race and actual remaining qty reconciliation | unknown timeout → RECONCILIATION_REQUIRED |
| EXIT_PENDING / EXPIRY_MANAGEMENT | all required lots confirmed flat | FLAT_CONFIRMED | actual position read model matches execution ledger | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | final P&L/fees reconciled | CLOSED | save result, config version/hash, group provenance | accounting mismatch → BLOCKED |
| any state | restart/source/API/transport failure | RECONCILIATION_REQUIRED | restore orders, fills, lots, counters and timers before entry | cannot reconcile → BLOCKED |
| RECONCILIATION_REQUIRED | all authoritative sources reconcile | prior valid state or FLAT_CONFIRMED | no blind retry, no duplicated group | residual uncertainty → BLOCKED |

상태 전이 제약:
1. 4-leg plan이 만들어졌다는 사실은 4개 주문의 접수/체결을 의미하지 않는다.
2. 그룹 risk preflight는 모든 필수 레그를 검사해야 하며, 주문 전 reject 시 그룹 전체를 fail-closed한다.
3. 부분체결 후에는 이미 체결된 leg를 보존하고 실제 노출을 계산한다. 원자적 4-leg 체결을 가정하지 않는다.
4. trailing 종료 후 남는 short-switch timer는 다음 lifecycle의 의도치 않은 close를 만들지 않도록 명시적 상태로 관리한다.

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S2-F01~F06, F09~F12, F16~F19, F23 | core/strategy/track2_asymmetric_trap.py, core/analytics/track2.py | thesis/payoff review, threshold boundaries, state and P&L tests | BLOCKED — economic rules unresolved |
| S2-F07~F08, F13~F15, F21, F24 | automated_virtual_runtime_factory.py resolve_track2, Track2ExecutionPlanAdapter, Track2OptionContractSource, core/oms/multi_leg_plan.py | 4-leg identity/order/fill/cancel-race/close-flat evidence | BLOCKED — full runtime lifecycle not proven |
| S2-F04, F10~F11, F27 | standard_runtime_input_provider.py, track2_analytics_provider.py, KISTrack2MarketMetricsSource, KISTrack2OptionIVSource | source timestamps, units, freshness, IV identity and missing/stale tests | INCOMPLETE — current source provenance/identity/freshness needs validation |
| S2-F12, F22, F26, F28 | core/risk/*, account/margin/fee providers and editable risk config | premium/max-loss/margin/fee and aggregate-account risk tests | BLOCKED — runtime enforcement evidence missing |
| S2-F20, F25 | MarketSessionPolicy, calendar/expiry source, strategy state persistence | cutoff/expiry/restart/timer cleanup scenarios | BLOCKED — expiry and durable recovery not defined |
| S2-F29 | tests/strategy/test_strategy2.py and Virtual E2E | F01~F29-to-test evidence matrix | INCOMPLETE — existing tests only cover two narrow contracts |

수용 게이트:
- A01: 전략 목적·경제적 payoff·zero-cost 주장·방향별 위험을 수치로 설명한다.
- A02: 모든 leg에 authoritative product/expiry/strike/instrument/multiplier/quote identity가 있다.
- A03: feature thresholds and skew logic have source-backed units, timestamps and boundary tests.
- A04: 4-leg group-wide preflight and per-leg partial/reject/cancel-race lifecycle is verified.
- A05: stop/trailing use actual option group P&L or are explicitly approved as separate underlying triggers.
- A06: expiry, cutoff, cooldown, daily cap, duplicate entry and short-switch timer transitions are deterministic.
- A07: editable capital/premium/max-loss/account risk settings are loaded, versioned and enforced before routing.
- A08: all F01~F29 link to source paths, test IDs, evidence and result.
- A09: validation is separated from explicit user approval.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | trap의 실제 thesis와 4-leg payoff | per-leg payoff, IV/vol regime scenario and fees | 전략 구조 승인 불가 |
| D02 | wide/narrow offsets 및 strike rounding | listed chain, tick rules, scenario analysis | 행사가 선택 기준 미확정 |
| D03 | OBI/basis/POC/IV skew thresholds and direction | source units, synchronized observations, backtest/stress scenarios | entry signal validation blocked |
| D04 | stop-loss and trailing basis | actual option marks/fills vs underlying movement, fee/multiplier model | current -30% and trailing cannot be treated as option P&L |
| D05 | entry cap/cooldown counting semantics | accepted/filled group lifecycle and realized loss attribution | counters may diverge from actual trades |
| D06 | expiry/overnight/cutoff rules | exact expiry, KRX calendar, session and broker capability | position may persist without terminal policy |
| D07 | partial-fill recovery and group unwind | risk worst-case exposure, leg fill order and Virtual broker behavior | no safe recovery until approved |
| D08 | total capital, strategy premium cap, strategy/account max loss values | account capital, authoritative quotes, margin, fee and stress-loss evidence | numerical limits not approved |
| D09 | source freshness and product-class filtering | option master, IV observations, market source provenance | contract/data eligibility blocked |
| D10 | restart, timer cleanup and active-entry idempotency | persistent group/order/fill/position state | duplicate/false close risk |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 문서 구조 검사와 source-to-factor mapping은 진행했으나 complete source, scenario and runtime E2E validation is not complete.
- 핵심 차단: active-entry duplicate guard, pre-fill state/count updates, underlying-based stop/trailing, expiry policy, post-trailing timer cleanup, account-level risk enforcement.
- 코드 변경/테스트/commit/push: 이 문서 작업에서는 수행하지 않는다.
- KIS Live 주문: 실행하지 않는다.
- 다음 작업: Strategy 3를 같은 F01~F29 기준과 깊이로 작성하고, 1~9 상세 명세 완료 후 통합설계표 및 상호작용 검증을 수행한다.
