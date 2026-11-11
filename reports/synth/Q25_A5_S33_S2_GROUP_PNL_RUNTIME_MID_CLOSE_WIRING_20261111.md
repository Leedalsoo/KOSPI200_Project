# Q25 A5 S33 ? S2 group PnL / Runtime close wiring (2026-11-11)

## Scope and safety

- Approved scope: S2 validation-only code, tests, Virtual Runtime/OMS wiring.
- Explicit exclusions: KIS Live, REAL_VTS, real account, real order, and external API calls.
- Worktree: `Q25_A5_S22_S5_GROUP_CLOSE_20261109`.
- Branch: `q25-a5-s22-s5-group-close-20261109`.
- Base HEAD: `1ea0129131370109344548827780a1e15b2ab414`.
- No commit or push performed. Existing dirty and untracked files were preserved.

## Implemented in this slice

1. `VirtualMultiLegExecutionBridge._is_terminal_execution_plan` now recognizes S2 `TRAP_CLOSE` as a terminal group-close plan.
2. S2 option-group marks use BID/ASK MID rather than requiring LAST. Each leg snapshot retains BID, ASK, quote timestamp, and `BID_ASK_MID` mark provenance.
3. Track2 group snapshots now carry separate `fees`, `slippage`, `net_pnl`, `initial_net_premium_received`, and `quote_freshness_verified` evidence fields. The initial net premium denominator is populated only for a complete four-leg group. Fee evidence is populated only when every filled execution report provides it.
4. Slippage and quote-freshness verification remain explicitly unknown; `net_pnl` and `quote_freshness_verified` therefore remain unset. No zero-cost or freshness assumption is introduced.
5. Runtime tick processing refreshes Track2 group marks and passes the snapshot to `Track2AsymmetricTrap`. The strategy requires complete four-leg MID evidence, costs, freshness verification, and all three exit-policy values before it can emit a close signal.
6. Production stop-loss, trailing-activation, and trailing-pullback ratios remain unset. Tests inject test-only values solely to verify that a triggered `TRAP_CLOSE` signal resolves to the existing four-leg open-lot close plan.
7. The close plan is routed through the Virtual Multi-Leg bridge's terminal group accounting path. No external order API is used.

## Verification

- 115 passed across 12 targeted S2/runtime/adjacent regression test files.
- `compileall` PASS for the four modified Python modules.
- `git diff --check` PASS.
- The new tests cover MID marking, quote provenance, missing/crossed quote fail-closed behavior, four-leg close-plan construction, terminal close classification, strategy exit-policy blocking, and Runtime tick wiring.
- This is implementation/plumbing evidence, not a PSB PASS or natural-signal E2E.

## KIS VTS source evidence

- Raw source: `data/kis_market_data_restart/20261021/kis_vts_websocket_raw.jsonl`.
- SHA-256: `54cf62fa97f07384b55536fb433f239851acc67f372b41d062705234bbd3e252`.
- Manifest record count: 137,319.
- TR IDs in this partition: `H0IOASP0`, `H0UPCNT0` only.
- Four option quote payloads carry source time `133813` (13:38:13 KST); their receive timestamps are around 13:38:16 KST. The four BID/ASK pairs match the supplied values:
  - PUT 877.5: 35.90 / 39.05
  - PUT 882.5: 38.15 / 41.75
  - CALL 887.5: 39.20 / 41.25
  - CALL 892.5: 36.70 / 38.40
- The partition contains no `H0IFCNT0` futures trade frames. The current Track2 analytics provider needs the futures observations for its basis/volume/POC inputs; therefore this partition alone cannot produce a natural S2 signal. No API call was made to fill the gap.

## Remaining blockers

- U16: max 3 retries and 120-second total processing limit are approved; BID/ASK limit pricing is approved. Retry interval and repricing timing remain unresolved. Repair/retry/flatten execution is not yet implemented.
- U18: MID mark, initial group net premium denominator, and fee/slippage inclusion are approved. Numeric stop-loss and trailing-pullback ratios remain unresolved. Fee/slippage source evidence is incomplete, so net PnL stays blocked.
- U19: broker/exchange positions are authoritative and the execution ledger is supplementary. Durable persistence and mismatch resolution/restart procedure are not implemented.
- U21: conservative fallback is selected, but maximum quote age, maximum spread/unit, fallback formula/priority, and tick rounding remain unresolved. The current MID mark records timestamps but does not assert freshness.
- U17: four contract identities, monthly expiry `20261112`, and multiplier `250000` are resolved; current tradability and volatility-boundary evidence remain unverified.
- Natural-signal four-leg Runtime E2E and Replay parity remain unrun.

## Verdict

`PSB_UNVERIFIED` remains. This slice connects part of the group-PnL/close plumbing and verifies fail-closed behavior; it does not authorize or perform real orders, Live/REAL_VTS access, or external API calls.


## Graphify

- `graphify update .` refreshed `graphify-out/graph.json` and `GRAPH_REPORT.md` after the S33 code changes.
- The new `.update_group_pnl_snapshot()` method is present in the graph. An undirected 4-hop path from `process_pending_multi_leg()` to `.update_group_pnl_snapshot()` was confirmed.
- Graphify returned one parser warning for `application/composition/virtual_composition_root.py` at line 54. `py -m py_compile application/composition/virtual_composition_root.py` passes; this is an extractor warning, not a Python syntax failure.
