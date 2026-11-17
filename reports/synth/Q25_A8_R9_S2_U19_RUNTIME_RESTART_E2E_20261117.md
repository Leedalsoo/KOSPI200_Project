# Q25 A8 R9 — S2 U19 Runtime PositionLot Restart E2E

Date: 2026-11-17
Branch: `work/q25-a8-r9-integrated-e2e-20261117`
Scope: validation-only S2 Runtime → PositionLot/VSSF account position → U19 evidence reconciliation → durable checkpoint reopen.

## Reused inputs and policy boundary

- Reused Accepted Runtime v2 and the existing Q25_A8_P2 market-calibrated four-leg sidecar already materialized in R9. No Raw, Canonical, Accepted, Master, expiry, or source sidecar was changed.
- Followed No.1534 reuse-first inventory policy, No.1538 market-calibrated synthetic provenance, No.1540 U19 follow-up, No.1549 U18/U19 validation-only boundary, No.1554 synthetic identity/provenance boundary, and No.1559 remaining broker/provider limitations.
- The quote-profile binder writes only to pytest temporary storage. Existing quote prices, sizes, timestamps, anchors, and calibration are not rewritten.

## Runtime-to-U19 scenario

- Shared Track2 Virtual Runtime replay capped at 85 events to stop after the first naturally produced fill: 1 signal, 1 fill, 0 rejects.
- The resulting `PositionLotProvenance` was read from the actual Runtime bridge; its `instrument_id`, `group_id`, `execution_id`, side, and remaining quantity were reconciled with the VSSF virtual account position and detailed fill trace.
- A validation-only broker snapshot and secondary execution-ledger snapshot were constructed from those same Runtime artifacts, with aligned event time, deterministic SHA-256 fingerprints, and explicit validation-only source labels.
- U19 returned `RESTORE_ALLOWED`; broker and ledger positions matched. The append-only SQLite checkpoint was reopened through a new store instance and retained the same position and execution fingerprint.
- `new_entry_enabled=false`, `order_submission_enabled=false`, and `runtime_restore_performed=false` remained enforced. Reopening the checkpoint proves durable evidence persistence only; it does not claim an actual live Runtime restoration or broker account reconciliation.

## Verification

Command:

`py -m pytest -q tests/core/test_track2_u19_recovery.py tests/application/composition/test_freshness_restart_recovery.py tests/application/composition/test_q25_a8_r9_strategyhub_shared_runtime_e2e.py tests/verification/test_q25_a8_r9_s2_u18_stop_close_runtime_e2e.py tests/verification/test_q25_a8_r9_s2_u19_runtime_restart_e2e.py`

Result: **52 passed in 6.78s**.

- New Runtime-to-U19 test plus U19 core suite: 36 passed.
- `py_compile`: PASS.
- `git diff --check`: PASS.
- An initial test attempt used source labels outside the U19 contract and correctly returned `BROKER_SNAPSHOT_UNVERIFIED`; the fixture was then aligned to the explicit validation-only source labels required by the U19 contract. No production guard was bypassed.

## Limitations

- The broker snapshot is a deterministic validation-only proxy derived from VSSF account state, not an actual KIS/broker account API response.
- The execution ledger is derived from PositionLot and Runtime trace, not a broker-confirmed execution ledger.
- This test validates one partial-open lot across durable U19 checkpoint recreation. It does not certify four-leg full-group recovery, late-fill reconciliation against a real broker, timestamp tolerance, automatic Runtime restoration, account persistence, or Live readiness.
- U18 stop/trailing operating thresholds remain unapproved. U19 recovery remains validation-only. S2 overall status remains `PSB_UNVERIFIED`.
- No new collection, collector/scheduler change, KIS Live/REAL_VTS/account/order API, or production configuration change was performed.
