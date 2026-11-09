SSOT: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 적용 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09

# Q25 A5 S23 S5 StrategyHub-owned Runtime Integrated E2E (2026-11-09)

## 판정

`PSB_PASS_VALIDATION_ONLY_SYNTHETIC_STRATEGYHUB_RUNTIME_FAST_DETAILED_PARITY`

`HighSpeedVirtualRuntimeReplayRunner`의 실제 StrategyHub-owned loop에서 S5 active-position seed를 복원하고 2개 synthetic market tick을 재생했다. Track5 전략이 underlying index 기준으로 자연 청산 신호를 생성했고, Risk → OMS/StandardOrderRouter → VirtualExecutionEngine → VSSF → PositionLot/PositionGroup 경로에서 청산을 완료했다. FAST/DETAILED 의미 결과가 동일하다.

## Runtime 결과

| 항목 | FAST | DETAILED |
| --- | --- | --- |
| Replay events | 2 | 2 |
| Track5 signals | 1 | 1 |
| Risk approved / routed / filled | 1 / 1 / 1 | 1 / 1 / 1 |
| Rejected | 0 | 0 |
| Execution ID | EXEC-000002 | EXEC-000002 |
| Close price | 42.25 | 42.25 |
| Simulator fee | 0.0 | 0.0 |
| Open lots after close | 0 | 0 |
| Track5 active after close | False | False |
| VSSF positions after close | empty | empty |

- FAST group: `S5-S23-STRATEGYHUB-FAST`; leg: `OPTION_EXIT-58d495bdfce0`.
- DETAILED group: `S5-S23-STRATEGYHUB-DETAILED`; leg: `OPTION_EXIT-58d495bdfce0`.
- VSSF `ExecutionReport` now preserves command `group_id` and `leg_id` through execute/query/cancel. DETAILED trace verified that the raw report group/leg IDs exactly match the routed order command.
- DETAILED observer: 1 order command / 1 execution report / 1 canonical fill; `trace_write_errors=[]`.
- StrategyHub Track5 runtime status: 1 execution signal, 1 approved, 1 routed, 1 filled, 0 unavailable, 0 runtime failures.

## Correctness fixes included

1. `track5_analytics_provider.py`: `price.last` for Track5 now comes from `data.underlying_price`; it no longer gets shadowed by the common option-premium `price.last` metric. Missing underlying price remains `UNAVAILABLE`, with no fallback to option premium.
2. `standard_runtime_input_provider.py`: Track5 `CommonStrategyInput.current_price` now uses the underlying index price and becomes `None` when the underlying price is missing; it never falls back to the option premium.
3. `vssf_execution_adapter.py`: canonical reports from VSSF retain command `group_id`/`leg_id` on execute, query and cancel. The DETAILED trace now confirms those identifiers.

## Validation-only inputs and boundaries

- KIS anchor source code: B01611887; Standard CALL; strike 887.50; expiry 20261112; multiplier 250000.
- KIS expiry evidence SHA-256: `DC100CD8D218A2FDE77406D4761C0ACCE617F3D5088C0D951796CE7F9595234F`.
- Linked KIS Master SHA-256: `EFB5B80BE190971EEA41A73F20573E7F4A4B33CAEABF1FC47CA8298A315E43EB`.
- Runtime identity is a validation-only alias `SYNTHETIC_CONTRACT:S5:20261112:CALL:887.50`; it is not promoted to a production Standard instrument ID.
- The seed fill and Track5 lifecycle state are synthetic validation fixtures, not historical executions/state. Replay ticks, option quotes, execution price and fee are synthetic, not subsequent KIS observations.
- The harness uses an active-position-only `SeedOnlyTrack5ContractSource` and synthetic freshness verdict because the operational S5 quote-freshness policy remains unset. This shim is test-only; it does not enable entry selection or production quote freshness.
- `CURRENT_EXECUTION_POLICY_APPROVED=False`, `runtime_config_verified=False`, `risk_limits_available=False` remain unchanged. New S5 entry remains BLOCKED.
- `stats.z_score` is unavailable in this synthetic fixture because active volatility is zero; the tested active-position exit path consumes the underlying `price.last` and does not enable new entry.
- No KIS API, REAL_VTS API, Live API, account API, or external order was used. `production_runtime_eligible=false`.

## Artifacts and hashes

- Runner: `verification/run_q25_a5_s23_s5_strategyhub_runtime_replay_20261109.py`
  - SHA-256: `31682B8729159AB99080DACD712CEBC5716323C6E1DD9996E081C634025AE2DD`
- Result: `reports/synth/Q25_A5_S23_S5_STRATEGYHUB_RUNTIME_REPLAY_20261109_RETRY13.json`
  - SHA-256: `D8D640691451308C3DC5ECFFFC0996C726D8926A47E49B963831C4E711F7344B`
- DETAILED trace: `reports/synth/traces/Q25_A5_S23_S5_STRATEGYHUB_DETAILED_TRACE_20261109_RETRY13.jsonl`
  - SHA-256: `B40B0E8D72D5909CC643B3829EDD84672DF3ED51D2DB35BEC5FCAB09D944C7E6`
- Source seed manifest/events SHA-256: `E78C608216B6D08FF06AD1C6E59DDD4E5BFB8F5F5C239872104FAE81AB6F89FD` / `7E7AF03974C7FD1CB7A7B1AB1C185088A370711757F432D6BE959F3EB4095008`.
- FAST seed manifest/events SHA-256: `B42F1354B32FAF97FD76274A36FB1BAD557E10085B4A3FFE0DF4FD61A0E05F14` / `46C9AC69714BFF1B48600D4218E7E3AB0D70258F8D9BBC1ADAA3B0D272B846A8`.
- DETAILED seed manifest/events SHA-256: `1D64AFAC7B83452529225E38016DCE3B8197D89EBB825F81BEDC586A0285584A` / `DDDAAADCD6FE43D323ED819E9121E587690F01372F0307CD2D3DB55A102B1588`.
- FAST replay manifest/events SHA-256: `0AE16E96C4DE3FB63C895C6E05F1AEF9FABFF2115AF588E670BEE070AEA365A0` / `2E08DB90131CF23EA99BDC0CA3A24F29B221D03FD9352AF02E93BB7C3107C8B5`.
- DETAILED replay manifest/events SHA-256: `7B5198677E9B76629ADA41262F51D52DAD2D28DB1BA386E6C671C55F114A5C49` / `C649C4542F99FC180EF8E230FF2177A2B4F05059F8C4A19640737BEFDB78CCF7`.

## Tests and graph

- Targeted regression suite: `51 passed in 1.27s` (including no-fallback check when underlying price is missing).
- `py_compile`: PASS.
- `git diff --check`: PASS.
- Graphify update/query: PASS; graph has 7,385 nodes / 21,054 edges / 385 communities. Query located Track5 analytics and VSSF metadata changes.
- Existing Graphify warnings remain: `application/composition/virtual_composition_root.py` syntax warning at line 54 and 29 no-symbol files.

## Git and safety

- All source changes and generated artifacts are in isolated worktree `q25-a5-s22-s5-group-close-20261109`.
- Original workfolder dirty count remains 224; no original files were modified.
- Commit `575712b875965eb7f16c91fd1b4aced00758d691` pushed non-force to `cleanup/p2-quarantine-20261026`; remote SHA verified identical.
- Earlier S21/S23 diagnostic reports and retry outputs remain untracked and were excluded from this commit; the committed final runner, source seed, FAST/DETAILED datasets, result, trace, and report are complete.