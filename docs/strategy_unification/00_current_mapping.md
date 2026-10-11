# Strategy 1–9 Current Code Mapping

- 조사 기준: Project200 HEAD e343c1dbb5abecee81e15a4b72b9a0330e302b47
- 기준 태그: baseline-current-implementation-20261011
- 명세: Notion KOSPI200 Project — Strategy Specification v1.0 (Strategy 1~9), 2026-10-08
- 범위: 읽기 전용 조사. 전략/환경/엔진 코드는 수정하지 않았다.
- 줄번호는 위 HEAD 기준이다. 명세와 코드가 다르면 실제 코드를 기준으로 기록한다.

## 1. 전략별 현황

### S1 — Tail Defense
- ID/version: TRACK1_TAIL_DEFENSE / 1.1.0. Manifest config/strategies/strategy-manifest.v1.json:6-10; class core/strategy/track1_tail_defense.py:42-58.
- 상태/reset: Track1State :27-40, _hedge_exit_pending :65-68, initialize/reset :74-76, reset :249 이후. 실행 결과 callback :113-129.
- 조건/파라미터: DTE cutoff 4.0, initial/outer fence distance, volatility multiplier, approach ratio, hedge reversion 1.5pt :53-58; manifest :22-31. Fence/DTE 조건 :144-172, hedge unwind :235-247.
- Signal→plan: application/composition/automated_virtual_runtime_factory.py:372-386; Futures proposal만 처리, unwind tag는 open-lot close plan, 그 외 Futures single-leg plan. Registry :493.
- NON_EXECUTION: S1 전용 이벤트는 이번 확인에서 특정하지 못함.
- Fill 의존: unwind pending 및 execution callback :113-129, :243-247. DTE≤4는 fence 관리 정리 의미이며 전체 포지션 강제청산으로 확대 해석하지 않는다.

### S2 — Asymmetric Trap
- ID/version: track2_asymmetric_trap / 1.0. Manifest :35-39; class core/strategy/track2_asymmetric_trap.py:21-47.
- 상태/reset: _exit_pending :51-60, reset :78-87, callback :92-106, close signal :108-120.
- 진입: BBW, volume z-score, OBI, futures basis, put/call IV, POC distance, regime/cooldown/cutoff :238-260. 4-leg builder :123-191.
- 청산: stop -30%, trailing activation 30%, watermark tiers 50%/100%, retain 85%/88%/90% :27-38, :193-221.
- Signal→plan: factory resolve_track2 :282-308; TRAP_CLOSE는 open-lot close plan, entry는 track2_plan_adapter. Registry :494.
- NON_EXECUTION: 별도 NON_EXECUTION event는 이번 코드 확인에서 특정되지 않음.
- Fill 의존: TRAP_CLOSE callback/pending :92-106; close leg 수량은 resolver의 open-lot 근거에 의존.

### S3 — Statistical Arbitrage
- ID/version: Strategy_3_StatArb / 1.0. Manifest :87-91; class core/strategy/track3_statistical_arbitrage.py:49-90.
- 상태/reset: active_position/group, _exit_pending, high-watermark/cooldown :49-90; callback :93-105; _close :315 이후.
- 진입/청산: z entry 2.0, exit ±0.2, stop ±3.5, max hold 300 ticks, minimum net profit 15,000, round-trip cost manifest :119-127; cutoff :279-280; trailing :287-295.
- Signal→plan: factory resolve_track3 :310-370; CLOSE_STAT_ARB는 open-lot close plan, entry는 futures identity와 strategy-specific plan adapter. Registry :497.
- NON_EXECUTION: 이번 조사에서 특정 이벤트 미확인.
- Fill 의존: _close는 exit-pending을 설정하고 callback 대기 :93-105, :315 이후. 실제 그룹 종료와 잔여 수량은 open-lot 근거가 필요하다.

### S4 — Gamma Scalping
- ID/version: track4_gamma_scalping / 1.0. Manifest :130-134; class core/strategy/track4_gamma_scalping.py:34-48.
- 상태/reset: basecamp_active, is_active :34-40; pending/callback :48-64; reset :164 이후.
- 진입/헤지: Basecamp regime :83-93; delta/deadband hedge :95-125; trailing :127-140. equity_threshold는 manifest :157-159 및 class :45-48.
- NON_EXECUTION: BASECAMP_BUILD 및 TRACK4_PROFIT_TAKEN :83-92, :127-140. Basecamp 이벤트는 주문이 아니다.
- Signal→plan: factory resolve_track4 :388-402; Futures proposal, unwind는 open-lot close plan, hedge는 Futures single-leg plan. Registry :495.
- Fill 의존: UNWIND_FUT_HEDGE / PROFIT_TAKEN_TRAILING_STOP callback :56-64. Hedge-only action을 옵션 포지션 청산으로 확대하지 않는다.

### S5 — Gap Divergence
- ID/version: track5_gap_divergence / 2.0. Manifest :162-166; class core/strategy/track5_gap_divergence.py:26-59.
- 상태/reset: Track5State의 active/direction/entry/target/stop/open_ticks/peak_pnl/trailing :26-44; initialize/reset :71-80; execution callback :239-295.
- 진입: regime별 gap Z threshold :80-190; stop distance max(1.0, expected_move×0.8) :172-178; option + Futures hedge proposal.
- 청산: gap fill 시작 시 Futures-first non-terminal unwind, 이후 previous close에서 Option close; stop/timeout/trailing :203-238, :296-390. 순서를 보존한다.
- Signal→plan: factory resolve_track5 :444-475; proposal 필수, Futures tag별 분기, SELL Option은 open-lot close, 나머지는 build_execution_plan :410 이후. Registry :496.
- NON_EXECUTION: 이벤트 목록 완전성을 이번 조사에서 확정하지 못함(BLOCKED).
- Fill 의존: execution callback :239-295에서 Futures 결과 이후 Option lifecycle 전이. Futures-first는 terminal grouped close와 구분한다.

### S6 — Daily Tail Insurance
- ID/version: track6_daily_tail_insurance / 1.0. Manifest :199-203; class core/strategy/track6_daily_tail_insurance.py:26-46.
- 상태/reset: is_active, high_watermark_intrinsic, trailing/pending :26-46; reset/callback :63-75.
- 진입: active vol ≥ base vol×1.3, authoritative listed PUT/CALL :97-149; manifest qty :225-228.
- 청산/시간: intrinsic proxy/trailing :151-198; 15:00 LIMIT close, 15:15 fallback :201-218; manifest modes :219-228.
- Signal→plan: factory resolve_track6 :404-415; SELL은 open-lot close plan, entry는 pair plan. Registry :498.
- NON_EXECUTION: pending tranche cancel 관련 :108. 이벤트 전체 목록은 미완전 확인(BLOCKED).
- PRESERVE: premium_spent 기반 보험가치 프록시를 그대로 유지한다. evaluate_take_profit은 high-watermark 갱신 후 high > self.state.high_watermark_intrinsic 비교(:173-187)로 보여 UPDATE_TRAILING 반환 조건이 사실상 항상 false인 것으로 보인다. 이번 통합에서 수정하지 않는다.

### S7 — Weekly Volatility Skew Insurance
- ID/version: track7_volatility_skew_weekly_insurance / 1.0. Manifest :231-235; class core/strategy/track7_volatility_skew_weekly_insurance.py:20-41.
- 상태/reset: weekly position/high-watermark/pending :20-41; reset/callback :54-66.
- 진입: new-week + authoritative expiry/option contracts :89-120; PUT+CALL plan :127-141.
- 청산: 20% trailing drawdown :35-36, :101-102; expiry-day 15:00 :108; manifest :250-257.
- Signal→plan: factory resolve_track7 :417-431; SELL은 open-lot close plan, BUY는 strategy builder. Registry :499.
- NON_EXECUTION: S7 전용 이벤트는 이번 조사에서 특정하지 못함.
- Fill 의존: mark_exit_pending/callback :58-66. 실제 Virtual bridge acceptance는 미검증.

### S8 — Macro Regime Monthly Strangle
- ID/version: track8_macro_regime_monthly_strangle / 2.0. Manifest :261-265; class core/strategy/track8_macro_regime_monthly_strangle.py:12-48.
- 상태/reset: is_active, strikes/qty, entry_date, high_watermark_intrinsic, trailing/pending :12-48; reset/callback :52-60.
- 진입: DTE≥15, budget≥200,000, authoritative strikes/multipliers :83-98; manifest :299-310.
- 청산/헤지: trailing :109-129; macro hedge :131-147; 15:15 pending cancel :155-159; DTE≤4 HOLD_LONG_ATTACK NON_EXECUTION :157-161.
- Signal→plan: factory resolve_track8 :433-442; SELL은 open-lot close plan, 그 외 build_execution_plan은 BUY pair :163-166. Registry :500.
- NON_EXECUTION: TRACK8_MACRO_HEDGE_STATE, TRACK8_PENDING_CANCEL, TRACK8_HOLD_STATE :136-161.
- PRESERVE: high-watermark 갱신 후 high > self.state.high_watermark_intrinsic 비교(:116-129)로 UPDATE_TRAILING 반환 조건이 사실상 항상 false인 것으로 보인다. DTE≤4는 강제청산이 아닌 NON_EXECUTION. 둘 다 수정하지 않는다.

### S9 — Event Overnight Insurance
- ID/version: track9_event_overnight_insurance / 3.0. Manifest :313-317; class core/strategy/track9_event_overnight_insurance.py:23-55.
- 상태/reset: entry_date, entry price/premium, peak profit, trailing/closed-next-open :23-38; pending/reset/callback :69-94.
- 진입: 15:10 :46-55, :160-194; shock 1%와 giveback 30%는 manifest :339-344.
- 청산: next-session shock/no-shock/trailing :222-287; pair builder :291-315.
- Signal→plan: factory resolve_track9 :477-491; SELL은 open-lot close plan, entry는 pair builder. Registry :501.
- NON_EXECUTION: S9 전용 이벤트는 이번 조사에서 확정하지 못함.
- Fill 의존: pending/callback :81-94, :291-315. entry quantity는 실제 close remaining quantity의 증거가 아니다.

## 2. 공통 실행 경로, manifest, resolver

- Class/registry: core/strategy/standard_registry.py:14-38; manifest/version validation :109-129; config/strategies/strategy-manifest.v1.json:1-347.
- Manifest enabled는 S1~S9 모두 true(:6-316). 이는 시작 기본값이지 runtime toggle의 영속 저장이 아니다.
- Factory의 ExecutionMultiLegResolverRegistry는 :278-280, resolver 정의/등록 :282-505. S1~S9 별도 resolver가 있고, 반복되는 proposal/tag/side 분기와 open-lot close-plan dispatch가 있다. 완전히 공통인 전략 불문 resolver는 아니다.
- build_pair_plan은 core/strategy/multi_leg_plan.py. 전략별 builder: S2 track2_asymmetric_trap.py:123-191; S5 track5_gap_divergence.py:410 이후; S6 track6_daily_tail_insurance.py:143-149; S7 track7_volatility_skew_weekly_insurance.py:127-141; S8 track8_macro_regime_monthly_strangle.py:163-166; S9 track9_event_overnight_insurance.py:291-315.
- Signal과 실제 주문은 다를 수 있다. Proposal/Plan/ExecutionReport/Position 경계를 따라야 한다.
- verification/current_strategy_replay.py:20-82는 한 번에 전략 하나를 실행하고 aggregate counters/last tick/execution IDs만 출력한다. 신호·거절 사유·주문·체결·lot·손익의 이벤트별 자료를 출력하지 않아 Golden baseline exporter로는 부적합하다.

## 3. ON/OFF 현황

- core/strategy/orchestrator.py:42-56에서 enabled는 manifest definition, entry_enabled/exit_enabled는 true로 초기화된다. setter/getter :59-89.
- 전체 enabled=false면 run()이 전략 evaluate를 건너뛴다(:143-149). 따라서 기존 보유 포지션의 exit 평가도 멈출 수 있고, 자동 청산은 이 코드에서 확인되지 않는다.
- 진입/청산 분리는 proposal tag/reason 문자열의 ENTRY/OPEN 또는 EXIT/CLOSE/UNWIND/FLATTEN/TAKE_PROFIT/STOP_LOSS/TIMEOUT 분류(:91-116)에 의존한다. UNKNOWN은 두 toggle에서 걸러지지 않는다.
- UI 컨트롤 존재: interfaces/control_tower/web/index.html:313-320; USE/ENTRY/EXIT 체크박스와 handler: interfaces/control_tower/web/app.js:110-128, :349-361.
- UI→API: app.js → /api/strategy/control; server.py:166-182 → application/control_tower_hub.py:58-87 → application/strategy_hub/hub.py:25-41 → orchestrator setters.
- 영속 저장: runtime toggle은 orchestrator object의 dict에 저장된다. 조사한 호출 경로에 저장/재로드는 없으며 재생성 시 manifest enabled와 entry/exit=true로 초기화된다. 재시작 유지 기능은 확인되지 않았다.
- 실제 브라우저 DOM toggle은 이번 읽기 전용 조사에서 테스트하지 않았다. 소스 연결은 확인했으나 UI E2E는 BLOCKED.
- EXIT 비활성화는 EXIT로 분류된 신호를 필터링하고, 전체 비활성화는 evaluate 자체를 멈춘다. 포지션 자동청산 여부는 별도 supervisor 경로까지 확인되지 않아 BLOCKED.

## 4. 공통화 후보 및 중복

- A: S6/S7/S8/S9는 보험형 PUT/CALL pair와 watermark/trailing 패턴을 공유. S2는 multi-leg와 P&L ratio trailing 측면에서 근접하지만 4-leg trap과 analytics entry gate가 달라 동일화하면 안 된다.
- B: S1/S4는 Futures hedge/rebalance, S5는 Option+Futures와 Futures-first non-terminal exit. 종료 semantics를 강제로 동일화하지 않는다.
- C: S3는 spread Z-score, 비용/수익, 최대 보유 tick 기반의 통계 전략.
- Resolver 중복: automated_virtual_runtime_factory.py:282-501의 resolve_track1~9. 공통 open-lot close builder를 재사용하지만 strategy별 tag/side/entry plan 분기가 별도다.
- Trailing 중복: S2/S3/S4/S5/S6/S7/S8/S9. 파라미터 의미가 다르다: S2 0.85/0.88/0.90 P&L retention; S3/S4 유사 tier; S6 1.5×/2.0× activation + 0.85/0.88/0.90 floors; S7 20% drawdown; S8 85% retention; S9 30% giveback. 공통 함수화 시 원래 기준을 별도 보존해야 한다.

## 5. 귀속/netting 한계

- Strategy ID/version은 proposal/plan 및 registry key (strategy_id, version)에 사용된다: core/strategy/registry.py:16-37; standard_registry.py:25-38. Resolver close-plan에 strategy ID도 전달한다.
- 각 전략의 실제 order→fill→lot→P&L까지 전수 추적하지 않았으므로 모든 계층의 strategy_id 보존 및 Strategy Trade P/L과 Account P/L 분리는 BLOCKED.
- close-plan builder는 application/composition/virtual_multi_leg_execution.py에 있고 factory :378, :394, :407, :424, :436, :454-465, :484에서 호출된다. 동일 종목 다중 전략 netting/account exposure 처리는 이번 읽기 전용 조사로 완전히 확인되지 않아 BLOCKED.
- 기존 Q&A No.1138에는 Virtual bridge probe 두 번 모두 routed/fill 0, 두 번째 GROUP_RISK_PREFLIGHT_REJECTED로 기록되어 있다. unit test PASS를 실제 Virtual E2E PASS로 확대 해석하지 않는다.

## 6. PRESERVE 목록

| 항목 | 코드 근거 | 처리 |
|---|---|---|
| S6 premium_spent 기반 보험가치 프록시 | track6_daily_tail_insurance.py:151-187; manifest :225-228 | 현 동작 보존, authoritative multiplier 기반 가치와 동일시 금지 |
| S6 UPDATE_TRAILING 비교 | track6_daily_tail_insurance.py:173-187 | 상태 갱신 후 비교로 반환 조건이 항상 false로 보임; 수정 금지 |
| S8 UPDATE_TRAILING 비교 | track8_macro_regime_monthly_strangle.py:116-129 | 상태 갱신 후 비교로 반환 조건이 항상 false로 보임; 수정 금지 |
| S8 DTE≤4 | track8_macro_regime_monthly_strangle.py:155-161 | HOLD_LONG_ATTACK NON_EXECUTION, 강제청산 아님 |
| S4 Basecamp | track4_gamma_scalping.py:83-92 | BASECAMP_BUILD NON_EXECUTION, 주문 아님 |
| S9 대표 신호와 pair close | track9_event_overnight_insurance.py:270-315; factory :477-491 | signal/plan 분리, SELL은 open-lot 기반 |
| S5 Futures-first | track5_gap_divergence.py:203-295 | 비종료 hedge exit 순서 보존 |
| S1 DTE cutoff | track1_tail_defense.py:163-172 | fence 관리 의미 보존 |
| S2/S3/S7/S9 pending lifecycle | S2 :92-120; S3 :93-105,:315 이후; S7 :58-66,:127-143; S9 :81-94,:291-315 | 요청/plan 생성만으로 종료 상태를 확정하지 않음 |

## 7. 명세 차이와 BLOCKED

- Strategy Specification v1.0은 현재 활성 기준문서다. 이 매핑은 실제 resolver가 signal보다 open-lot 잔여수량을 기준으로 close plan을 구성하는 경우 그 코드를 기준으로 기록했다.
- S6/S8 UPDATE_TRAILING 조건은 코드상 문제 의심점이며 이번 작업에서 고치지 않았다.
- strategy_id 문자열은 TRACK1 대문자, track2 소문자, Strategy_3_StatArb, track4~9 소문자로 서로 다르다. 호출자는 문자열을 임의 정규화하지 말아야 한다.
- Golden baseline: BLOCKED. 기존 current_strategy_replay.py는 이벤트별 결과를 내보내지 않으며, 새 exporter 생성은 지시에서 금지됐다. 따라서 가짜/불완전 golden JSON이나 MANIFEST를 생성하지 않았다.
- 실제 ON/OFF DOM 동작, 전략별 NON_EXECUTION 목록의 완전성, end-to-end strategy_id 귀속, 동일 종목 netting은 명시한 범위에서 BLOCKED다.
