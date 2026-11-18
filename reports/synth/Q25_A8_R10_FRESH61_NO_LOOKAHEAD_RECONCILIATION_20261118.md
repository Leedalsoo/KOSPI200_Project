# FRESH-61 — Accepted Runtime v2 future-anchor reconciliation

- Report SHA-256: `da17f73b85eb7be8ecfcd8fbb6c1fc84ecdd759eb6f048e48675fd74f6fbd3a1`

| Date | Rows | Future donors before | Replaced | Future donors after | Underlying replacements | Ask proxy | Max prior age (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20261012 | 686 | 0 | 0 | 0 | 0 | 0 | None |
| 20261013 | 1386 | 28 | 28 | 0 | 27 | 1 | 283.0 |

## Ask proxy detail

- Target: B01611A01 CALL 1000.0, expiry 20261112, 2026-10-13T08:45:00+09:00.
- Donor: same-time KRX derived scenario CALL 1032.5, same expiry; strike distance 32.5, spread 0.5. Raw bid 35.5 / prior future-generated ask 37.45 -> validation-only synthetic ask 36.0 (change -1.4500000000000028).
- This is not a KIS observed ask and must not be used as actual broker quote or profitability evidence.

## Limits

- Underlying replacements use same-day nearest-prior 5-minute synthetic KRX spot only.
- Original future anchors are preserved as audit metadata; original Accepted Runtime v2 and KRX source data remain unchanged.
- All corrected rows are DERIVED_SCENARIO / validation-only. No account Execution/fill or Live authority.
