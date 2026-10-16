# Strategy 1 — Tail Defense 상세 명세 v0.3
- 작성일: 2026-10-12
- 상태: **draft / unverified / unapproved**
- 기준: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 우선 근거: 사용자 직접 지시 2026-10-12 §1. 현재 코드 및 v0.2와 다르면 사용자 의도가 우선한다.
- v0.2는 보존한다. 문서만 갱신하며 코드 수정·테스트 실행·commit/push·KIS Live 주문은 금지한다.
- Fail-closed: 필수 설정 null/invalid/PROVISIONAL 또는 승인/hash/source 검증 실패 시 신규 주문을 차단한다.

## 1. 사용자 확정 의도
1. S1의 기존 미니선물 헤지는 전부 옵션 헤지로 대체한다. 목표 문서·상태기계·시나리오에서 미니선물 헤지는 폐기 대상이다.
2. 월물 초 ATM 기준 +12.5pt CALL BUY 1계약과 -12.5pt PUT BUY 1계약의 넓은 양매수를 보유한다. 이것이 기본 방어다.
- Short accumulation: compare each index move with the current reference point. At +short_step_pt, SELL PUT at previous_reference_point - short_offset_pt; at -short_step_pt, SELL CALL at previous_reference_point + short_offset_pt. Only after deriving the strike, update the reference point to the new ATM. Example: 100→102.5 gives PUT 92.5; 102.5→105 gives PUT 95; 105→107.5 gives PUT 97.5. Downward moves are symmetric for CALL.
4. 매도 잔량 누적 후 되돌림으로 ATM이 매도 행사가에 접근하면 short option 가격 상승으로 손실이 발생할 수 있다. 기본 양매수 1계약만으로는 일부만 방어하므로 옵션 매수 헤지가 필요하다.
5. ATM이 가장 가까운 매도 옵션 행사가에서 hedge_trigger_distance_pt 이내로 접근할 때 헤지를 검토한다. 이 값은 null/미정이며 REAL_VTS 튜닝 비교 후보에 2.5pt와 5.0pt를 포함하되 어느 값도 사전 확정하지 않는다. 하락 케이스는 상승의 대칭이다.
6. 헤지 후보는 “매도 당시 받은 프리미엄과 가장 가까운 가격” 기준. 후보가 여럿이면 가격 거리 최소, 동률이면 유동성 우선. 호가 공백이면 지정가 예약주문 후 30분 대기, 취소 확인 후 다음 후보로 하강한다.
7. 헤지 수량은 연결된 실제 미청산 매도 수량과 1:1이다. 주문 수량이 아닌 fills/잔량 대사가 기준이다.
8. CALL+PUT 합산 매도 미청산 수량 최대 10계약. 도달 시 신규 매도 중단. 헤지 매수는 이 10계약 상한에서 제외하지만 계좌 위험·자금 한도에는 포함한다.
9. ATM이 관련 매도 행사가에서 ±5.0pt 이상 멀어지면 관련 헤지를 청산한다. 만기 4일 전에도 헤지를 청산한다.
10. 월물 만기 4일 전 남은 매도 옵션, 헤지 옵션, 기본 양매수를 모두 전량 청산한다.
11. 지수 움직임이 작아 가두리 매도가 늘지 않으면 추가 행동 없이 현재 보유 포지션을 그대로 둔다.
12. S1에는 폭등락 예상일에 양매수 청산을 보류하는 별도 규칙을 두지 않는다. 기존 규칙이 있으면 의도 불일치로 기록한다. S6/S7/S8은 별도 전략이다.
13. 모든 임계값은 설정 파일로 관리한다. REAL_VTS의 튜닝 기간과 검증 기간을 분리하고, 검증 후 수치 확정을 별도 승인받는다. 실행마다 설정 버전/hash와 적용값을 기록한다.

## 2. F01–F29 판단요소별 재분류
“확정”은 사용자 의도가 명시됐다는 뜻이지 검증·승인 완료가 아니다. 설정값도 PROVISIONAL이며 필수값 null 또는 미승인 설정이면 신규 주문을 차단한다.

| F-ID | 판단요소 | 분류 | S1 목표 및 잔여 | 근거 |
|---|---|---|---|---|
| F01 | 목적/payoff/역할 | 확정 | 기본 wide strangle + short premium + option hedge; Mini Futures hedge 폐기 | §1.1–4 |
| F02 | 상품/자산 유형 | 확정 | S1 hedge는 옵션; 매도할 CALL/PUT 정책은 미정 | §1.1, §1.4 |
| F03 | lifecycle/month cycle | 확정 | 월물 초 시작, DTE4 전량청산 후 다음 월물 시작 전 약 3~4일 휴지 | §1.2, §1.10, 사용자 확정 2026-10-12 |
| F04 | source/time/provenance | 설정값 | REAL_VTS tuning/validation 분리 및 config provenance; quote freshness/master 검증 필요 | §1.13 |
| F05 | 초기 진입/short entry | 확정 | 상승 시 PUT 매도(ATM 아래 offset), 하락 시 CALL 매도(ATM 위 offset); 용어 혼선 제거 | §1.2–3, 사용자 확정 2026-10-12 |
| F06 | 추가 진입/short 누적 | 설정값 | step 2.5, offset 7.5, 합산 cap 10; 매도 정책 미확정이면 차단 | §1.3, §1.8 |
| F07 | pending/cancel/reprice | 설정값 | hedge 지정가, 30분, cancel 확인 후 후보 하강 | §1.6 |
| F08 | identity/expiry | 확정 | authoritative identity, exact YYYYMMDD, mini option 미사용; DTE 의미 미정 | §1.10; No.1119/1070 |
| F09 | strike/tick/rounding | 설정값 | 12.5/7.5/2.5는 PROVISIONAL; tick/master로 계산 | schema |
| F10 | volatility/regime | 확정 | S1에 폭등락 예상일 양매수 청산 보류 또는 변동성 기반 fence 변경을 추가하지 않음 | §1.11–12 |
| F11 | momentum/Greeks/microstructure | 설정값 | 거리 트리거와 프리미엄 가격 비교를 사용; 유동성 동률판정 지표/호가 품질 기준은 검증 가능한 설정으로 이관 | §1.5–6, U21 |
| F12 | session/calendar | 사용자 확인 필요 | 월물 시작/DTE4 종료 외 시작 reference·공백 미정 | §1.2, §1.10 |
| F13 | order type/price/retry | 설정값 | hedge LIMIT + 30분 + cancel confirmation; short order pricing 미정 | §1.6 |
| F14 | grouped plan/legs | 확정 | base CALL/PUT, shorts, hedge options를 역할별 레그로 관리; 원자체결 가정 금지 | §1.2–7 |
| F15 | partial/reject/cancel race | 확정 | 레그별 상태; cancel 중 fill이면 다음 후보 금지; flat 전 reset 금지 | §1.6; No.1132/1134 |
| F16 | hedge/rebalance | 확정 | distance trigger, actual short 잔량 1:1 option buy, ±5 release, DTE4 hedge close; Futures hedge 없음 | §1.4–9 |
| F17 | qty/multiplier | 설정값 | base long 각 1, hedge ratio 1, short cap 10; capital_per_contract 25m 임시값 | §1.2, §1.7–8 |
| F18 | stop/max loss/risk | 설정값 | capital, premium, strategy/account max loss, margin/cost caps editable; 승인 전 차단 | §1.13 |
| F19 | take profit/trailing | 사용자 확인 필요 | 신규 profit/trailing 미정; 기존 코드 값 자동 승계 금지 | §1 |
| F20 | expiry/session/rollover | 확정 | DTE4 전 short+hedge+base strangle 전량청산; flat 전 다음 lifecycle 금지 | §1.9–10 |
| F21 | close plan/order sequence | 설정값 | terminal plan은 모든 잔여 S1 leg 포함; fill/remaining 개별 대사 | §1.10; No.1132/1134 |
| F22 | P&L/fees/slippage | 설정값 | actual fill/qty/multiplier/fees/slippage provenance; 비용 값 미확정 | §1.13 |
| F23 | trigger priority | 확정 | DTE4 close가 신규 short/hedge보다 우선; cancel/reconcile 중 후보 하강 금지; 기타 우선순위 미정 | §1.6, §1.10 |
| F24 | lifecycle/provenance | 확정 | run/group/leg/order/execution IDs, config hash, fill/position evidence 유지 | §1.13; No.1132 |
| F25 | restart/recovery | 확정 | 재시작 시 orders/fills/lots/config 대사; flat 전 reset/re-entry 금지 | §1.6, §1.10 |
| F26 | cross-strategy/account risk | 설정값 | S1 short cap 10과 별도로 계좌 premium/margin/stress risk 합산 | §1.8, §1.13 |
| F27 | data failure | 확정 | null/PROVISIONAL, stale/missing/mismatched quote/identity/position이면 신규 주문 차단 | §0, §1.13 |
| F28 | editable config/resume | 설정값 | config file/version/hash 및 실행별 적용값; 미승인·미검증이면 차단 | §1.13 |
| F29 | test/acceptance | 확정 | REAL_VTS tuning/validation 분리; 시나리오/추적성 작성; 본 작업에서 테스트 미실행 | §1.13 |

분류 집계: **확정 15 / 설정값 12 / 사용자 확인 필요 2 / 합계 29**. 상태 분류는 의도/설정의 확정도를 뜻하며, 검증·승인 완료를 뜻하지 않는다.

## 3. 설정 스키마 초안 — 전부 PROVISIONAL
설정 예시(구현 파일이 아님):
    strategy1:
      status: PROVISIONAL
      config_version: strategy1-v0.3-provisional
      wide_strangle_distance_pt: 12.5
      base_call_buy_contracts: 1
      base_put_buy_contracts: 1
      capital_per_contract: 25000000
      short_step_pt: 2.5
      short_offset_pt: 7.5
      max_short_contracts_total: 10
      hedge_trigger_distance_pt: null
      hedge_release_distance_pt: 5.0
      hedge_ratio: 1.0
      hedge_price_match: sold_premium
      hedge_order_type: LIMIT
      hedge_order_timeout_minutes: 30
      close_all_dte: 4
      max_strategy_premium: null
      max_strategy_loss: null
      account_total_capital: null
      account_max_loss: null
      max_margin_utilization: null
      max_order_cost: null
      max_bid_ask_spread: null
      tuning_dataset_id: null
      validation_dataset_id: null
      approved_config_hash: null

- wide_strangle_distance_pt 12.5: ATM 기준 CALL +12.5, PUT -12.5 후보. 실제 tick-rounded strike 기록 필요.
- max_short_contracts_total 10: CALL+PUT actual open short 잔량과 pending worst-case exposure 합산. hedge BUY는 이 수량 cap에서 제외되지만 account risk에는 포함.
- hedge_ratio 1.0: linked short lot actual remaining qty 기준. filled/pending hedge를 반영해 중복 매수 금지.
- 헤지 후보는 행사가 거리가 아니라 옵션 프리미엄 가격 자체를 매도 당시 받은 프리미엄과 비교한다. 동률이면 유동성이 좋은 후보를 선택한다.
- new_short_stop_dte=7은 폐기됨(사용자 확정, 2026-10-12). 해당 설정을 사용하지 않으며 신규 매도는 DTE4 전량청산 시점까지 다른 승인된 게이트를 통과하는 한 허용한다.
- capital_per_contract=25,000,000은 임시 입력이지 승인 자본금/계약가치가 아니다. 단위와 경제적 의미 확인 전 주문 금지.
- 실행별 기록: run_id, strategy_id, config_version, canonical SHA-256, 적용 설정값, status/validation, KST timestamp/effective time, code commit SHA, REAL_VTS provenance, tuning/validation dataset ID, master/calendar/quote version, risk-gate snapshot, approval reference. 비밀정보는 기록하지 않는다.
- 열린 포지션은 생성 당시 config version/hash를 유지한다. hot reload 정책 확정 전 열린 포지션에 설정을 소급 적용하지 않는다.

## 4. 사용자 확인 질문 상태 및 신규 미결 항목
사용자 확정 답변(2026-10-12)에 따라 기존 질문 U16–U20을 다시 묻지 않는다. 아래 U21–U29는 사용자 의도를 추측해 채우지 않고 추가 확인/검증이 필요한 미결로 등록한다. 별도의 사용자 확인 질문은 현재 없음.

- U21: 유동성 동률판정 지표, 최대 스프레드/호가 깊이/호가 신선도 기준.
- U22: 달력일 DTE와 거래일 DTE 중 기준, authoritative 만기/최종거래일 출처 및 컷오프 시각.
- U23: 월물 시작 ATM 기준시점 및 시초 갭 처리.
- U24: 가두리 매도 지정가/재가격 주기/최대 시도 횟수.
- U25: DTE4 전량청산 레그 거절·유동성 부족 복구 절차.
- U26: REAL_VTS 튜닝/검증 데이터셋 ID, 분리 기간, 합격 기준.
- U27: capital_per_contract=25000000의 단위·경제적 의미.
- U28: RESOLVED BY USER (2026-10-13). Each short_step_pt crossing sells from the PREVIOUS reference point: on an upward crossing, SELL PUT at previous_reference_point - short_offset_pt; on a downward crossing, SELL CALL at previous_reference_point + short_offset_pt. After the strike is determined, refresh the reference point to the newly reached ATM. Values 2.5pt and 7.5pt remain the specified working parameters in this draft.
- U29: 별도 이익실현/trailing 정책이 필요한지. 사용자 의도에 없는 규칙을 임의로 추가하지 않는다.

## 5. 상태 전이표
| 상태 | 조건/입력 | 목표 동작/묶음 | 레그별 체결 처리 | 실패/복구 |
|---|---|---|---|---|
| DISABLED_CONFIG | PROVISIONAL/null/invalid config or source unavailable | 신규 주문 없음 | 기존 fills/lots 보존 | BLOCKED_CONFIG/UNAVAILABLE; 검증 후 재개 |
| MONTH_START_READY | calendar/master로 새 월물 시작, 이전 S1 group flat | ATM reference; CALL +12.5 BUY 1 + PUT -12.5 BUY 1 grouped plan | 두 레그 주문/fill/remaining 개별 추적 | 한쪽만 fill이면 ENTRY_PARTIAL; 중복 진입 금지 |
| BASE_STRANGLE_ACTIVE | 양쪽 actual lots 대사 완료 | 기본 방어 유지; short policy 미해결이면 신규 매도 금지 | CALL/PUT lot 분리 | 불일치 시 RECONCILIATION_REQUIRED |
| SHORT_CANDIDATE | Each short_step_pt crossing from the current reference point, with exposure and risk gates valid | Up: SELL PUT at previous_reference_point - short_offset_pt; down: SELL CALL at previous_reference_point + short_offset_pt; then refresh reference to the newly reached ATM. Validate listed contract identity, premium, liquidity, limits and order provenance | Record prior/new reference, crossing direction, strike formula, config version, candidate and leg state | Missing/stale data, invalid contract, PROVISIONAL config or risk failure blocks order; code path is not implemented by this document edit |
| SHORT_WORKING/PARTIAL | submitted/accepted/partial/reject/cancel pending | actual+pending worst-case exposure cap 적용 | cumulative fills/leaves/cancel ack/late fills 기록 | reconcile 전 재진입 금지 |
| SHORT_ACTIVE | authoritative short lots 확인 | nearest short strike 거리 감시; 보합이면 no-op/hold | sale-time premium 및 contract identity 보존 | stale/missing data면 신규 short/hedge 차단 |
| HEDGE_TRIGGERED | distance ≤ approved hedge_trigger_distance_pt | linked short actual remaining qty × 1.0 option BUY plan | filled/pending hedge를 차감해 중복 방지 | null/PROVISIONAL/quote/identity/cost fail이면 BLOCKED |
| HEDGE_LIMIT_WORKING | 유효 후보에 LIMIT 예약주문 | 후보 1개만 활성; 30분 대기 | leg별 order/fill/remaining tracking | 30분 후 cancel request; 다음 후보 금지 |
| HEDGE_CANCEL_RACE | 취소 중 late fill 도착 | 다음 후보 금지; fills와 positions 재대사 | cumulative fill/remaining qty 재계산 | cancel terminal + leaves=0 + reconcile 후 후보 하강 |
| HEDGE_CANDIDATE_DOWN | 앞 후보 cancel terminal, leaves=0, fills reconciled | 다음 후보에 LIMIT/30분 절차 반복 | 후보별 order/leg ID와 시도 순번 | 후보 소진/타이머 불명확이면 BLOCKED; 임의 market order 금지 |
| HEDGE_ACTIVE | hedge fills/open lots 확인 | ATM이 linked short strike에서 5.0pt 이상 이탈 시 hedge 잔량 청산 | short와 hedge를 상계해 flat 처리하지 않음 | partial/reject 시 close pending 유지 |
| DTE4_TERMINAL | authoritative expiry + approved DTE semantics에서 DTE≤4 | 모든 short/hedge/base CALL+PUT 잔량 grouped terminal close; 신규 진입 억제 | grouped plan은 원자체결 아님; 각 레그 fills authoritative | open lot이면 PARTIAL_FLATTEN/RECONCILIATION_REQUIRED |
| TERMINAL_CANCEL_RACE | terminal close cancel/reprice 중 late fill | 기존 group/leg reconcile; 이미 닫힌 qty 중복주문 금지 | late fill/leaves 반영 | 모든 주문 terminal/open lots=0 전 새 group 금지 |
| FLAT_CONFIRMED | orders terminal, fills/positions reconciled, S1 open lots=0 | 월물 lifecycle 완료, ledger provenance 보존 | fills/fees/realized P&L 기록 | 이때만 lifecycle reset |
| WAIT_NEXT_MONTH | DTE4 전량청산 및 authoritative flat 확인 후 다음 월물 시작 전 약 3~4일 | S1 신규 거래 없음; 다음 월물 시작 조건까지 대기 | 이전 월물 group/ledger/config provenance 보존 | 미확정 달력/DTE/월물 기준이면 BLOCKED |

취소 레이스 필수 규칙: 취소 요청은 취소 완료가 아니다. 취소 대기 중 fill이 오면 반영하고 다음 후보 주문을 금지한다. cancel terminal, leaves=0, late ExecutionReport 반영, position-lot 대사가 모두 완료된 뒤에만 후보 하강한다. 누락/순서 역전/identity 불일치이면 RECONCILIATION_REQUIRED다.

## 6. Execution/position 계약
각 주문/fill은 run_id, strategy_id, config_version/hash, group_id, leg_id, client_order_id, execution_id, exact expiry YYYYMMDD, option type, strike, instrument_id, multiplier, role, side, requested/cumulative/remaining qty, average fill, fees, source timestamps, cancel/replace lineage를 보존한다.
- grouped plan은 논리적 묶음이지 원자 체결이 아니다.
- 승인/라우팅은 체결이 아니다. 그룹 preflight 실패 시 신규 그룹 전송 금지.
- open lots/executions 대사 전 active/flat 판단 금지.
- No.1132/1134의 grouped terminal execution, per-leg fill, flat 전 reset 금지 원칙을 따른다.

## 7. 헤지 후보/유동성 규칙
1. trigger를 만든 short lot/group 및 actual remaining qty를 특정한다.
2. sale-time premium과 exact contract provenance를 조회한다.
3. authoritative option master/chain/quotes로 후보를 구성한다. premium/strike/expiry/multiplier 추정 금지.
4. 후보별 현재 옵션 프리미엄 가격과 연결된 매도 당시 받은 프리미엄의 절대 차이를 비교하고, 가장 가까운 가격을 우선한다. 행사가 거리로 대체하지 않는다.
5. 프리미엄 차이가 동률이면 유동성이 좋은 후보를 우선한다. 유동성 metric, quote age, spread/depth 기준은 U21이며 검증 전 임의 임계값을 만들지 않는다.
6. quote gap이면 LIMIT reservation → 30분 → cancel request → cancel terminal/late-fill/position reconciliation → 다음 후보.
7. hedge qty는 linked short remaining qty × 1.0. filled/pending hedge 반영으로 duplicate hedge 금지.
8. cost/premium/margin/stress gate 실패 시 주문 생성 없이 BLOCKED. 미헤지 short exposure는 read model에 노출한다.
9. REAL_VTS tuning candidate set에는 hedge_trigger_distance_pt 2.5pt와 5.0pt를 포함한다. 두 후보는 비교 대상일 뿐이며 최종값은 분리된 검증 기간 결과와 별도 사용자 승인 전까지 미확정이다.

## 8. 계좌 위험/자본/비용
계좌 총자본, S1 최대 프리미엄, S1 최대손실, 계좌 최대손실, 증거금 사용률, order cost, fees/slippage, bid-ask spread/liquidity, S1~S9 correlated tail risk는 설정 가능 항목이며 수치는 미확정이다. capital_per_contract=25,000,000은 임시 입력이며 승인값이 아니다. 필수 risk limit가 null/PROVISIONAL이거나 authoritative input이 없으면 신규 거래를 fail-closed한다. 열린 포지션은 없다고 추정하지 않는다.

## 9. 기존 U/G/I 재분류
### Existing U register
| U | 분류 | 근거/잔여 |
|---|---|---|
| U01 S1 target payoff/3-leg structure | 확정으로 해결 | §1.2–7 및 사용자 확정 2026-10-12 |
| U10 capital/premium/max-loss numbers | 설정값으로 이관, 수치 PROVISIONAL | §1.13 |
| U11 partial/cancel/restart persistence | 사용자 확인/검증 미완료 | runtime evidence 없음 |
| U12 account aggregate risk/correlation/netting | editable limits; aggregation method unresolved | §1.13 |
| U13 authoritative P&L/fees/multiplier | 사용자 확인/검증 미완료 | ledger evidence 필요 |
| U14 expiry/session/rollover | DTE4 전량청산 및 3~4일 월물 공백은 확정; 달력일/거래일 DTE 및 authoritative cutoff는 U22 | §1.10, U22 |
| U15 Shrimp Resume Context | UNAVAILABLE; 이 작업에서 확인/갱신하지 않음 | workflow |

### 신규 미결 항목 및 사용자 답변 처리
| U | 상태 | 항목/근거 |
|---|---|---|
| U16 | 확정으로 해결 | 상승 시 PUT 매도, 하락 시 CALL 매도; 혼선 용어 폐기. 사용자 확정 2026-10-12 §1.3 |
| U17 | 확정으로 해결 | DTE4 flat 후 다음 월물 시작 전 약 3~4일 S1 휴지. 사용자 확정 2026-10-12 |
| U18 | 확정으로 해결 | new_short_stop_dte=7 삭제 및 폐기 기록; DTE4 전량청산만 사용. 사용자 확정 2026-10-12 |
| U19 | 설정값으로 이관 | hedge trigger는 REAL_VTS로 튜닝; 2.5pt와 5.0pt 후보 포함, 확정값 없음 |
| U20 | 확정으로 해결 | 옵션 프리미엄 가격 자체를 매도 당시 받은 프리미엄과 비교. 사용자 확정 2026-10-12 §1.6 |
| U21 | 사용자 확인 필요 | 유동성 지표, 스프레드/깊이/quote-age 기준 |
| U22 | 사용자 확인 필요 | calendar/trading DTE, expiry/last-trading-day source/cutoff |
| U23 | 사용자 확인 필요 | 월물 시작 ATM 기준 및 opening gap |
| U24 | 사용자 확인 필요 | short-entry limit/reprice interval/max attempts |
| U25 | 사용자 확인 필요 | DTE4 close reject/illiquidity recovery; market fallback 추론 금지 |
| U26 | 설정값으로 이관 | REAL_VTS tuning/validation dataset IDs, 기간 분리 및 acceptance criteria를 명시 설정하되 값/검증은 미완료 |
| U27 | 사용자 확인 필요 | capital_per_contract=25000000 단위/경제적 의미 |
| U28 | RESOLVED by explicit user correction (2026-10-13) | Per-step reference refresh and strike formula are defined; code implementation remains absent and unauthorized |
| U29 | 사용자 확인 필요 | 별도 take-profit/trailing 정책 유무 |

### S1 G01–G12 gate 판정
| Gate | S1 v0.3 | Blocker |
|---|---|---|
| G01 payoff/role | PARTIAL | short direction resolved; payoff/stress model validation remains |
| G02 entry/scale/exit | BLOCKED | short direction resolved; trigger tuning is configurable; DTE7 gate retired |
| G03 contract/expiry/qty/multiplier | PARTIAL | DTE semantics/master/rounding evidence |
| G04 partial/reject/cancel race | SPECIFIED / UNVERIFIED | no scenario execution |
| G05 hedge/rebalance | PARTIAL | premium-price matching resolved; trigger tuning and cost gates remain |
| G06 exits | PARTIAL | DTE4/±5 specified; other exits undefined |
| G07 session/rollover | BLOCKED | monthly gap resolved; DTE definition/cutoff remain U22 |
| G08 capital/risk | BLOCKED | provisional/null limits and unvalidated cost model |
| G09 recovery | SPECIFIED / UNVERIFIED | no runtime recovery evidence |
| G10 traceability | BLOCKED | exact tests/logs not run/mapped |
| G11 assumptions/dependencies | DRAFT | U21–U29 and source/acceptance dependencies remain; U16–U20 resolved or settings |
| G12 validation vs approval | PASS (process only) | remains draft/unverified/unapproved |

### I01–I16 S1 interaction delta
| I | S1 update | Status |
|---|---|---|
| I01 capital/premium/margin | editable config; null/PROVISIONAL blocks new orders | BLOCKED pending values/runtime enforcement |
| I02 shared Futures identity | S1 Futures hedge removed; S3/S4/S5 role issue separate | S1 resolved; global issue BLOCKED |
| I03 option lots/Greeks | S1 hedge uses linked short lots 1:1, not unowned account delta | BLOCKED pending ownership evidence |
| I04 insurance overlap | S1/S2/S6/S7/S8/S9의 계약·만기별 수량, 프리미엄, 증거금 및 stress 노출을 합산; 중복 보호 credit 금지, 전략 의도 변경 없음 | BLOCKED |
| I05 partial/cancel race | cancel-confirm and late-fill rules added | specified, unverified |
| I06 P&L/fees | actual fill/qty/multiplier/fees/slippage; no underlying proxy as option P&L | BLOCKED pending ledger proof |
| I07 expiry/session | DTE4 full-close and monthly pause specified; DTE semantics/cutoff remain U22 | BLOCKED |
| I08 trigger priority | DTE4 suppresses new S1 short/hedge; other priorities open | PARTIAL |
| I09 stale/unavailable | fail-closed for null/provisional/stale/mismatch | specified, enforcement unverified |
| I10 restart/idempotency | reconcile before resume; no reset until flat | specified, persistence unverified |
| I11 S5 role | S1 does not convert Futures quantities; S5 No.1151 unchanged | S5 unresolved |
| I12 S3 spread identity | no S1 change | BLOCKED |
| I13 S4 hedge ownership | S1 hedge limited to S1-owned linked short lots; S4 issue remains | BLOCKED |
| I14 S8 add-on | no S1 change | BLOCKED |
| I15 cycle/re-entry | S1 next cycle requires prior group flat; other cycles unchanged | account interaction BLOCKED |
| I16 editable config | schema/version/hash defined; null/provisional fails closed | runtime enforcement unverified |

## 10. Historical Decision Log retirement proposals — not executed
No Decision Log item is deleted or changed. If an existing S1 item mandates Mini Futures hedge, short cap 5, 1.5pt release, new_short_stop_dte=7, DTE7 hedge close, or high-volatility-day deferral of base strangle close, propose status “폐기됨” with reason/date 2026-10-12 and the conflicting user clause. Proposal only. Do not reuse retired No.1168 BUY 2. No.1151 role classification and cost/margin gates remain in force; no same-quantity Futures-to-option substitution is implied.

## 11. Test mapping and final state
Scenario plan: 04_strategy_1_to_9_scenario_test_plan_v0.2.md, TP-S1-U01..U11; all NOT_RUN. Document structure is draft; payoff completeness, REAL_VTS tuning, runtime behavior, tests and user approval remain incomplete. No implementation permission is granted.

## 9-A. Strict three-way classification of every v0.2 U, S1-relevant G and I
The following classification uses only the three categories requested in the user instruction. “Resolved” means the intent/policy question is settled by the user's direct instruction; it does not mean code or runtime verification passed.

### All existing U01–U15
| Item | Required classification | Reason / scope |
|---|---|---|
| U01 | 확정으로 해결 | S1 core structure now specified by user §1.2–7; residual semantics are new U16/U20 |
| U02 | 사용자 확인 필요 | S2-only payoff/stop basis; outside S1 intent |
| U03 | 사용자 확인 필요 | S3 tradable spread identity; outside S1 intent |
| U04 | 사용자 확인 필요 | S4 eligible option lots/basecamp role; outside S1 intent |
| U05 | 사용자 확인 필요 | S5 Futures PRIMARY_ALPHA/SPREAD vs HEDGE, quantities and exit order; No.1151 remains |
| U06 | 사용자 확인 필요 | S6 pair MTM/partial pair/cutoff; outside S1 intent |
| U07 | 사용자 확인 필요 | S7 IV skew trigger/expiry normalization; outside S1 intent |
| U08 | 사용자 확인 필요 | S8 add-on/rounding/DTE policy; outside S1 intent |
| U09 | 사용자 확인 필요 | S9 latest entry/open/stabilization close; outside S1 intent |
| U10 | 설정값으로 이관 | capital/premium/max-loss values editable, but provisional/null until verified and approved |
| U11 | 사용자 확인 필요 | common partial/cancel/restart persistence has no current runtime evidence |
| U12 | 설정값으로 이관 | account aggregate limits editable; correlation/netting model remains an explicit blocker |
| U13 | 사용자 확인 필요 | authoritative P&L/fee/multiplier source and ledger evidence |
| U14 | 사용자 확인 필요 | DTE4 전량청산과 3~4일 월물 공백은 확정; calendar/trading DTE 및 authoritative cutoff는 U22 |
| U15 | 사용자 확인 필요 | Shrimp Resume Context currently UNAVAILABLE; this task did not update it |

### All completeness gates G01–G12
| Gate | Required classification | Reason |
|---|---|---|
| G01 payoff/role | 사용자 확인 필요 | short direction/timing resolved; payoff/stress model still requires validation |
| G02 entry/scale/exit | 사용자 확인 필요 | short direction resolved; trigger distance is tunable, DTE7 gate retired |
| G03 contract/expiry/qty/multiplier | 사용자 확인 필요 | DTE semantics/master/rounding evidence remains open |
| G04 partial/reject/cancel race | 사용자 확인 필요 | transition is specified, but tests/runtime evidence are NOT_RUN |
| G05 hedge/rebalance | 사용자 확인 필요 | premium-price matching resolved; trigger tuning and cost gates remain |
| G06 stop/target/trailing/time exit | 사용자 확인 필요 | DTE4/±5 specified; no other exit policy was authorized |
| G07 session/expiry/rollover | 사용자 확인 필요 | monthly gap resolved; DTE definition/cutoff remain U22 |
| G08 capital/premium/max-loss/account risk | 설정값으로 이관 | editable settings exist in draft; all critical numbers are null/provisional |
| G09 failure/restart/recovery | 사용자 확인 필요 | policy draft exists, persistence/reconciliation evidence absent |
| G10 requirements-spec-code-test | 사용자 확인 필요 | exact test IDs/logs not run or mapped |
| G11 assumptions/external dependencies | 사용자 확인 필요 | U21–U29 and source/acceptance dependencies remain; U16–U20 resolved or settings |
| G12 validation vs approval | 확정으로 해결 | process boundary is explicit: draft/verification never implies user approval; this document remains unapproved |

### All interaction register items I01–I16, S1 classification
| I | Required classification | S1 reason; other-strategy issue remains where noted |
|---|---|---|
| I01 capital/premium/margin | 설정값으로 이관 | account/strategy caps are configurable; runtime enforcement and values not verified |
| I02 shared Futures identity | 확정으로 해결 | S1 has no Futures hedge in target intent; S3/S4/S5 global role issues remain |
| I03 option lots/Greeks ownership | 사용자 확인 필요 | S1 1:1 linked-short rule set, but authoritative lot ownership/duplicate aggregation evidence absent |
| I04 insurance overlap/tail risk | 설정값으로 이관 | S1/S2/S6/S7/S8/S9의 수량·프리미엄·증거금·stress를 계좌 기준으로 합산; 모델은 검증 미완료 |
| I05 multi-leg partial/cancel race | 사용자 확인 필요 | state policy written; runtime test evidence absent |
| I06 P&L/fees attribution | 사용자 확인 필요 | authoritative ledger/multiplier/fee evidence absent |
| I07 expiry/session/rollover | 사용자 확인 필요 | DTE4 and monthly pause specified; calendar semantics/cutoff remain U22 |
| I08 risk/profit/hedge trigger priority | 사용자 확인 필요 | DTE4 suppresses new entry; other simultaneous priorities remain open |
| I09 data freshness/unavailable | 확정으로 해결 | user mandates fail-closed; actual enforcement still unverified |
| I10 restart/idempotency | 확정으로 해결 | user mandates reconcile before resume and no reset until flat; durable implementation still unverified |
| I11 Strategy 5 Futures role | 확정으로 해결 | S1 will not convert Futures quantities; S5 itself still requires No.1151 classification |
| I12 Strategy 3 spread identity | 사용자 확인 필요 | S3 issue is outside S1 and remains BLOCKED |
| I13 Strategy 4 hedge ownership | 확정으로 해결 | S1 uses only S1-owned linked short lots; S4 ownership issue remains separate |
| I14 Strategy 8 add-on intent | 확정으로 해결 | S1 does not modify S8 intent; S8 remains independently blocked |
| I15 daily/weekly/overnight re-entry | 사용자 확인 필요 | S1 monthly flat gate defined, account-wide cross-strategy cycle interaction remains unverified; S1 monthly pause is specified |
| I16 editable config consistency | 설정값으로 이관 | S1 version/hash schema specified; config values and runtime enforcement unverified |

These classifications do not change the status of any Decision Log entry. Any historical conflict is only a proposed “폐기됨” annotation; no Decision Log item was changed or deleted.

## Product boundary — No.1070
S1 base CALL/PUT, short options and hedge options use standard KOSPI200 options only. Mini Options are not used. This restriction is independent from replacing Mini Futures hedge with option hedge. All contract identity, exact YYYYMMDD expiry, strike and multiplier must be resolved from authoritative master data; otherwise new orders are blocked.

## 12. Follow-up user-confirmed amendment — 2026-10-12
이 절은 앞선 초안 문구와 충돌할 경우 우선한다. 사용자 확정 의도는 문서 승인이나 구현 검증 완료를 뜻하지 않는다.

- Short accumulation: compare each index move with the current reference point. At +short_step_pt, SELL PUT at previous_reference_point - short_offset_pt; at -short_step_pt, SELL CALL at previous_reference_point + short_offset_pt. Only after deriving the strike, update the reference point to the new ATM. Example: 100→102.5 gives PUT 92.5; 102.5→105 gives PUT 95; 105→107.5 gives PUT 97.5. Downward moves are symmetric for CALL.
- 사용자가 의도하지 않은 매도 용어는 목표 규칙/상태기계에서 사용하지 않는다.
- 월물 만기 4일 전 남은 short/hedge/base strangle 전량 청산 후 다음 월물 시작 전 약 3~4일 거래를 쉰다.
- new_short_stop_dte는 설정 스키마에서 삭제되었고 new_short_stop_dte=7은 **폐기됨(사용자 확정, 2026-10-12)**. 별도 DTE7 신규매도 중단 규칙은 없다.
- hedge_trigger_distance_pt 비교 후보: 2.5pt, 5.0pt 및 필요한 추가 후보. 이들은 REAL_VTS 튜닝 후보일 뿐 최종값이 아니다. 튜닝/검증 기간을 분리한다.
- 헤지 후보는 행사가가 아니라 옵션 프리미엄을 매도 당시 받은 프리미엄과 비교한다. 동률이면 유동성을 비교하고, 호가 공백 시 LIMIT reservation 30분 후 취소 terminal/late fill/position reconciliation을 모두 확인한 뒤 다음 후보로 이동한다.
- U28 is resolved at the specification level by the user correction dated 2026-10-13. The remaining gap is implementation/verification: current code does not implement the target step-based short accumulation, so no code/runtime PASS is implied.

### U16–U20 final disposition
| U | Required classification | Basis |
|---|---|---|
| U16 | 확정으로 해결 | 사용자 §1.3: 상승→PUT, 하락→CALL; 혼선 용어 폐기 |
| U17 | 확정으로 해결 | 사용자 §4-2: DTE4 이후 3~4일 휴지 |
| U18 | 확정으로 해결 | 사용자 §4-3: DTE7 setting 삭제, DTE4 전량청산만 사용 |
| U19 | 설정값으로 이관 | 사용자 §4-4: REAL_VTS 튜닝, 2.5/5.0pt 후보 포함, 최종값은 미확정 |
| U20 | 확정으로 해결 | 사용자 §4-5: 옵션 프리미엄 가격 자체 비교 |

### U21–U29 strict three-way classification
| U | Required classification | Basis / unresolved boundary |
|---|---|---|
| U21 | 사용자 확인 필요 | 유동성 지표 및 quote-quality threshold 미정 |
| U22 | 사용자 확인 필요 | DTE 정의와 authoritative expiry/cutoff 미정 |
| U23 | 사용자 확인 필요 | 월물 시작 ATM 기준/갭 처리 미정 |
| U24 | 사용자 확인 필요 | short order pricing/reprice/max attempts 미정 |
| U25 | 사용자 확인 필요 | DTE4 close failure recovery 미정; market fallback 금지 |
| U26 | 설정값으로 이관 | tuning/validation dataset ID·기간·acceptance 설정 항목; 실제 값/검증은 미완료 |
| U27 | 사용자 확인 필요 | capital_per_contract 단위/경제적 의미 미정 |
| U28 | RESOLVED by explicit user correction (2026-10-13) | Per-step reference refresh and strike formula are defined; code implementation remains absent and unauthorized |
| U29 | 사용자 확인 필요 | 별도 take-profit/trailing 정책은 사용자 의도에 없어 추론 금지 |

현재 남은 항목은 미결 레지스터에만 기록하며 이 보고에서 추가 사용자 질문을 요구하지 않는다. 상태는 draft/unverified/unapproved 유지.

- No.1046 evidence boundary: current-code observations, authoritative source evidence and actual verification results are kept distinct. This document task performed static document/code inspection only; it claims no test/runtime PASS.

- No.1131 (2026-10-12 scope): this document records user-confirmed behavior as target intent only; no silent strategy-logic change is applied to code, and any unresolved anchor/order details remain U24.

## User-confirmed S1 strike/reference correction — 2026-10-13
- The short strike is NOT calculated from the newly reached/current ATM. It is calculated from the immediately preceding reference point.
- Upward crossing by short_step_pt=2.5: SELL PUT at previous_reference_point - short_offset_pt=7.5. Downward crossing by 2.5: SELL CALL at previous_reference_point + 7.5.
- After each crossing is processed, set the reference point to the newly reached ATM. Thus 100→102.5: PUT 92.5; 102.5→105: PUT 95; 105→107.5: PUT 97.5. Downward examples are symmetric with CALL.
- U28 is resolved as a specification ambiguity. The current code gap remains; this document-only correction does not implement code, authorize tests, or authorize trading. Status remains DRAFT / UNVERIFIED / UNAPPROVED.
