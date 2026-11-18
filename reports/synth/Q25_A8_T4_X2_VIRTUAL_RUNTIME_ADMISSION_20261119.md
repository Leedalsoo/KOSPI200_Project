# Q25 A8 Track 4 T4 — X2 Virtual Runtime admission wiring

- Date: 2026-11-19 (KST)
- Branch: `work/q25-a8-r10-order-lineage-u19-20261118`
- Base HEAD: `bf8315e858c75fce4b96faa59bd2218bd1855178`
- Decision references: No.1534 / No.1535 / No.1538 / No.1554 / No.1555 / No.1566 / No.1546 / Current Baseline v2

## Decision and evidence handling

- No.1534 is mandatory. A data mismatch or missing input is not immediately classified as BLOCKED. Compare the relevant Notion decision and existing Raw/Canonical/manifest/KIS Master/REST/expiry/KRX lineage first; apply crosswalk, independent replay, schema/contract checks or provenance-preserving synthetic fallback.
- Existing observed data and accepted provenance-tracked synthetic/complementary inputs remain eligible for validation under No.1535/1538/1554/K-1. Synthetic evidence is explicitly validation-only and never promoted to KIS/account/broker/Production/Live truth.
- T4 exercised the control boundary with deterministic in-memory synthetic evidence. It did not modify or regenerate Raw/Canonical/accepted datasets, collect new data, or call KIS APIs.

## Implementation

- Added `ValidationOnlyRuntimeStopAdmissionSource`, which overlays the durable X2 latch on the existing `VirtualRiskGuardStatusSource` without duplicating RiskGuard/RiskGate decisions.
- `virtual_session_factory` now creates one `RiskEngine` and injects that exact instance into both X2 and `AutomatedVirtualTradingLoop`/`RiskGate`.
- X2 state is persisted per `run_id` under `%LOCALAPPDATA%/KOSPI200_Project/validation_only_runtime_stop_switch/<sha256(run_id)>.sqlite3`, outside the repository and market-data tree. Reusing the same run ID restores the durable latch.
- The shared Virtual Runtime loop now checks the X2 + RiskGuard + RiskEngine admission state before pending multi-leg processing and before each multi-leg submission. Single-order submission continues through the existing RiskGate with the X2 overlay.
- If X2 is tripped, or RiskGuard/RiskEngine admission is unavailable/blocked, pending/multi-leg/single-order submissions are denied. Strategy cancel requests are not executed while X2 is tripped. A status read or persistence failure raises before further order submission.
- No `RuntimeController.stop()`, broker cancel, liquidation, position flatten, Live/REAL_VTS, account/order API, or collector invocation was added.

## Verification

- Focused X2/X1/Track2/RiskGate/FRESH31/FRESH62/FRESH63/provider-boundary regression: **81 passed / 0 failed**.
- Synthetic T4 integration checks cover shared RiskEngine identity, healthy admission pass-through, X2 durable trip, RiskGate denial, pending/multi-leg submitter suppression, base RiskGuard block, external RiskEngine kill-switch state, and fail-closed status-read/persistence errors.
- `py -m compileall -q` on the four changed runtime modules: PASS.
- Ruff on X2 module + new T4 test: PASS.
- Ruff `--select S110` on `automated_virtual_trading_loop.py`: PASS.
- `git diff --check`: PASS.
- Full-file Ruff on the legacy composition/factory files still reports existing import-order/unused-import findings; broad auto-fix was intentionally not applied to avoid unrelated cleanup.

## Files in T4 commit

- `application/composition/validation_only_runtime_auto_stop_switch.py`
- `application/composition/automated_virtual_trading_loop.py`
- `application/composition/automated_virtual_runtime_factory.py`
- `application/run_hub/virtual_session_factory.py`
- `tests/application/composition/test_validation_only_runtime_x2_virtual_admission.py`
- `reports/synth/Q25_A8_T4_X2_VIRTUAL_RUNTIME_ADMISSION_20261119.md`

## Remaining boundary

- T4 wires the durable X2 latch into the Virtual Runtime order-admission paths. It does not yet build a live per-tick evidence collector that automatically assembles X1 ledger evidence, U19 recovery decision, and market freshness verdict for `X2.evaluate()`. That evidence-provider/supervisor orchestration is the next validation-only integration step.
- No actual market/account authority, contract multiplier, fee/tax/margin/slippage, Production or Live readiness is certified.