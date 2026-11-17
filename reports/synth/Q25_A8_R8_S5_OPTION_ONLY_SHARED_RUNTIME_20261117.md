# Q25 A8 R8 — S5 option-only Shared Virtual Runtime validation

- Date: 2026-11-17
- Status: `SYNTHETIC_VALIDATION_ONLY`
- Strategy decision reference: Notion No.1565 (D1-A option-only direction; D2-D8 remain unapproved)
- Data/validation references: No.1534, No.1535, No.1538, No.1554

## 1. Reused market-calibrated option sidecar

The existing R7 sidecar was reused; it was not regenerated or changed.

- Original dataset: `data/derived_scenario/q25_a8_r7_s5_atm_market_calibrated_v3_20261117`
- R8 validation copy: `data/derived_scenario/q25_a8_r8_s5_atm_market_calibrated_v1_20261117`
- Quote rows: 3,160; complete CALL/PUT pairs: 1,570; partial pairs: 20.
- Candidate timestamp groups: 1,594; future observation count: 0.
- Source sidecar manifest SHA-256: `606e3d4c93f03adfbb7831208c0c08c396d7f373026c36f80635b7795eacf335`
- Quote JSONL SHA-256: `df8f2bea97ac8e3cd1b90213575aefa9bf782179d65b87baf0be2e6c08bf7193`
- Candidate input SHA-256: `8716c0907c9f699492acdeabc159323939643034d60d02300d0248a52b562dc2`

The sidecar retains observed source anchors, empirical IV calibration, observed spread statistics and L1 quantity proxy provenance. Its source KIS contract codes remain crosswalk-only; synthetic IDs are not promoted to KIS identity. Multiplier remains null in the sidecar.

## 2. Runtime-only identity and accounting adapter

- Profile: `config/validation_only/q25_s5/option_only_runtime_profile.v1.json`
- Profile SHA-256: `c89f13dde86ce278cf24cb26c31bfd9f2daefdb3097fec9f50ad8ac6ca74d4f4`
- Selected four quote groups: 2026-10-13 10:26:29, 10:26:38, 10:26:49 and 10:27:11 KST; expiry 20261112; strike 937.5.
- Sidecar's per-timestamp synthetic IDs are mapped to stable scenario-local IDs by `sha256(profile_id|expiry|option_type|strike)[:32]`, preserving one CALL and one PUT identity across the lifecycle.
- VSSF requires a non-null option multiplier to execute a Virtual fill. A technical runtime unit scale of `1` is therefore used only inside this isolated fixture. It is not a KIS multiplier, contract specification, KRW notional, margin, or PnL authority.
- A weekday-only DTE proxy of 22 is supplied solely to satisfy a shared Runtime data-provider field; exchange holiday authority is `NONE` and it is not used by S5 policy logic.

## 3. Shared Virtual Runtime lifecycle

A test-only signal driver (not `Track5GapDivergence`) sends four validation intents through StrategyHub → Risk → OMS/Router → VSSF → PositionLot → close resolver:

1. CALL BUY 1 — primary option entry.
2. PUT BUY 1 — opposite-option hedge scenario.
3. PUT SELL 1 — close the hedge lot independently.
4. CALL SELL 1 — close the primary option lot independently.

Assertions at each phase: one signal, one approval, routed and filled execution, zero rejection. Open option lots transition `1 → 2 → 1 → 0`; final open-lot set is empty. This proves the shared Virtual Runtime can route and reconcile the option-only two-lot lifecycle using the synthetic quote sidecar.

This is Runtime plumbing/lifecycle evidence only. It does not prove that production S5 generated these signals, that the chosen hedge-close order is an approved operating rule, or that any D2-D8 threshold is accepted.

## 4. Tests and boundaries

- New S5 validation-only profile/Runtime tests: 3 passed.
- Combined focused S5 regression (analytics provider, option contract source, strategy spec guard, seed-ingestion guards, reversal analysis and new Shared Runtime tests): 33 passed in 1.01s.
- `py_compile`: PASS; `git diff --check`: PASS.
- Production `Track5GapDivergence.CURRENT_EXECUTION_POLICY_APPROVED` remains `False`; no production strategy, Runtime composition, Risk/OMS policy, or production configuration changed.
- D2-D8 remain UNSET/PROVISIONAL/UNAPPROVED. No option premium profitability, official multiplier, tradability, fees/taxes, account capital/margin, actual fills or Live readiness is certified.
- No Raw/Canonical/accepted source or original R7 sidecar was modified. R8 data copy remains ignored/uncommitted data.
- No new collection, KIS/REAL_VTS/Live/account/order API calls, real orders, or Project200 merge.

## 5. Git

- Branch: `work/q25-a8-r8-s5-gap-observed-20261117`
- Commit: pending
- Project200 merge: none
