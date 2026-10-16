# Worktree Change Audit — 2026-10-14

Status: report-only inventory; no files in this list were deleted or reverted by this audit.

## Summary
- Tracked modified paths: 55
- Untracked files (using git status --untracked-files=all): 149
- Total file-level status entries: 204
- No.1253 historical count (48 modified / 17 untracked) does not match current inventory. Earlier plain git status hid contents under untracked directories; file-level inventory now lists all nested files. Exact provenance of older untracked files is not established.
- Local HEAD and origin/Project200 both equal 3179d80c0f0d7ba0a74120740e23132e80b1aa7b; no merge/rebase/pull/reset/stash performed.

## High-risk review outcome
- Strategy logic: core/strategy/track5_gap_divergence.py; core/strategy/track7_volatility_skew_weekly_insurance.py; tests/strategy/test_strategy5.py. No current approved replacement strategy spec was confirmed for these exact diffs. User judgment required; no edits/reverts made by this directive.
- Order/virtual execution: application/composition/virtual_multi_leg_execution.py; application/composition/virtual_runtime_data_provider.py; contracts/canonical_order_transport.py; core/oms/option_identity_resolver.py; core/runtime/reference_execution_pipeline.py; environments/high_speed/synthetic_runtime_sources.py; environments/virtual/broker/virtual_broker.py; environments/virtual/broker/virtual_broker_api.py; environments/virtual/execution/order_intent_adapter.py; environments/virtual/execution/vssf_command_context_provider.py; environments/virtual/market/simulator_runtime.py; verification/e2e_virtual_exchange_broker_strategy_position_pnl_control_tower_20261009.py. Existing diffs are preserved; current approval scope is not proven file by file.
- S3/S4 manifest: current manifest has all nine enabled=true. This conflicts with Directive F expectation S3/S4 enabled=false and capital_gate_min=null. The capital_gate_min key is absent (not explicitly null) in all manifest entries. Manifest was not changed because strategy settings are out of scope.
- Data/reference changes: No.1171/No.1244 and No.1250-1254 support KIS-only source policy and exact expiry, but the existence of a diff does not establish that all adjacent strategy/OMS changes were approved.

## File-level inventory
| Git status | File | Area | Change summary | Notion/approval evidence |
|---|---|---|---|---|
| MODIFIED | application/composition/market_calendar_hub.py | Reference data/identity/calendar/subscription | tracked diff +6 / -8 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | application/composition/option_master_factory.py | Reference data/identity/calendar/subscription | tracked diff +24 / -3 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | application/composition/track2_option_contract_source.py | Strategy analytics/source adapter | tracked diff +8 / -1 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | application/composition/track5_option_contract_source.py | Strategy analytics/source adapter | tracked diff +7 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | application/composition/track7_option_contract_source.py | Strategy analytics/source adapter | tracked diff +11 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | application/composition/track8_option_contract_source.py | Strategy analytics/source adapter | tracked diff +7 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | application/composition/virtual_multi_leg_execution.py | Order/execution/risk/virtual runtime | tracked diff +16 / -18 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | application/composition/virtual_runtime_data_provider.py | Order/execution/risk/virtual runtime | tracked diff +3 / -2 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/canonical_order_transport.py | Order/execution/risk/virtual runtime | tracked diff +5 / -0 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/external_authoritative_option_identity_record.py | Reference data/identity/calendar/subscription | tracked diff +7 / -0 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | contracts/option_expiry.py | Reference data/identity/calendar/subscription | tracked diff +5 / -1 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | contracts/option_identity_source_port.py | Reference data/identity/calendar/subscription | tracked diff +6 / -0 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | contracts/track2_option_iv_source.py | Strategy analytics/source adapter | tracked diff +8 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/track6_volatility_source.py | Strategy analytics/source adapter | tracked diff +8 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/track9_iv_event_materializer.py | Strategy analytics/source adapter | tracked diff +12 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/track9_iv_timeseries.py | Strategy analytics/source adapter | tracked diff +8 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | contracts/types.py | Other/runtime | tracked diff +8 / -0 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | core/oms/option_identity_resolver.py | Reference data/identity/calendar/subscription | tracked diff +6 / -1 lines; high-risk scope, not changed by Directive F, not reverted | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | core/option/option_master.py | Reference data/identity/calendar/subscription | tracked diff +360 / -128 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | core/runtime/reference_execution_pipeline.py | Order/execution/risk/virtual runtime | tracked diff +11 / -2 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | core/strategy/canonical_signal_adapter.py | Strategy logic/config | tracked diff +6 / -1 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | core/strategy/track5_gap_divergence.py | Strategy logic/config | tracked diff +8 / -0 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | core/strategy/track7_volatility_skew_weekly_insurance.py | Strategy logic/config | tracked diff +15 / -1 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | environments/high_speed/synthetic_runtime_sources.py | Other/runtime | tracked diff +40 / -35 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | environments/virtual/broker/virtual_broker.py | Order/execution/risk/virtual runtime | tracked diff +5 / -0 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | environments/virtual/broker/virtual_broker_api.py | Order/execution/risk/virtual runtime | tracked diff +6 / -0 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | environments/virtual/execution/order_intent_adapter.py | Order/execution/risk/virtual runtime | tracked diff +5 / -0 lines; high-risk scope, not changed by Directive F, not reverted | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | environments/virtual/execution/vssf_command_context_provider.py | Order/execution/risk/virtual runtime | tracked diff +6 / -1 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | environments/virtual/market/canonical.py | Other/runtime | tracked diff +9 / -0 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | environments/virtual/market/reference_vms_market/canonical.py | Other/runtime | tracked diff +8 / -0 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | environments/virtual/market/simulator_runtime.py | Order/execution/risk/virtual runtime | tracked diff +10 / -2 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | infrastructure/kis/historical_observation_sources.py | Other/runtime | tracked diff +20 / -61 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | infrastructure/kis/holiday_fallback_provider.py | Reference data/identity/calendar/subscription | tracked diff +80 / -97 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | infrastructure/kis/holiday_provider.py | Reference data/identity/calendar/subscription | tracked diff +38 / -2 lines; this run set default auth environment to VTS only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | infrastructure/kis/kis_index_option_master_source.py | Reference data/identity/calendar/subscription | tracked diff +378 / -63 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | infrastructure/kis/kis_rest_market_observation_collector.py | Other/runtime | tracked diff +106 / -8 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | infrastructure/kis/kis_rest_market_observation_normalizer.py | Reference data/identity/calendar/subscription | tracked diff +3 / -3 lines; this run added KIS source Greek keys gama/theta/vega | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | infrastructure/kis/kis_vts_weekday_collector.py | Other/runtime | tracked diff +10 / -1 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | infrastructure/kis/krx_kis_option_identity_resolver.py | Reference data/identity/calendar/subscription | tracked diff +7 / -2 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | infrastructure/kis/track2_option_iv_source.py | Strategy analytics/source adapter | tracked diff +9 / -2 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | infrastructure/kis/track6_atm_volatility_source.py | Strategy analytics/source adapter | tracked diff +5 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | infrastructure/kis/track9_atm_iv_source.py | Strategy analytics/source adapter | tracked diff +5 / -0 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | interfaces/control_tower/server.py | Other/runtime | tracked diff +2 / -2 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | scripts/kis_vts_websocket_collector.py | Other/runtime | tracked diff +92 / -2 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | shared/contracts/canonical.py | Other/runtime | tracked diff +22 / -0 lines | 근거 확인 필요; 변경 보존 |
| MODIFIED | tests/integration/test_high_speed_virtual_runtime_replay.py | Order/execution/risk/virtual runtime | tracked diff +6 / -19 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | tests/integration/test_historical_option_quote_vms_boundary.py | Test | tracked diff +2 / -2 lines | 검증 자산; 테스트 PASS는 전략 구현 승인 아님 |
| MODIFIED | tests/strategy/test_strategy5.py | Strategy logic/config | tracked diff +1 / -1 lines | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| MODIFIED | tests/unit/test_holiday_fallback_provider_priority.py | Reference data/identity/calendar/subscription | tracked diff +72 / -36 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | tests/unit/test_kis_option_master_multiplier.py | Reference data/identity/calendar/subscription | tracked diff +27 / -16 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | tests/unit/test_option_identity_resolver.py | Reference data/identity/calendar/subscription | tracked diff +6 / -2 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | tests/unit/test_option_master_factory.py | Reference data/identity/calendar/subscription | tracked diff +2 / -1 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | tests/unit/test_synthetic_trading_calendar_expiry.py | Reference data/identity/calendar/subscription | tracked diff +4 / -2 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| MODIFIED | tests/unit/test_virtual_position_lot_provenance.py | Test | tracked diff +1 / -1 lines | 검증 자산; 테스트 PASS는 전략 구현 승인 아님 |
| MODIFIED | tests/unit/test_weekly_expiry_by_weekday.py | Reference data/identity/calendar/subscription | tracked diff +10 / -20 lines | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | config/risk/option-hedge-risk.v1.json | Order/execution/risk/virtual runtime | untracked/pre-existing provenance unknown; preserved | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| UNTRACKED | core/risk/option_hedge_risk_config.py | Order/execution/risk/virtual runtime | untracked/pre-existing provenance unknown; preserved | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| UNTRACKED | core/trading_day_calculator.py | Reference data/identity/calendar/subscription | pre-existing untracked file; Directive F appended D-4 11:00 KST helper/tests; no strategy logic | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/00_strategy_1_to_9_draft_index_and_matrix_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/00_strategy_1_to_9_spec_index_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/01_strategy_1_to_9_consistency_review_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s2_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s2_delta_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s5_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s5_delta_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s9_delta_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_s9_delta_v0.6.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.6.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.7.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.8.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v0.9.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v1.0.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v1.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v1.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/02_decision_factor_integrated_design_matrix_v1.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s2_delta_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s2_delta_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s5_delta_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s5_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s9_delta_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_s9_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.6.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.7.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.8.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.9.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s2_delta_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s2_delta_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s5_delta_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s5_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s9_delta_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s9_delta_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.5.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.6.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.7.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.8.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.9.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v1.0.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/06_kis_option_timestamp_vts_freshness_measurement_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/config_schema_integrated_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/cross_strategy_conflict_review_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/decision_log_candidates_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/implementation_order_proposal_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/kis_only_authoritative_data_migration_plan_20261014.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/kis_only_authoritative_data_phaseA_B_evidence_20261014.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/kis_subscription_planner_design_draft_20261014.md | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/kis_type_code_mapping_evidence_draft_20261014.md | Draft documentation | created in Directive F run; draft/evidence only | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/krx_exact_expiry_source_policy_v1.md | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/krx_weekly_identity_and_otp_download_investigation_20261013.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/reference_data_manual_download_guide_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/reference_data_protection_rules_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/reference_data_registry_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategies_1_to_9_integrated_spec_v1.0_draft.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_code_intent_diff_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_code_intent_diff_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_tail_defense_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_tail_defense_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_tail_defense_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_1_tail_defense_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_2_asymmetric_trap_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_2_asymmetric_trap_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_2_asymmetric_trap_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_2_asymmetric_trap_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_2_code_intent_diff_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_3_statistical_arbitrage_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_3_statistical_arbitrage_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_3_statistical_arbitrage_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_4_gamma_scalping_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_4_gamma_scalping_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_4_gamma_scalping_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_5_gap_divergence_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_5_gap_divergence_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_5_gap_divergence_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_5_gap_divergence_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_6_daily_tail_insurance_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_6_daily_tail_insurance_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_6_daily_tail_insurance_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_6_daily_tail_insurance_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_7_weekly_volatility_skew_insurance_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_7_weekly_volatility_skew_insurance_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_7_weekly_volatility_skew_insurance_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_8_macro_regime_monthly_strangle_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_8_macro_regime_monthly_strangle_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_8_macro_regime_monthly_strangle_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_8_macro_regime_monthly_strangle_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_9_event_overnight_insurance_spec_v0.1.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_9_event_overnight_insurance_spec_v0.2.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_9_s1_put_insurance_spec_v0.3.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/strategy_9_s1_put_insurance_spec_v0.4.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | docs/strategy_specifications/trading_day_boundary_table_draft.md | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/trading_day_boundary_table_v2.md | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/trading_day_boundary_table_v3.md | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | docs/strategy_specifications/trading_day_boundary_table_v4.md | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | infrastructure/kis/collector_instance_lock.py | Other/runtime | untracked/pre-existing provenance unknown; preserved | 근거 확인 필요; 변경 보존 |
| UNTRACKED | infrastructure/kis/kis_option_expiry_source.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | infrastructure/kis/kis_subscription_planner.py | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | infrastructure/krx/krx_option_expiry_master.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_holiday_provider_coverage.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_index_option_master_source.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_option_expiry_source.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_option_master_identity_expiry.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_rest_greeks_normalization.py | Test | created in Directive F run; draft/evidence only | 검증 자산; 테스트 PASS는 전략 구현 승인 아님 |
| UNTRACKED | tests/unit/test_kis_rest_request_timing.py | Test | untracked/pre-existing provenance unknown; preserved | 검증 자산; 테스트 PASS는 전략 구현 승인 아님 |
| UNTRACKED | tests/unit/test_kis_subscription_planner.py | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_kis_vts_websocket_timing.py | Test | untracked/pre-existing provenance unknown; preserved | 검증 자산; 테스트 PASS는 전략 구현 승인 아님 |
| UNTRACKED | tests/unit/test_krx_option_expiry_master.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_option_expiry_end_to_end.py | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | tests/unit/test_option_hedge_risk_config.py | Order/execution/risk/virtual runtime | untracked/pre-existing provenance unknown; preserved | 근거/승인 상태 미확정; 과거 Q&A는 이력일 뿐 현재 신규 명세 승인으로 간주하지 않음; 사용자 판단 대기 |
| UNTRACKED | tests/unit/test_trading_day_calculator.py | Reference data/identity/calendar/subscription | pre-existing untracked file; Directive F appended D-4 11:00 KST helper/tests; no strategy logic | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | verification/_tmp_full_same_run_e2e.py | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/baseline/pre_unification_20261010_blocked_quote_failure/BLOCKED_REPORT.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/baseline/pre_unification_20261010_blocked_quote_failure/MANIFEST.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/baseline/pre_unification_20261010_blocked_quote_failure/run_1.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/baseline/pre_unification_20261010_failed_attempt_1_import_path/MANIFEST.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/e2e_pipeline_fresh_20261009.py | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/e2e_pipeline_run_20261009_v2.py | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/e2e_virtual_exchange_broker_strategy_position_pnl_control_tower_20261009.py | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/fo_idx_code_mts_20261014.zip | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_api_capability_probe_20261014.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_dependency_inventory_20261014.csv | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_dependency_inventory_20261014.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_expiry_crosscheck_20261014.json | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | verification/evidence/kis_expiry_generalization_20261014_dda0ee9c.json | Reference data/identity/calendar/subscription | untracked/pre-existing provenance unknown; preserved | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | verification/evidence/kis_holiday_single_probe_20261014.json | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | verification/evidence/kis_master_identity_join_20261014.json | Evidence/cache/data | created in Directive F run; draft/evidence only | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_phaseA_trace_followup_20261014.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | verification/evidence/kis_phaseA_trace_followup_20261014_0130KST.md | Draft documentation | untracked/pre-existing provenance unknown; preserved | 초안/역사적 문서; 사용자 승인 전 구현 기준 아님 |
| UNTRACKED | verification/evidence/kis_strategy_source_trace_20261014.json | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/evidence/kis_subscription_plan_dry_run_20261014.json | Reference data/identity/calendar/subscription | created in Directive F run; draft/evidence only | No.1171 KIS-only, No.1244 exact-expiry, No.1250-1254와 대조; Directive F 범위에는 해당하지만 파일별 기존 변경의 승인 상태는 별도 확인 |
| UNTRACKED | verification/evidence/kis_vts_account_readonly_capability_20261014.json | Evidence/cache/data | created in Directive F run; draft/evidence only | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |
| UNTRACKED | verification/same_run_control_tower_probe.py | Evidence/cache/data | untracked/pre-existing provenance unknown; preserved | 보존 증거/캐시; 삭제·덮어쓰기 금지; runtime authority 아님 unless separately approved |

## Important limits
- This inventory categorizes by path and diff metadata; it is not a semantic approval of every pre-existing diff.
- Related historical items No.1132/No.1134 are context only and do not automatically approve current order/strategy changes.
- No high-risk file was restored, deleted, staged, committed, or pushed.

## Inventory follow-up after audit file creation
- Final status snapshot after this audit file and the two follow-up drafts were created: 55 tracked modified paths and 152 untracked files (207 file-level status entries).
- The 149-untracked inventory table above was captured immediately before creating this audit report. This report itself and the following drafts were added afterward: docs/strategy_specifications/holiday_provider_kis_first_diff_review_20261014.md and docs/strategy_specifications/contract_multiplier_tick_source_proposal_draft_20261014.md.
- No pre-existing untracked files were deleted or normalized to reduce the count.
## Final status after evidence correction
- Current final inventory: 55 tracked modified paths and 153 untracked files (208 file-level status entries); HEAD and origin/Project200 remain identical at 3179d80c0f0d7ba0a74120740e23132e80b1aa7b.
- The additional file beyond the prior 152-untracked snapshot is verification/evidence/kis_subscription_plan_dry_run_v2_20261014.json, which corrects the earlier dry-run record wording about official confirmation of the 41-registration scope. The earlier evidence file remains preserved.

## Final account-evidence follow-up
- A further masked account-configuration evidence file was added after the 153-untracked snapshot: verification/evidence/kis_vts_account_config_check_followup_20261014.json. It stores only boolean format/presence checks and the official source, not the account number or credentials.
- Current final inventory after this evidence file: 55 tracked modified paths and 154 untracked files (209 file-level status entries). No pre-existing files were removed.
