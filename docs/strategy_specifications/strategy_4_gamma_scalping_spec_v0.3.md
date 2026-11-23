# Strategy 4 Gamma Scalping 명세 v0.3 — 시장 표준 기준·보류형 초안

- 작성일: 2026-10-13
- 상태: **DRAFT / UNVERIFIED / UNAPPROVED / DISABLED**
- 변경 성격: 문서 전용. v0.2 보존. 코드 수정·테스트 실행·commit/push·KIS Live 주문 없음.
- 권한: 사용자 위임에 따른 시장 표준 기준 제안이며, Decision Log에는 초안 제안만 가능하다. 본 문서는 사용자 승인 명세가 아니다.

## 1. 전략 목적 및 시장 표준 제안

S4 Gamma Scalping은 실제 옵션 매수 포지션으로 롱 감마를 보유하고, 그 옵션 포지션의 델타만 선물로 반복 중립화하는 전략이다. 대표 구성은 ATM 롱 스트래들(call 1 + put 1) 또는 근접 롱 스트랭글이다. 델타 헤지 거래에서 기초자산을 유리한 가격에 사고/팔아 실현 변동성을 축적하며, 경제성은 실현 변동성 대 내재 변동성, 옵션의 세타 감소, 수수료·슬리피지·헤지 오차에 좌우된다. 이 설명은 시장 표준 논리이지 수익 보장이 아니다.

### 1.1 확정된 사용자 운영 제한

- S4는 정규/미니 선물을 사용하는 본래 전략이며, 옵션으로 선물 역할을 단순 치환하지 않는다.
- 현재 자본/증거금 조건으로 운용을 보류한다. `enabled=false`, `capital_gate_min=null`이면 진입 차단. 등록·자본 예약·VTS 자동 운용에서도 비활성 상태를 유지한다.
- 활성화는 충분한 자본 검증과 사용자의 별도 명시 승인 후에만 가능하다.
- 장중 전량 청산, 오버나이트 금지. `force_close_time: "15:10"`은 설정 후보이며 실제 시장 세션·청산 capability 검증이 필요하다.
- 설정 수치는 PROVISIONAL. REAL_VTS의 튜닝 기간과 별도 검증 기간을 나누고 매 run에 config version/hash를 기록한다. 필수 설정이 null이거나 stale/unavailable이면 진입·헤지 추가를 차단한다.
- 옵션 매수 체결이 확인된 후에만 S4의 선물 델타 헤지를 허용한다. NON_EXECUTION 이벤트는 주문 또는 보유 옵션의 증거가 아니다.

### 1.2 표준 동작 후보

1. **옵션 진입:** 변동성·가격·체인·IV·예상 실현변동성·거래비용을 검증하고, 예상 실현변동성이 내재변동성을 초과할 합리적 근거가 있을 때만 롱 감마 후보를 허용한다. IV source가 없으면 진입 차단. 기존 active/base ratio 0.85/1.30은 검증 전 후보값일 뿐 IV edge를 증명하지 않는다.
2. **옵션 구성:** 시작 후보는 ATM call 1 + ATM put 1의 롱 스트래들. 근접 롱 스트랭글은 별도 설정/검증 후보이며, 현재 확정되지 않았다. 계약 identity/expiry/strike/multiplier/quote는 authoritative master로 결정한다.
3. **델타 소유권:** S4가 소유한 실제 체결 옵션 lots의 델타만 합산한다. 계좌 전체 delta나 S1 등 타 전략 delta를 섞지 않는다. 계좌 전체 위험은 별도 account risk layer에서 합산한다.
4. **헤지 계산:** option delta의 단위(계약별/합계), 옵션·선물 승수, point value, 부호 규약 및 정수 환산·반올림을 명시한다. 승수/단위 중 하나라도 미확정이면 수량을 추정하지 않고 BLOCKED. 선물 deadband는 최소 한 계약의 환산 델타 단위 이상이어야 한다. 기존 analytics key `price.tick_deadband`를 delta 단위에 직접 비교하는 것은 의미상 불일치 가능성이 있다.
5. **목표와 실제 포지션 분리:** target hedge qty, pending qty, 실제 filled qty를 분리한다. 목표량은 주문 전에 계산할 수 있으나 실제 hedge position/active quantity는 authoritative fills와 positions로만 갱신한다.
6. **헤지 상한:** 하드코딩 100 대신 `max_hedge_qty`와 증거금/자본/계좌 최대손실 게이트로 제한한다. 상한이나 margin quote가 null/stale이면 신규 노출을 차단한다.
7. **청산:** 위험/세션/만기 종료가 profit trailing보다 우선한다. gamma scalping 포지션을 종료할 때 S4가 소유한 옵션과 연결된 선물 헤지를 함께 닫는다. 단, 부분체결·거부·불명확한 상태에서 일괄 flat을 가정하지 않고 레그별로 추적·대사한다. 청산 요청만으로 state reset 금지.
8. **손익:** 옵션 MTM + 선물 헤지 realized/unrealized P&L − premium/fees/slippage/financing 및 검증된 세타 비용을 같은 기준시각과 실제 fills로 계산한다. 계좌 전체 P&L만으로 S4 trailing을 판단하지 않는다. gamma profit을 데이터 없이 추정하지 않는다.
9. **세타·비용:** 누적 세타 비용과 거래비용이 허용된 전략 손실 한도 또는 기대 감마 이익을 초과할 때 종료하는 규칙을 후보로 둔다. 임계값은 설정/REAL_VTS 검증 전 null.
10. **만기:** `no_new_entry_dte`를 설정으로 두며 null이면 신규 진입 차단. 만기 당일/임박 계약의 감마·갭 위험을 별도 검증한다.

## 2. 설정 스키마 초안

```yaml
strategy4:
  status: PROVISIONAL
  enabled: false
  capital_gate_min: null
  basecamp_low_vol_ratio: 0.85
  basecamp_high_vol_ratio: 1.30
  option_structure: long_straddle
  option_legs: [call, put]
  option_qty_each: 1
  hedge_instrument: mini_futures
  delta_scope: own_options_only
  delta_deadband: null
  max_hedge_qty: null
  rebalance_min_interval_sec: null
  trailing_activate_pnl: null
  trailing_retention: null
  theta_cost_stop: null
  no_new_entry_dte: null
  force_close_time: "15:10"
```

`option_structure`/수량은 시작 후보이지 승인값이 아니다. 승수, tick, quote freshness, IV, capital/margin, max-loss, fee/slippage, hedge quantity rounding, config version/hash는 authoritative source 또는 명시적 설정에서 제공되어야 한다. null/invalid/stale이면 fail-closed. `enabled=true`는 이 문서만으로 허용되지 않는다.

## 3. 공통 상태 및 전이

| 현재 상태 | 입력/조건 | 다음 상태 | 허용 동작 / 실패 처리 |
|---|---|---|---|
| DISABLED | enabled=false 또는 capital gate 미충족/null | DISABLED | 신규 옵션·선물 주문 금지. 이미 존재하는 포지션이 있으면 비활성만으로 방치하지 않고 별도 reconciliation/exit 관리 필요 |
| READY | 활성화 승인, capital gate PASS, config/source fresh | ENTRY_PREFLIGHT | option master, IV/quotes, cost, max-loss, expiry, session, account margin 검증 |
| ENTRY_PREFLIGHT | 그룹 risk preflight PASS | OPTION_ENTRY_PENDING | call/put 레그별 주문 및 order IDs 기록; atomic fill 가정 금지 |
| OPTION_ENTRY_PENDING | 옵션 fills 확정, 실제 lot와 Greeks 연결 | LONG_GAMMA_ACTIVE | 체결된 수량만 옵션 보유로 기록; 부분체결이면 PARTIAL/RECONCILIATION_REQUIRED |
| OPTION_ENTRY_PENDING | reject/timeout/cancel race/unknown | BLOCKED_RECONCILIATION | 신규 헤지 금지; 취소 완료와 late fills를 포함해 실제 positions 대사 |
| LONG_GAMMA_ACTIVE | fresh own-option Greeks, delta beyond deadband | HEDGE_PREFLIGHT | target qty와 actual/pending qty 분리; margin/cap check |
| HEDGE_PREFLIGHT | preflight PASS | HEDGE_ORDER_PENDING | grouped plan 및 leg provenance 발행, 상태는 체결으로만 갱신 |
| HEDGE_ORDER_PENDING | partial/reject/cancel race | PARTIAL / BLOCKED_RECONCILIATION | fill마다 exposure 재계산; blind retry 금지 |
| HEDGE_ORDER_PENDING | fills reconciled | LONG_GAMMA_ACTIVE | actual hedge quantity 및 residual delta 갱신 |
| LONG_GAMMA_ACTIVE | risk/expiry/force-close/trailing/theta stop | TERMINAL_EXIT_PENDING | 옵션과 연결 헤지의 남은 수량을 grouped terminal plan으로 구성; risk/expiry 우선 |
| TERMINAL_EXIT_PENDING | 일부 미체결 또는 late fill | PARTIAL / BLOCKED_RECONCILIATION | 주문/체결/포지션 대사, 재시작 후에도 유지 |
| TERMINAL_EXIT_PENDING | 모든 required lots authoritative flat | FLAT_CONFIRMED | 그때만 lifecycle reset, 다음 cycle은 calendar/config gate 확인 후 |
| ANY ACTIVE | stale/mismatched Greeks, identity, account/margin or source | BLOCKED_RECONCILIATION | 신규 노출 금지; 기존 포지션의 안전한 관리·수동介入 필요 여부 명시 |

No.1132 grouped execution 원칙에 따라 한 snapshot은 atomic execution을 의미하지 않는다. terminal close는 모든 open leg를 grouped plan에 담되 실제 완료는 각 ExecutionReport와 position read model로 확인한다.

## 4. F01–F29 재분류표

분류: **표준으로 해결**은 일반 원칙만 확정된 항목, **설정 이관**은 수치/정책 후보, **사용자 확인 필요**는 활성화 전 사용자 승인 또는 전략 경계 선택이 필요한 항목이다. 각 분류는 구현/검증 완료를 뜻하지 않는다.

| ID | 영역 | 시장 표준·현재 코드 근거 | 분류 및 처리 |
|---|---|---|---|
| F01 | 목적·경제성 | 롱 감마 옵션 + 선물 delta hedge; 현 코드는 option inventory 없이 futures signal 가능 | 표준으로 해결: 실제 옵션 체결 후에만 hedge |
| F02 | 상품/identity | 현 코드는 Mini Futures proposal; basecamp는 NON_EXECUTION | 설정 이관: option/futures master·승수 확인 전 차단 |
| F03 | 세션/활성화 | basecamp cutoff만 있고 hedge 경로는 basecamp 상태에 종속되지 않음 | 설정 이관: disabled, entry/hedge window, 15:10 close, no overnight |
| F04 | 동기화/시점 | materializer가 tick/runtime/Greeks timestamp 동일성 검사 | 표준으로 해결: source-time/freshness/identity/position provenance 모두 필요; 실제 완전성 미검증 |
| F05 | 진입/basecamp | ratio 0.85/1.30은 state-only event이며 option 주문 아님 | 설정 이관: IV edge 검증 및 option entry plan 필요 |
| F06 | 추가 진입/hedge eligibility | basecamp_active와 무관하게 hedge 가능 | 표준으로 해결: owned option fill 없으면 hedge 금지 |
| F07 | 주문 lifecycle | `active_hedge_qty`를 체결 전에 target으로 갱신 | 표준으로 해결: actual filled state는 authoritative fills에서만 갱신 |
| F08 | 계약 identity | aggregate delta input 및 Futures resolver 존재; lot-level link 미증명 | 설정 이관: exact option lots/Futures identity/multiplier/expiry |
| F09 | Greeks 단위·부호 | delta Decimal을 `delta_to_mini_futures_qty(abs(delta))`에 전달 | 설정 이관: unit/sign/multiplier/rounding 검증 전 BLOCKED |
| F10 | 변동성/IV | active/base ratio만 사용, IV edge 없음 | 설정 이관: source/window/unit/IV and realized-vol estimator |
| F11 | deadband | `price.tick_deadband`가 delta와 비교됨 | 설정 이관: delta-space deadband와 min-one-contract consistency 검증 |
| F12 | 수량·자본·비용 | `min(...,100)`, equity threshold 기본 0 | 설정 이관: capital/margin/qty/max-loss/fee/slippage; null blocks |
| F13 | 가격/재주문 | Futures proposal `requested_price=None` | 설정 이관: order type/collar/reprice/timeout/liquidity limits |
| F14 | risk preflight | resolver/RiskGate 존재; S4 group/account risk proof 미확인 | 표준으로 해결: every rebalance/entry/exit requires group + account preflight; coverage BLOCKED |
| F15 | partial/reject | target set pre-fill | 표준으로 해결: independent leg states, late fills and reconciliation |
| F16 | hedge quantity | adjustment based on stored target, not verified actual position | 표준으로 해결: target minus actual filled/open quantity, pending orders accounted |
| F17 | holdings | state lacks per-lot Futures identity | 설정 이관: durable lot/group provenance and target/actual/pending separation |
| F18 | risk exit | equity threshold unwinds hedge only; no explicit max loss/delta error | 설정 이관: equity/max loss/stress loss/delta residual limits |
| F19 | trailing | high P&L > 30,000 and 85/88/90% thresholds; closes Futures only | 설정 이관: option+futures strategy P&L, fees, activation and retention values |
| F20 | expiry/overnight | no option expiry/rollover path | 설정 이관: DTE block, expiry exit, no overnight; null blocks new entry |
| F21 | close qty/side | derives close from `active_hedge_qty` target | 표준으로 해결: close from actual open lots and confirm flat |
| F22 | P&L/theta | portfolio current P&L/premium; gamma/theta input not used in shown decision | 설정 이관: strategy-owned option/futures MTM, theta/cost ledger |
| F23 | trigger priority | basecamp then hedge then trailing; conflicts possible | 표준으로 해결: risk/expiry > reconcile/terminal exit > hedge rebalance > profit trailing > entry/basecamp |
| F24 | provenance | stable Futures group suffix; basecamp not linked to option lots | 설정 이관: option/hedge group, evaluation/order/fill/P&L links |
| F25 | restart/idempotency | reset clears memory state; durable restore not shown | 표준으로 해결: reconcile orders/fills/positions/config before resuming |
| F26 | cross-strategy risk | portfolio delta/P&L/equity source with ownership unclear | 사용자 확인 필요: S4-owned delta only is recommended; account risk separately aggregates all strategies |
| F27 | unavailable data | analytics feature validation and timestamp checks exist | 표준으로 해결: stale/missing/mismatched inputs block entry/rebalance; active risk handled by reconciliation |
| F28 | editable config | equity threshold constructor; qty cap hard-coded | 설정 이관: versioned schema/hash and central capital/risk gates |
| F29 | acceptance | tests cover positive delta sell and deadband no-op only | 표준으로 해결: exhaustive test plan required; tests NOT_RUN in this document task |

## 5. 코드-표준 차이표

| 코드 경로 | 관찰된 구현 | 표준 대비 분류 | 문서상 필요한 후속 검증 |
|---|---|---|---|
| `core/strategy/track4_gamma_scalping.py` | `evaluate_basecamp` emits `NON_EXECUTION`; `evaluate_delta_hedge` can emit Futures signal without confirmed option lots; target stored before fills | 불일치 | Gate hedge on actual S4-owned option positions; actual qty from fills |
| same file | `target_abs_qty=min(delta_to_mini_futures_qty(abs(delta)),100)` | 불일치/임시 상수 | `max_hedge_qty` plus capital/margin gate; rounding and unit proof |
| same file | equity threshold defaults zero and equity failure unwinds only Futures hedge | 불일치/정책 미정 | active option lifecycle and terminal group close semantics |
| same file | P&L trailing threshold 30000 and retention 0.85/0.88/0.90; closes Futures hedge only | 불일치/임시값 | combined S4-owned options+Futures P&L and joint exit |
| same file | evaluation emits basecamp, hedge, then trailing signals without explicit deterministic priority | 불일치 | deterministic priority and compatible plan arbitration |
| `application/composition/track4_market_input_materializer.py` | aligns tick/runtime/Greeks timestamps; passes current delta/gamma/theta, P&L/equity, premium; accumulated gamma profit/theta decay cost are None | 부분 일치 / 데이터 미구현 | per-lot option inventory/IV/freshness, realized gamma and theta-cost lineage |
| `application/composition/track4_runtime_strategy_seam.py` | builds S4 StrategyContext and routes signal | 부분 일치 | verify resolver, config disabled gate and actual execution read-model provenance |
| `application/composition/track4_analytics_provider.py`, `core/analytics/track4.py` | analytics exposes passthrough volatility, options delta/gamma/theta, portfolio P&L/equity | 부분 일치 | confirm values are S4-owned, units and source freshness; portfolio P&L must not drive S4 trailing unfiltered |
| `core/delta_hedge_quantity.py`, `core/risk/delta_hedge_quantity.py` | shared delta-to-mini quantity conversion; risk module re-exports helper | 미검증 | verify option/futures multipliers, sign convention, rounding, delta per contract vs aggregate |
| `application/composition/virtual_track4_attribution_source.py`, `contracts/track4_attribution_provider.py` | attribution provider paths exist | 미검증 | inspect if authoritative per-lot fills and realized/unrealized S4 P&L are actually consumed end-to-end |
| `application/composition/track4_runtime_input_provider_factory.py`, `contracts/track4_composite_runtime_input_provider.py`, `contracts/track4_kis_greeks_provider.py`, `contracts/track4_vssf_account_projection_provider.py` | provider contracts exist | 미검증 | prove exact option lot ownership, account-vs-strategy delta boundary, source status and fail-closed behavior |
| `resolve_track4` in `application/composition/automated_virtual_runtime_factory.py` (location/name to verify) | prior matrix refers to resolver; current complete path not established by this read | 미검증 | map actual resolver/plan/order/fill path; no inferred PASS |
| `tests/strategy/test_strategy4.py` | observed tests: positive delta proposes SELL; deadband case emits no signal | 부분 확인 / insufficient | test plan adds ownership, caps, partial fills, terminal close, restart, expiry, stale input, config-disabled gates |

## 6. v0.2 unresolved registers and gates — exhaustive classification

The v0.2 F-register contains F01–F29; all are classified in §4. This section carries forward the S4-related open items found in the integrated registers. Items outside S4 remain unchanged in the source versions.

### v0.2 D01–D10 unresolved register (source used D, not U)

The v0.2 file has no U01–U15 or G-register table. Its actual S4 unresolved register is D01–D10, and the integrated matrix separately has U04 and U12 plus G01–G12/I01–I16. These registers are kept distinct; no invented U IDs are treated as source records.

| v0.2 ID | Original unresolved item | Classification | v0.3 disposition |
|---|---|---|---|
| D01 | Basecamp actual option trade vs state-only | 표준으로 해결 | Current BASECAMP is NON_EXECUTION, not an option order. New standard requires actual option fills before hedge. |
| D02 | Which option lots determine delta | 표준으로 해결 | S4-owned, actually filled option lots only; runtime proof still blocked. |
| D03 | Delta/deadband units and conversion | 설정 이관 | Delta units, multiplier, point value, sign and rounding must be sourced; null blocks. |
| D04 | Target qty cap/equity threshold/max delta error | 설정 이관 | `max_hedge_qty`, capital/margin gate and risk limits; no hard-coded 100 as standard. |
| D05 | Trailing closes hedge only or option group | 표준으로 해결 | Terminal gamma-scalping exit closes owned options and linked hedge; actual per-leg flat confirmation required. Thresholds stay configurable. |
| D06 | Order pricing/partial-fill recovery | 설정 이관 | Order type/collar/reprice/timeout configurable; leg-level fills and cancel race are standard requirements. |
| D07 | Expiry/session/restart | 설정 이관 | No overnight and 15:10 candidate; exact DTE/calendar and restart persistence need evidence. |
| D08 | Editable total capital/premium/max-loss values | 사용자 확인 필요 | Capital and account/strategy loss caps need user confirmation before activation. |
| D09 | Cross-strategy delta ownership | 사용자 확인 필요 | S4-owned delta recommended; account-level aggregation is separate, with final activation policy to be confirmed. |
| D10 | P&L attribution and theta cost | 설정 이관 | Own-option MTM + linked Futures fills + fees/slippage/theta cost; source and thresholds unverified. |

### Integrated matrix U register (S4-related)

| ID | Integrated matrix item | Classification | v0.3 treatment |
|---|---|---|---|
| U04 | Eligible option lots, delta units and basecamp role | 표준으로 해결 + 설정 이관 | Option-fill ownership and own-option delta required; IV/lot details require evidence. |
| U12 | Account-wide aggregate exposure/correlation/netting policy | 사용자 확인 필요 | S4 hedge scope is own options only as standard proposal; account risk aggregates all strategies separately. |
### G01–G12 gates

| Gate | S4 v0.3 assessment | Missing evidence / disposition |
|---|---|---|
| G01 Purpose/economics | PARTIAL | standard purpose defined; real option inventory/IV edge and combined economics not verified |
| G02 Entry/wait/add/reverse | BLOCKED | IV/realized-vol edge, basecamp meaning, entry/cancel policy require config and data |
| G03 Identity/expiry/multiplier/qty | BLOCKED | exact option/Futures master, multiplier and rounding evidence |
| G04 Partial/no-fill/reject/cancel race | BLOCKED | plan described; runtime coverage not verified |
| G05 Hedge/rebalance | BLOCKED | option ownership gate, actual qty and deadband consistency not implemented/proven |
| G06 Stop/TP/trailing/time exit | BLOCKED | strategy P&L, joint option+hedge terminal exit and threshold values unresolved |
| G07 Expiry/session/overnight | PARTIAL | no overnight and 15:10 candidate specified; DTE/session validation missing |
| G08 Cost/capital/max loss/account risk | BLOCKED | null capital gate, margin, fee/slippage and stress loss data |
| G09 Failure/restart/idempotency | BLOCKED | durable reconciliation/resume evidence absent |
| G10 Spec-code-test traceability | PARTIAL | F map and scenario plan defined; execution evidence/test IDs remain NOT_RUN |
| G11 Assumptions/dependencies | PARTIAL | remaining settings/approval needs listed |
| G12 Verification vs approval | PASS (process only) | this remains draft/unverified/unapproved and disabled |

### S4 interaction register I01–I16 disposition

| ID | S4 interaction | Classification / proposal |
|---|---|---|
| I01 | Shared capital/premium/max-loss/margin | disabled S4 must not reserve active strategy budget or consume other strategies' deployable capital; any existing positions still count in account risk. Activation requires atomic budget reservation and approved caps. BLOCKED |
| I02 | Futures identity offset/duplicate hedge | S4 hedge Futures must retain S4 ownership and not be netted away without risk accounting; compare against S3/S5 and all actual/pending Futures lots. BLOCKED |
| I03 | Option lot/delta ownership | S4 hedge only its own filled option lots; account risk aggregates all positions separately. BLOCKED |
| I04 | Overlapping insurance pairs/tail risk | not primary S4 gamma pair rule, but its long options/premium must count in account scenario risk. BLOCKED |
| I05 | Multi-leg partial fill/cancel race | S4 option pair and terminal close are per-leg stateful grouped plans; no atomicity assumption. BLOCKED |
| I06 | Strategy/account P&L attribution | S4 P&L includes own options + associated futures + fees/slippage/theta cost; account P&L is not an S4 proxy. BLOCKED |
| I07 | Expiry/session/overnight | close all S4 positions by configured 15:10 candidate, no overnight; calendar and DTE gate required. BLOCKED |
| I08 | Risk exits vs profit/hedge exits | risk/expiry/force-close > reconcile/terminal exit > rebalance > trailing > entry. BLOCKED |
| I09 | Data freshness/unavailable | missing/stale/mismatched IV, Greeks, lots, quote, multiplier, margin blocks new risk. BLOCKED |
| I10 | Restart/duplicate/state restore | restore and reconcile orders/fills/positions/config hash before hedge action. BLOCKED |
| I11 | S5 Futures role | separate S5 policy; S4 hedge must not be reclassified as substitute alpha/options. Keep role provenance. OPEN |
| I12 | S3 spread identity | separate S3 calendar spread; shared account Futures risk must retain leg identity/owner. OPEN |
| I13 | S4 basecamp and hedge ownership | resolve as standard: state-only basecamp is not option position; actual option fills required before hedge. Runtime enforcement unverified. BLOCKED |
| I14 | S8 macro add-on | separate strategy ownership; account risk aggregates actual lots without transferring S4 delta ownership. OPEN |
| I15 | Daily/weekly/overnight re-entry | S4 cycle may restart only after old group is flat-confirmed and new session/expiry gates pass. BLOCKED |
| I16 | Editable config consistency | shared schema/version/hash and account caps; disabled/null fail-closed. BLOCKED |

## 7. Required approval before any activation

No questions are asked in this work. The following are recorded as user-confirmation items before activation:

1. `capital_gate_min` and approved account/strategy margin/max-loss limits.
2. Confirm S4 delta scope as own-options-only (market-standard recommendation); account-wide aggregation remains a separate risk layer.
3. Confirm option structure: long ATM straddle or near-ATM strangle, after REAL_VTS evidence.

## 8. Required validation evidence before status can advance

- Exact contract/expiry/strike/multiplier and quote freshness from authoritative master/source.
- IV and realized-volatility comparison, cost-aware expectancy, and separated tuning/validation REAL_VTS periods.
- Verified delta units/sign/rounding and at-least-one-contract deadband.
- Per-leg order/fill/cancel-race/restart reconciliation and actual-flat confirmation.
- S4-attributed options+Futures P&L, theta/fees/slippage and stress-loss evidence.
- Disabled/capital gate enforcement through registry, budget allocator and VTS runtime.
- All required scenario plans executed only after separate approval; tests were not run in this document task.

## 9. Status and change log

- v0.3 is **DRAFT / UNVERIFIED / UNAPPROVED**; `enabled=false`.
- v0.2 is retained unchanged as historical evidence, not current implementation authorization.
- No Decision Log status was changed. Any future No. entry must label this as a proposal, not confirmation.
- This task makes no code/test/Git/Live changes.
## 2026-11-23 U16 recovery validation follow-up (No.1768)

A validation-only test uses an S4 MINI synthetic group/leg identity with the existing U16 coordinator and SQLite state store:

- A cancelled original hedge order with 2/5 filled creates a validation repair intent for the missing quantity 3.
- After restart, the actual U19 recovery coordinator is run against matching synthetic broker-position and execution-ledger snapshots. Only `RESTORE_ALLOWED` authorizes U16 state restoration; `new_entry_enabled` and `order_submission_enabled` remain false.
- Before the previous repair is terminal and position-reconciled, the restarted U16 coordinator waits and does not invoke the repair callback. After explicit terminal/reconciled evidence, the next retry slot may request only the missing quantity 3.
- A broker/ledger position mismatch denies U16 restore.

**Scope limitation:** this is a pure validation-coordinator/state-store harness with test callbacks, not a routed S4 Runtime repair. `ValidationOnlyU16VirtualBridgePorts` currently scopes its authoritative entry-plan provider to `track2_asymmetric_trap`, and `Track4State` remains in-memory without an S4 snapshot/restore contract. S4-specific U16-to-VirtualBridge wiring and durable strategy-state rehydration remain OPEN. No Production code or policy is changed by this evidence.
## 2026-11-23 validation update — MINI Futures freshness fault slice (No.1769)

A validation-only S4 MINI Futures bridge test now injects five pre-route freshness faults: STALE, UNKNOWN, CAPABILITY_CONFLICT, FRESH with mismatched command symbol, and missing verdict. Every case must return REJECTED before VSSF order-command submission; no PositionLot or account position may be created. The test uses synthetic S4 identity and derived evidence only.

This closes the focused test slice for F04/F27 freshness/provenance admission. It does not close the broader F04/F27 strategy-input, active-position risk, or full F01-F29/G01-G12 matrix. Existing S4 partial-fill/cancel/late-fill/U19 restart and No.1768 U16 coordinator harness results remain separate evidence. U16 VirtualBridge routing and Track4State durable strategy snapshot/restore remain OPEN. Strategy specification status remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED.
## 2026-11-23 validation update — MINI Futures margin preflight fault (No.1770)

A validation-only S4 MINI Futures bridge case now sets the synthetic VSSF account free-margin snapshot to zero while supplying a fresh, identity-matched synthetic freshness verdict. The bridge must return a margin-related REJECTED report before VSSF order-command submission, with zero routed/filled quantity and no PositionLot/account position mutation. This covers one focused F12/F14 account-margin admission fault; it does not establish authoritative live margin requirements, strategy max-loss, stress-loss, or the full risk-preflight matrix.

S4 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED. No production risk parameters or order behavior were changed.
## 2026-11-23 S4 active-position / pending-order reconciliation slice (No.1771)

Extended the existing S4 MINI 2/5 partial-fill → pending/cancel → late-fill scenario with U19 evidence-gated reconciliation:

- While the residual quantity 3 order is pending, broker position and PositionLot-derived signed ledger both equal -2. U19 still returns `PENDING_ORDER_RECONCILIATION_REQUIRED`; restore, new entry and order submission remain disabled because a late fill is possible.
- After terminal cancel removes the pending-order uncertainty, a synthetic broker quantity -2 versus ledger quantity -1 returns `POSITION_LEDGER_MISMATCH` and denies restore.
- Matching broker/ledger signed quantity -2 returns `RESTORE_ALLOWED` only as a validation recovery decision; new entry and order submission remain disabled.
- Existing late-fill reconciliation then adds the remaining quantity 3 and retains the exact-once execution/position/fee checks.

This closes a focused S4 active-position/pending-order/U19 quantity reconciliation slice. It does not establish real broker truth, automatic Track4State restore, S4 U16 VirtualBridge routing, or full F01-F29/G01-G12 acceptance. No Production reconciliation implementation or policy was changed; all snapshots and identities are synthetic validation-only.
## 2026-11-23 S4 signed-position and close-quantity characterization (No.1772)

Extended the synthetic S4 active-position/U19 test slice:

- A signed-side conflict (+2 broker vs -2 execution ledger) is classified as `POSITION_LEDGER_MISMATCH`; no restore is permitted.
- A pre-close quantity conflict (-4 broker vs -5 PositionLot-derived ledger) is classified as `POSITION_LEDGER_MISMATCH`; the test confirms no additional VSSF order command is submitted while this evidence is unresolved.
- With two distinct late-fill execution lots totaling five open contracts, the existing close-plan builder derives one BUY close leg for exactly five contracts.

**Important boundary:** this is U19 evidence/close-plan characterization, not an automatic account-vs-PositionLot admission guard. The current `build_close_plan_from_open_lots` derives quantity from PositionLots; it does not itself reconcile broker/account side and quantity before returning a close plan. No Production semantics were changed because that integration requires an explicit contract decision. Keep automatic pre-close reconciliation admission OPEN.

## 2026-11-23 S4 synthetic close-lifecycle / group-scope validation (No.1773)
- Extended the existing MINI Futures Virtual Runtime scenario with a 2/5 partial close, terminal cancellation of the residual close order, reconstruction from the remaining 3 PositionLot units, and final 3-unit BUY close to flat.
- Added builder characterization for run/strategy scoping, same-group actual-quantity aggregation, and fail-closed rejection of ambiguous multiple open groups.
- Focused combined S4/U16/profile/close-lot suite: 54 passed; compileall and git diff --check PASS.
- This is not account/broker position reconciliation before close. No Production code or reconciliation semantics changed. F12/F14 margin admission remains a focused synthetic slice only; max-position, max-loss, stress-loss, delta residual, fee/slippage and other operating risk limits remain unresolved. G06/G08 and complete F01-F29/G01-G12 acceptance remain OPEN; specification remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED.

## 2026-11-23 S4 synthetic margin-boundary characterization (No.1774)
- Extended the F12/F14 focused margin admission test to characterize both sides of the existing strict `required_margin > free_margin` comparison. The synthetic test fixture derives 250,000,000 KRW from price 1,000 ? quantity 5 ? MINI multiplier 50,000; this is not a live margin rule or approved account limit.
- At 249,999,999 KRW free margin the order is rejected before VSSF order-command submission, with no routed/fill quantity or position mutation. At exactly 250,000,000 KRW the current preflight accepts and the 5-unit synthetic order fills.
- Combined S4/U16/profile/close-lot suite: 55 passed; compileall/Ruff F821+F401/git diff-check PASS.
- This closes only the synthetic arithmetic boundary characterization for the current code path. It does not approve real-account margin schedules, margin utilization, max-position, max-loss, stress-loss, fees/slippage, or the full risk matrix. No Production code/policy changed; S4 remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED.

## 2026-11-23 S4 generic configured margin-utilization boundary (No.1775)
- Characterized current generic RiskConfig default `max_margin_utilization_ratio=0.85` in synthetic validation: (used margin 600,000,000 + required margin 250,000,000) / total balance 1,000,000,000 = 0.85 and exact equality passes; used margin 600,000,001 gives 0.850000001 and rejects before VSSF order submission.
- Combined S4/U16/profile/close-lot suite: 57 passed; compileall/Ruff F821+F401/git diff-check PASS.
- The 0.85 value is a generic code default only, not an approved S4 or real-account limit. No Production policy/adapter changed. S4 remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED; full F01-F29/G01-G12 risk acceptance remains OPEN.

## 2026-11-23 S4 synthetic position-cap boundary characterization (No.1776)
- Added an integration-level synthetic S4 MINI risk preflight boundary: requested quantity 5 with configured generic `max_position_per_instrument=4` is rejected before VSSF order command; exact configured limit 5 is accepted and fills 5 in Virtual validation.
- The test also retains No.1774 free-margin and No.1775 generic margin-utilization boundary cases. S4 target file 17 passed; combined S4/U16/profile/close-lot batch 59 passed; compileall/Ruff F821+F401/git diff-check PASS.
- Values 4 and 5 are synthetic boundary inputs only, not approved S4 position caps. No Production risk policy/adapter changed. S4 remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED; full F01-F29/G01-G12 matrix remains OPEN.

## 2026-11-23 S4 synthetic realized daily-loss preflight boundary (No.1777)
- Added an integration-level S4 MINI Virtual risk-preflight characterization of the existing generic `RiskConfig.max_daily_loss_krw` rule. With synthetic test cap 1,000 KRW, account realized PnL -999 KRW admits the 5-unit order; exact realized loss -1,000 KRW rejects before VSSF order command.
- S4 target file 19 passed; combined S4/U16/profile/close-lot batch 61 passed; compileall/Ruff F821+F401/git diff-check PASS.
- The 1,000 KRW threshold is test-only, not approved S4 or real-account policy. Only the current realized-loss preflight branch was characterized; unrealized/stress loss, option+hedge attribution, costs, and account aggregation remain unverified. No Production risk code/policy changed; S4 remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED.


## 2026-11-23 S4 synthetic unrealized-loss risk-path characterization (No.1778)
- Extended the existing S4 MINI synthetic risk-preflight parameterization with two unrealized-loss cases: realized PnL 0, unrealized PnL -1,000 and -1,001 KRW, test `max_daily_loss_krw` 1,000 KRW. Both cases were admitted and the 5-unit synthetic order filled.
- Source trace explains the result: `VSSFAccountSnapshotAdapter` carries `unrealized_pnl`, but `account_snapshot_to_risk_input` projects only cash/realized_pnl/margin_used/available_cash into `RiskAccountInput`; the type itself has no unrealized-PnL field. `RiskEngine.evaluate_order` uses accumulated realized loss and negative current realized PnL only.
- No stress-loss field, stress scenario valuation, or stress-loss preflight calculation was found in the current generic RiskConfig/RiskEngine path. No formula, threshold, or production behavior was invented or changed.
- Focused S4/U16/profile/close-lot/spec batch: 39 passed; compileall, Ruff F821/F401 and git diff-check PASS. This is a current-code gap characterization, not a PASS for unrealized/stress loss control. Keep these items, S4 option+hedge attribution, fees/slippage, account-wide aggregation and full F01-F29/G01-G12 acceptance OPEN. S4 remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED.


## 2026-11-23 D10/I06 synthetic option + linked Futures attribution follow-up (No.1779)
- Read-only source audit: Virtual Track4 attribution currently derives executed OPTION BUY premium only; accumulated gamma profit and theta decay cost raise unavailable. Market projection readiness is hardcoded attribution=false, and materialization still supplies gamma-profit/theta-cost as None. Account PnL is not an S4-owned PnL substitute.
- Added a test-only synthetic arithmetic harness scoped to one S4 strategy/group. It FIFO-matches fills, splits realized option/Futures PnL, marks remaining option/Futures lots separately, subtracts per-fill synthetic fees and reference-price slippage, and excludes unrelated strategy/group executions. Missing open-lot marks and multiplier mismatch are rejected.
- Fixture output: realized option +750,000; realized Futures +250,000; unrealized option -500,000; unrealized Futures +250,000; gross +750,000; fees 400; synthetic slippage 300,000; net after execution costs 449,600 KRW. Theta diagnostic 80,000 KRW is retained separately to avoid double-subtracting an estimate from option MTM.
- This is validation-only arithmetic, not a production attribution implementation or approved S4 fee/slippage/theta methodology. No.1495 MID/cost decision is S2-specific. D10/I06 remain OPEN pending approved S4 ownership/linkage and valuation/decomposition contract. No Production code changed; status remains DRAFT/UNVERIFIED/UNAPPROVED/DISABLED.


## 2026-11-23 validation update — Gamma/Theta decomposition and execution linkage (No.1780)

A validation-only fixture now decomposes synthetic option mark-to-market using an explicitly declared Taylor convention:

- delta: option-price change per underlying point
- gamma: option-price change per squared underlying point
- theta: option-price change per elapsed day
- vega: option-price change per decimal IV unit
- residual: observed option MTM less the four modeled components

Fixture arithmetic: option MTM +38 = delta +40 + gamma +16 + theta -20 + vega +2 + residual 0. A same-strategy/same-group synthetic short MINI Futures mark contributes +100 unrealized PnL, so combined observed option+Futures MTM is +138. Theta decay cost +20 is a diagnostic representation of theta PnL -20 and is not subtracted again from MTM. A separate mark perturbation leaves residual +10 visible.

Source/execution audit:
- H0IOCNT0 Greeks are passed through as raw values; the current snapshot does not declare their units, theta time basis, or IV scale.
- Virtual execution-ledger attribution remains OPTION BUY premium-only; gamma/theta are unavailable. Market projection readiness remains false and runtime materializer still supplies both as None.
- Current Basecamp emits NON_EXECUTION rather than an option order. Actual option fill → S4-owned option lot → linked Futures hedge → authoritative attribution is not an established end-to-end path.
- The synthetic unit convention is a test fixture only. It is not an approved KIS conversion, S4 accounting rule, threshold, or Production/Live criterion.

Validation: 8 tests in the new file plus 3 existing attribution tests passed (11 total). The broader selected S4 regression and compile/lint checks are recorded in No.1780 Q&A. No Production Strategy/Provider/Risk/Runtime/OMS/Router or execution semantics changed.

D10/I06, authoritative Greek units and valuation, option lot ownership, linked hedge ownership, authoritative fees/slippage, and end-to-end Runtime attribution remain OPEN. S4 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED.


## 2026-11-23 validation update — S4 position-lot ownership and linked asset isolation (No.1781)

The VirtualPositionLotStore previously matched an opposite execution to an open lot using instrument, side and group, without checking run or strategy ownership. Its execution fingerprint also omitted run_id. A synthetic same-group collision reproduced a cross-run close.

The lot store now scopes FIFO close candidates to the exact run_id, strategy_id, group_id and instrument_id plus opposite side. The execution fingerprint includes run_id, so reuse of one execution_id with conflicting run provenance is rejected.

Validation-only fixture:
- Synthetic OPTION and MINI Futures lots share one S4 run/strategy/group but retain distinct instrument identities and multipliers.
- A partial OPTION close reduces only the OPTION lot; the linked MINI Futures hedge lot remains open.
- Same instrument/group collisions across runs and strategies do not cross-close.
- Reused execution_id with conflicting run provenance raises POSITION_PROVENANCE_DUPLICATE_CONFLICT.

Focused input-independent regression: 62 passed; compileall, Ruff F821/F401 and diff-check PASS. Three tests in the broader batch could not run to completion because the accepted runtime-v2 dataset and FRESH61 JSONL fixture were absent; those cases remain unverified and were excluded from the focused regression.

This is a virtual lot provenance/FIFO fix, not evidence of an actual S4 option-entry path or authoritative KIS/Production hedge linkage. D01/D02/F17/F24/D10/I06 and full option-fill → owned lot → linked Futures → attribution remain OPEN. S4 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED.

## 2026-11-23 S4 synthetic fill-to-owned-lot materialization (No.1782)

The existing `VirtualMultiLegExecutionBridge._apply_reconciled_execution()` method is the current Virtual execution-fill materialization seam. It checks client-order/group/leg lineage, expands canonical fill reports, creates a provenance-owned lot with bridge run ID and plan strategy/group/leg identity, records the fill fee, and updates an instrument-specific Virtual position aggregate.

A validation-only test invokes that method directly with synthetic OPTION and linked MINI Futures fills. Both legs use the same synthetic S4 run/strategy/group but distinct instrument IDs and multipliers. The test verifies the resulting owned lots and fee records, replay of the exact same execution without duplicate mutation, and a partial OPTION close that does not change the MINI Futures hedge lot.

All identity source labels are `SYNTHETIC:DERIVED_SCENARIO`. Fixture multipliers (OPTION 10, MINI Futures 50,000), prices and fees are test inputs, not KIS or approved S4 criteria. This method-level test is not a complete S4 Runtime dispatch, OMS/VSSF, broker, hedge-sizing/atomicity, or restart test. Actual strategy-to-bridge dispatch, linked hedge integration, authoritative Greek units/valuation, fees/slippage, D01/D02/F17/F24/D10/I06 and full end-to-end attribution remain OPEN. S4 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED.

## 2026-11-23 S4 Runtime option-proposal route boundary (No.1783)

The Strategy 1-9 Option Hedge Specification v0.1 remains DRAFT and is not an approved S4 option-entry contract. Its Strategy 4 classification states that Basecamp is NON_EXECUTION and that current executable proposals are Futures hedge/unwind; the authoritative source for an actual option position must be identified before adding option legs.

Source inspection confirms `Track4GammaScalping.evaluate_basecamp()` emits a `NON_EXECUTION` state event without an execution proposal, while `evaluate_delta_hedge()` emits a FUTURES proposal. The standard Runtime `resolve_track4()` accepts only FUTURES proposals and returns no execution plan for an OPTION proposal. A validation-only synthetic test now calls the actual loop resolver with an OPTION proposal and verifies that it returns no plan and creates no PositionLot.

Focused S4 Runtime identity + spec alignment + attribution + Greek decomposition regression: 40 passed. This characterizes the current route boundary only; it does not implement an option-entry route, approve an option contract, or establish Production/Live readiness. No Production Strategy/Runtime/OMS/Router/order semantics changed. Actual option-entry source and approved leg contract, authoritative identity/quote/multiplier, capital/margin/fee/risk gates, linked hedge sizing/atomicity, D01/D02/F17/F24/D10/I06 and full end-to-end attribution remain OPEN. S4 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED.

## S4 option ownership input boundary follow-up (No.1784)

- A validation-only strategy-method test now exercises the actual `Track4GammaScalping.evaluate_basecamp()` and `evaluate_delta_hedge()` helpers with explicit synthetic values.
- Basecamp emits a `NON_EXECUTION` state event with strike hints only; it does not create an OPTION proposal or bind a contract identity through Option Master.
- `Track4MarketInput` contains aggregate Greek values but no S4-owned option lots, Option Master contract identity, or fill lineage. `evaluate_delta_hedge()` can nevertheless emit a MINI Futures proposal from the supplied aggregate delta. The helper has no ownership evidence parameter/gate.
- This is a reproducible source/contract gap characterization, not approval to add an option-entry contract or change Production hedge semantics. S4 v0.3 remains DRAFT / UNVERIFIED / UNAPPROVED / DISABLED. The future authoritative contract must define owned filled option-lot scope and prove the delta source maps to those lots before any activation.
- Focused target test file: 23 passed. compileall, Ruff F821/F401, and git diff-check PASS.
