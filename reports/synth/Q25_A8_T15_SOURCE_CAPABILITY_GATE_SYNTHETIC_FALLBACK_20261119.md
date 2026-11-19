# Q25 A8 T15 — Source Capability Gate and Synthetic Fallback

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only evidence gating; no source data rewrite

## Mandatory reconciliation

- No.1534 and No.1422 were checked before implementation, together with the original 2026-10-13 manifest, raw WS records and timing sidecar.
- The manifest labels the run VTS, but the raw event has no independent account/environment proof. The timing sidecar marks H0IOCNT0 capability, clock timezone and date semantics UNVERIFIED.
- The official KIS sample documents H0IOCNT0 and H0IOASP0 as real-account-only, virtual trading unsupported:
  https://github.com/koreainvestment/open-trading-api/blob/74b0a082fa67a0be5bf53f561719c853890ed2df/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py
- This remains an unresolved source-environment conflict. No REAL or VTS authority is inferred. The T13 WS lag distribution is candidate-only, not authoritative source age.

## Implementation

- Added a shared accepted-source provenance gate. An original accepted quote candidate now requires every row to explicitly carry:
  - source_capability_status beginning with VERIFIED;
  - known source_environment;
  - source_timestamp_absolute=true;
  - verified source timezone and date resolution;
  - source_time_semantics_verified=true.
- The Notion/source reconciliation provider additionally requires the per-day WS timing sidecar to show verified H0IOCNT0 capability, clock timezone and date semantics. Missing sidecar or any UNVERIFIED value leaves the source candidate ineligible.
- The reconciliation diagnostic still records raw SHA-256 and scenario-anchor matching, but separately appends SOURCE_CAPABILITY_OR_TIME_SEMANTICS_UNVERIFIED. This distinguishes file-lineage verification from source authority.
- Unverified source candidates return None and continue to the provenance-preserving synthetic alternative. They do not trip X2 or immediately block the run.
- WS and REST normalizers expose source_environment=UNKNOWN, source_environment_status=UNVERIFIED, source_time_semantics_verified=false until independently verified. WS candidate KST/trading-date interpretation remains separately labeled candidate-only.

## Runtime verification

A validation-only virtual replay of the 2026-10-12 candidate produced:

- Accepted original primary: 0/4 synchronous legs.
- Notion/source reconciliation: raw WS SHA matched; scenario anchors 12/12; source capability/time semantics UNVERIFIED; original leg coverage 0/4.
- Provenance-preserving synthetic alternative: VALIDATED.
- X2 state: ARMED.
- cancel_orders=false, flatten_positions=false, runtime_stop=false.

A dedicated supervisor test also supplies four matching accepted rows but deliberately unverified WS timing metadata. Both original and reconciliation candidates are rejected as authoritative; the synthetic alternative validates and X2 remains ARMED.

## Validation and boundaries

- Combined T5-T15 regression suite: 208 passed, 0 failed.
- compileall, REST normalizer Ruff, WS/provider/test import and critical Ruff checks, git diff --check PASS.
- No Raw/Canonical/accepted partition or manifest modified. No Live/REAL_VTS/account API connection, new collection, collector restart, order, cancellation or liquidation.
- Actual account API connection remains the only route to resolving the environment, capability, contract, source-clock and date semantics. Until then, synthetic validation is the approved fallback.
- Next T16: continue Virtual-only synthetic verification and preserve the source-capability gate; re-evaluate authoritative mapping only after the user connects the real investment API and its exact environment is proven.
