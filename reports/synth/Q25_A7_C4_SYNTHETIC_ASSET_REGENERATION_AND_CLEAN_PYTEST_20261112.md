# Q25 A7 C4 — Synthetic asset regeneration and clean-checkout full pytest
Date: 2026-11-12

## Verdict

C4 completed. Authoritative-input-driven synthetic generation and the complete validation-only asset bootstrap succeeded in a disposable clean checkout. The final full pytest suite passed: **697 passed, 1 skipped**.

## Scope and isolation

- Integration branch: `integrate/q25-s2-20261111`.
- Starting integration HEAD: `2aee84d7d26f917e29505234cbc33a1e554a949d`.
- Disposable clean checkout: `C:\Users\white\AppData\Local\Temp\Q25_A7_C4_CLEAN_20261112`, detached at the starting HEAD.
- The original working folder was read-only. No original file was copied by move, overwritten, renamed, or deleted.
- Only generated/validation-only data was written inside the disposable clean checkout. Generated data was not added to Git.

## Authoritative input provenance

The following source files were copied from the original working folder into the disposable checkout and verified byte-for-byte by SHA-256:

| Input | SHA-256 |
| --- | --- |
| `data/calendar/krx/2026.json` | `5f4d04c3ab688180d9a10286513e5b4203cb4fe53ef13900df6e9599373a791e` |
| `data/calendar/krx/2027.json` | `8109de96c59765476c4e4d91fda6ab0f3d44d1d2f25cfd4be56bd021848e771b` |
| `data/calendar/krx/2028.json` | `9cdc1b50123fc64d69320126d492072a834ab4c6ad37583a1f6a652c85d10d30` |
| `data/historical/krx_raw/20261008_options_daily.json` | `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9` |
| `data/historical/krx_raw/20261008_futures_daily.json` | `16cc2a913f7e7b02dfb5a82c859ff01e7ed028e005de76751047e3644af8d9ec` |
| `data/historical/krx_raw/manifest_20261008.json` | `f91b69bc7aea2ecf462d738346f7c8cd513bc57983a1e822ffac6a51f815e411` |

The first generator attempt correctly failed closed because the 2028 calendar needed for forward expiry resolution was not yet present in the disposable checkout. The original 2028 KRX calendar was then copied unchanged; generation succeeded. No weekday-only or inferred calendar was substituted.

## Three-month authoritative synthetic dataset

- Generator: `py -m scripts.generate_authoritative_option_synthetic_3m`.
- Output: `data/synthetic/authoritative_option_3m_c4_20261112_retry01` (disposable checkout only).
- Rules: `project200-synthetic-3m-v4-calendar-expiry`.
- Pattern/seed: `mean_revert` / `20061009`.
- Horizon: 2026-10-08 through 2027-01-07; end-exclusive 2027-01-08.
- Actual trading days: 62; event rows: 53,550.
- Initial underlying: 1044.52 from same-date regular KOSPI200 futures symbol `A016C000`.
- Daily-pair coverage: 62/62; monthly-pair coverage: 62/62.
- Authoritative weekly coverage: 5 trading days only; all other dates remain explicitly unavailable because the snapshot does not list those future weekly identities.
- Validator: `PASS_WITH_LIMITATION`.
- Manifest SHA-256: `7cbd740378ad132117f2e8d558587d7a3fee2c8e3b81c208d162c3d2c6b537bf`.
- Limitation: KRX per-contract daily price-limit bands are not enforced because authoritative prior-session base prices are unavailable. This dataset is DERIVED_SCENARIO only and is not an exchange-valid executable quote set.

## Existing validation-only asset regeneration

Executed `verification/bootstrap_q25_a5_s01d1e_synthetic_assets_20261108.py` in the disposable clean checkout.

- Verdict: `ASSETS_RESTORED_AND_SHA_VERIFIED`.
- Restored/regenerated the P5, S7/S8 v1, S7/S8 v2, S7 concurrent S05_3, and S8 v3 normal/high-volatility assets at their expected paths.
- All dataset/manifest checks passed. Original expected inventory hashes matched for `q25_strategy7_8`, `q25_strategy7_8_v2`, and `q25_s05_3_s7_concurrent`.
- P5 payload inventory and canonical manifest hashes matched the recorded originals.
- S8 v3 normal/high-volatility payload inventories and canonical manifest semantics matched the recorded originals.
- Six protected validation-only risk profiles retained their original SHA-256 values; generated profile semantics matched tracked profiles. No tracked risk profile was modified.
- Bootstrap report SHA-256: `4fdfea3db225d561869d5db42f4e7a1e1b49dc3ce82cd3598591a82e1a49e4ab`.
- Every regenerated asset remains `validation_only=true` and `runtime_eligible=false`.

## Clean-checkout full pytest

- Initial clean-checkout run before asset bootstrap: 668 passed, 29 failed, 1 skipped. Failures were missing ignored synthetic datasets required by existing S7/S8/R4 tests; no code failure was inferred from missing data.
- After the approved asset bootstrap, reran the complete suite from the same clean checkout:

`py -m pytest -q`

**Final result: 697 passed, 1 skipped in 34.96s.**

- Final pytest log: `C:\Users\white\AppData\Local\Temp\Q25_A7_C4_FULL_PYTEST_FINAL_20261112.log`.
- Final stderr was empty. Clean checkout Git status remained clean; generated data are ignored and not committed.

## Safety and preservation

- Original working folder branch remains `cleanup/p2-quarantine-20261026`.
- Original HEAD remains `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`.
- Original Git status remains 224 entries.
- No original files or data were changed.
- No KIS API, Live/REAL_VTS, real-account, order, modify, cancel, position, or evidence API was called; external orders: 0.
- No `.env`, production risk config, scheduler, collector, or operating configuration was changed.
- No generated datasets were committed; this commit contains only the C4 report and current-stage documentation updates.

## C4 completion

C4 acceptance criteria are met: synthetic assets regenerated and validated, complete clean-checkout pytest passed, report prepared, and remote push is authorized by the A7 C4 row. C5 remains pending separate approval.
