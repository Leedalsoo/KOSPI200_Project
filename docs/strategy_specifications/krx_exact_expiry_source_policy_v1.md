# KRX exact expiry master loader — source policy and limitations

## Source and schema

- Accepted input: an explicitly supplied KRX Marketplace `.xlsx` derivative master. No network download, implicit file discovery, configuration mutation, or fallback to a calculated date is performed by the loader.
- Required first-sheet headers: A `표준코드`, B `단축코드`, C `한글종목명`, G `최종거래일`.
- Exact expiry is read only from G `최종거래일`, normalized to `YYYYMMDD`. H `최종결제일` is not an expiry source.
- KRX `표준코드` is the join key because it exactly matches KIS `stnd_iscd` for matched instruments. KRX column B `단축코드` is not interchangeable with KIS `shrn_iscd`; the short codes differ in the checked examples. No name/strike/month heuristic join is allowed.
- Every resolved record retains filename, source column, load timestamp (UTC), and a filename-derived date when the filename contains `_YYYYMMDD`. The filename-derived date is not represented as an independently verified download timestamp.

## Fail-closed rules

- Missing file, invalid workbook/header, missing or malformed G value, duplicate conflicting KRX standard code, missing contract, or absent KIS standard-code join key => `BLOCKED` via a typed error.
- `YYYYMM` in the expiry column is rejected. KIS labels such as `F 202612` or `C 202610` are not promoted to exact expiry.
- A contract not present in the loaded master is `BLOCKED`; the loader never extends coverage by calculating future dates.
- Weekly contracts absent from the KIS master cannot be joined by guessing. The checked 2026-09-19 KRX weekly samples did not match the then-current KIS master by standard code; those contracts remain unresolved until a compatible KIS master record is present.

## Freshness, update ownership, and expiry of evidence

- Evidence currently available for this implementation is a Git-preserved KRX export named with `20260919`; the current working tree no longer contains the original workbook. The original OS modification time and actual download timestamp were not preserved.
- Refresh responsibility: the project operator must obtain a new KRX official export, record retrieval time and SHA-256, and explicitly pass its path to the loader. No automatic download or scheduler is added by this change.
- Refresh cadence and maximum age are **UNSET** pending user/project policy. Until those are set, presence of an exact contract in a dated snapshot proves only the date recorded by that snapshot; it does not prove that the snapshot is current or covers future contracts.
- If a requested contract is absent, a required future expiry is outside the loaded file's coverage, or freshness is not sufficient to establish coverage, callers must report `BLOCKED/UNAVAILABLE`. Do not use the second-Thursday rule as a fallback.

## Verified snapshot facts (file date from filename: 2026-09-19)

| File | Records with expiry | Exact expiry coverage | Join observations |
|---|---:|---|---|
| `data_0841_20260919.xlsx` | 2,524 | 2026-10-08 to 2027-03-11 | 2,056 standard-code matches in the checked KIS master |
| `data_0900_20260919.xlsx` | 13 | 2026-12-10 to 2028-12-14 | 6 standard-code matches; futures/spread rows are not all options |
| `data_2801_20260919.xlsx` | 4,600 | 2026-10-08 to 2028-12-14 | 3,904 standard-code matches in the checked KIS master |
| `data_2836_20260919.xlsx` | 11 | 2026-10-08 to 2027-03-11 | 5 standard-code matches; futures/spread rows are not all options |
| `data_2923_20260919.xlsx` | 196 | 2026-09-23 only | 0 matches in the checked KIS master snapshot |
| `data_2935_20260919.xlsx` | 232 | 2026-09-21 only | 0 matches in the checked KIS master snapshot |

These counts describe the historical snapshot only. They are not a statement of current KRX listings.
