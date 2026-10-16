> 산출물 역할 정정 (2026-10-12): 이 보고서는 현 코드의 관찰 사실과 위험 후보를 기록하는 보조 조사 자료다. 사용자가 요구한 주 설계표는 docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.2.md이며, 동일 판단요소를 행으로 두고 Strategy 1~9를 열로 통합한다. 이 문서의 코드 관찰은 목표 설계·승인이 아니다.
# Strategy 1~9 신규 명세 통합 검토 보고서 v0.1

- 상태: **검토 초안 / 미승인**
- 날짜: 2026-10-12
- 기준 branch/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 범위: 신규 명세 9개, 통합 비교표, 현 전략 코드 및 실행 resolver의 정적 대조
- 제한: 전략 코드 테스트/시뮬레이션은 실행하지 않았으며, 본 보고서는 정적 코드 검토와 문서 품질 확인이다.

## 1. 검증 결과 요약

| 검증 영역 | 판정 | 근거 |
|---|---|---|
| 초안 파일 존재 | PASS | S1~S9 명세와 통합표 10개 파일 확인 |
| 문서 인코딩/기본 형식 | PASS | UTF-8 읽기, 문서 상태 및 BLOCKED 표기, trailing whitespace 검사 |
| Notion 기록 | PASS | No.1197~No.1206 페이지를 생성하고 내용/핵심 문구를 다시 조회 |
| 현재 코드 연결 경로 | PASS(초기 매핑) | 전략 파일, runtime input/analytics, resolver/plan adapter, MultiLegBridge 경계 확인 |
| 기존 테스트 참조 목록 | PASS(목록 확인만) | tests/strategy 및 tests/unit에서 S1~S9 관련 테스트 파일을 찾음 |
| 전략 의도 완전성 | BLOCKED | 사용자 최종 목적/레그 역할/손실 한도/시간 경계가 미확정 |
| 상태 전이·partial-fill 시나리오 완전성 | BLOCKED | 설계 초안에 포함했으나 실제 전이표와 모든 조합 검증은 미완료 |
| 기존 코드 의미 검증 | FAIL(정적 코드에서 문제 발견) | S3의 같은 Futures identity 반대방향 동일수량 leg, S8의 macro add-on resolver 불일치 및 trailing signal 억제 |
| 자동화 테스트/시뮬레이션 | NOT RUN | 이번 단계는 명세 문서 작성/정적 검토이며 코드를 수정하지 않음 |
| 구현 승인 | BLOCKED | 사용자 승인 전 |

## 2. 전략별 정적 검토 판정

| 전략 | 판정 | 현재 확인된 주요 쟁점 |
|---|---|---|
| S1 Tail Defense | BLOCKED | 첫 평가 가격을 기준가격으로 사용; 변동성 fence distance와 최초 strikes 계산 불일치; 3개 option leg 중 내부 상태가 한 leg만 추적; DTE close 전 flat 확인 없음; duplicate method/state code |
| S2 Asymmetric Trap | BLOCKED | stop/trailing은 실제 option-pair P&L이 아닌 underlying return proxy; entry state가 fills 전에 active; expiry policy 미정; 종료 후 short-switch timer 잔존 가능 |
| S3 Statistical Arbitrage | FAIL(정적 설계 문제) | Track3MultiLegExecutionPlanAdapter가 동일 Futures identity를 강제하고 동일 qty의 반대방향 leg 2개 생성; 순노출 상쇄 가능. _exit_pending 분기에서 regime 할당 전 regime 참조 |
| S4 Gamma Scalping | BLOCKED | basecamp는 NON_EXECUTION인데 hedge가 basecamp/실제 option position 확인 없이 실행 가능; hedge target qty가 fill 전 state에 반영; trailing은 Futures만 닫음 |
| S5 Gap Divergence | BLOCKED | session start price는 첫 관측 tick; fixed Futures qty=5; 30회 evaluate count는 시간과 다름; actual option P&L/expiry policy 미정; partial-fill recovery 세부 규칙 필요 |
| S6 Daily Tail Insurance | BLOCKED | entry state가 fill 전 active; intrinsic proxy 산식이 실제 option mark/multiplier와 다름; partial pair/expiry/cutoff 복구 필요 |
| S7 Weekly Volatility Skew Insurance | BLOCKED | 전략 평가에서 IV skew가 trigger로 쓰이지 않음; expiry format 정규화 위험; quantity>1일 때 mark value에 quantity 미반영; entry state가 fill 전 active |
| S8 Macro Regime Monthly Strangle | FAIL(정적 설계 문제) | MACRO_HEDGE_SCALE_UP도 full pair entry plan으로 resolve됨; high-watermark를 먼저 업데이트해 UPDATE_TRAILING 비교가 억제됨; premium_spent/exact expiry가 state에 충분히 반영되지 않음 |
| S9 Event Overnight Insurance | BLOCKED | entry는 15:10 이후 조건만 확인하고 official close 이후를 명시적으로 차단하지 않음; 한쪽 leg만 체결된 경우 overnight recovery 정책 없음; exact expiry state 없음 |

FAIL 표기는 현재 코드/실행계획의 정적 설계 문제를 뜻하며, 해당 주문 경로를 실제 실행해 실패를 관찰했다는 의미는 아니다.

## 2.1 Strategy 1 추가 소스 경계 검토

Strategy 1 직접 코드 외에 Track1RuntimeInputProvider, StandardRuntimeInputProvider, RuntimeStrategyToDecisionAdapter, ExecutionMultiLegResolverRegistry, resolve_track1, PositionLotProvenance, VirtualMultiLegExecution의 close-plan 경계 및 기존 Strategy 1 테스트를 추가 확인했다.

- OPTION proposal에 대해 resolve_track1은 MultiLegExecutionPlan을 반환하지 않는다. RuntimeStrategyToDecisionAdapter는 resolver가 None이면 SINGLE_ORDER plan으로 fallback한다. 따라서 최초 CALL/PUT/PUT은 grouped strategy plan이 아닌 세 개의 단일 주문으로 처리될 수 있다. 만기 청산 후보도 같은 fallback 경로를 사용한다.
- Track1RuntimeInputProvider는 Strategy ID와 instrument identity 존재 여부로 lots를 필터링할 뿐 Option/Futures identity type을 구분하지 않는다. short_target은 모든 SELL lots를 합산하고 delta lookup은 각 SELL identity의 expiry/option_type/strike를 읽는다. 같은 전략에 Futures SELL lot이 섞이면 Option 전용 identity 필드 접근 또는 잘못된 delta source 조회가 발생할 수 있다.
- Futures hedge entry 신호 생성 전에 active_hedge, entry price, quantity, daily count가 설정된다. on_execution_result는 FUTURES_UNWIND만 처리하므로 Futures entry reject/partial/unknown에 대한 상태 대사가 빠져 있다.
- coverage_ratio, profit_target, profit_buffer는 Track1Input/state에 존재하지만 현재 evaluate 경로에서 전략 판단에 사용되지 않는다.
- tests/strategy/test_strategy1.py는 첫 3개 option signal과 missing delta 시 Futures hedge 차단을 확인한다. tests/strategy/test_strategy_contract_safety.py는 missing/empty market state 및 unchanged-price case를 다룬다. resolver의 SINGLE_ORDER fallback, grouped fills, partial/cancel-race, DTE close 후 flat, Futures entry reject reconciliation은 이 테스트에서 확인되지 않는다.

이 발견은 정적 소스 검토 결과다. 실제 주문 경로/런타임을 실행해 재현한 결과가 아니며, 코드 수정 승인도 아니다.
## 3. 코드 및 테스트 참조

### Strategy source / resolver
- S1: core/strategy/track1_tail_defense.py; track1_runtime_input_provider.py; resolve_track1.
- S2: core/strategy/track2_asymmetric_trap.py; track2_execution_plan_adapter.py; resolve_track2.
- S3: core/strategy/track3_statistical_arbitrage.py; track3_multi_leg_execution_plan_adapter.py; resolve_track3.
- S4: core/strategy/track4_gamma_scalping.py; Greeks provider; resolve_track4.
- S5: core/strategy/track5_gap_divergence.py; Track5 contract/runtime sources; resolve_track5.
- S6: core/strategy/track6_daily_tail_insurance.py; Track6OptionContractSource; resolve_track6.
- S7: core/strategy/track7_volatility_skew_weekly_insurance.py; Track7OptionContractSource; resolve_track7.
- S8: core/strategy/track8_macro_regime_monthly_strangle.py; resolve_track8.
- S9: core/strategy/track9_event_overnight_insurance.py; Track9 ATM IV/Option Master sources; resolve_track9.
- Common: core/strategy/strategy_execution_proposal.py; core/strategy/multi_leg_plan.py; MultiLegBridge; PositionLotStore; contract identity/expiry and execution result read models.

### Existing test files found (not executed)
- S1: tests/strategy/test_strategy1.py; tests/strategy/test_strategy_contract_safety.py.
- S2: tests/strategy/test_strategy2.py; tests/strategy/test_strategy_configuration_contract.py; tests/strategy/test_strategy_contract_safety.py; tests/unit/test_runtime_unified_execution_plan.py.
- S3: tests/strategy/test_strategy3.py; tests/strategy/test_strategy_configuration_contract.py; tests/strategy/test_strategy_contract_safety.py.
- S4: tests/strategy/test_strategy4.py; tests/strategy/test_strategy_configuration_contract.py; tests/strategy/test_strategy_contract_safety.py; tests/unit/test_runtime_unified_execution_plan.py.
- S5: tests/strategy/test_strategy5.py; tests/strategy/test_strategy_configuration_contract.py; tests/unit/test_pending_multi_leg_results_counted.py; tests/unit/test_strategy5_risk_diagnostic_jsonl.py; tests/unit/test_strategy5_risk_diagnostic_virtual_runtime.py; tests/unit/test_virtual_multi_leg_group_merge.py.
- S6: tests/strategy/test_strategy6.py; tests/strategy/test_s6_engine_candidate.py; tests/unit/test_strategy6_virtual_runtime_integration.py; tests/unit/test_track6_listed_pair_fallback.py; tests/unit/test_strategy_horizon_contract_selection.py; tests/unit/test_virtual_multi_leg_group_merge.py.
- S7: tests/strategy/test_strategy7.py; tests/strategy/test_execution_plan_contract.py; tests/unit/test_strategy7_virtual_runtime_integration.py.
- S8: tests/strategy/test_strategy8.py; tests/unit/test_strategy8_virtual_runtime_integration.py; tests/unit/test_strategy_horizon_contract_selection.py.
- S9: tests/strategy/test_strategy9.py; tests/strategy/test_execution_plan_contract.py; tests/unit/test_strategy9_virtual_runtime_integration.py; tests/unit/test_option_program_execution_provenance.py; tests/unit/test_pending_multi_leg_results_counted.py.

Existing tests are historical evidence only. Their existence or past PASS does not approve new rules or prove conformance to the new specifications.

## 4. Cross-strategy issues that must be resolved before approval

1. Common definition of exact contract identity, expiry, trading calendar, quote freshness, mark/Greeks units and source provenance.
2. Each strategy's purpose, option leg role, Futures alpha/spread/hedge role and ownership boundary.
3. Actual P&L: per-leg fills/marks/multiplier/fees/slippage; replace or explicitly justify underlying/intrinsic proxies.
4. Entry/exit lifecycle for each leg: rejected, partial, unknown, cancel requested, cancel confirmed, fill during cancellation, retry and reconciliation.
5. Strategy-specific maximum premium, maximum loss, margin and account-wide risk/overlap limits.
6. DTE/session/overnight rules and no-reset-before-flat invariant.
7. Resolver conformance: every proposal must produce exactly the intended plan purpose, asset identity, legs, sides and quantities.
8. State persistence/restart recovery and prevention of duplicate signals/orders.
9. Decision boundary: No.1131 says architecture work must not silently alter the investment thesis. Fresh drafts are authorized; any change to the underlying thesis must be surfaced as a separate decision.
10. No.1151 requires capital/margin/transaction cost review and forbids blanket Futures removal or same-quantity Futures-to-Option substitution.

## 5. Required next verification steps

1. Confirm original intent and leg role for each strategy, starting with S1.
2. Resolve D1–D17 in each strategy draft and add approved numeric formulas/units where applicable.
3. Produce a shared state transition matrix for every order/fill/cancel/expiry/restart state.
4. Create a per-leg table for each strategy with exact identity, side, quantity, role, entry/exit, risk and recovery.
5. Review all resolver outputs against proposal intent, especially S3 and S8.
6. Map every requirement to source boundary and new test IDs; do not inherit old test expectations blindly.
7. Run scenario simulation and relevant automated tests only after the specification is coherent and the user approves the implementation scope.
8. Obtain explicit approval of a versioned specification before strategy code changes.
9. Do not commit/push strategy or design changes before the required approval.

## 5.1 Shrimp Resume Context 확인

- Remote Desktop Commander에서 실제 원격 프로세스 목록을 확인하고, My_Caddy_Powershell에서 command lookup 및 Docker container image/command/label을 검색했다.
- Shrimp Resume Context를 확실히 식별하는 실행 프로세스/명령/컨테이너 또는 전용 도구가 확인되지 않았다. 검색에 잡힌 powershell 프로세스는 조회 명령 자체였다.
- 따라서 Shrimp Resume Context는 **갱신하지 못함(BLOCKED)**. 실제 갱신 여부를 검증할 수 없으므로 업데이트했다고 보고하지 않는다.
## 6. Final status

- Drafting S1~S9 and the integrated table: **PASS (draft creation only)**.
- Document basic quality checks: **PASS**.
- Semantic completeness/contradiction verification: **BLOCKED**, with confirmed static design issues documented.
- Code tests/simulation: **NOT RUN**.
- Strategy implementation: **NOT STARTED**.
- Commit/push: **NOT PERFORMED**.
- Next approval: not needed to continue drafting; required before implementation or strategy/design commit/push.