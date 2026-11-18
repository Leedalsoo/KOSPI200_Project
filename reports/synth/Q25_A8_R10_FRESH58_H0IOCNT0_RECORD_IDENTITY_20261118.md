# FRESH-58 — H0IOCNT0 58-field record identity and canonical collision audit

- Report SHA-256: `45bd9fed06aa0d01d457107a637829d59b1429e61cb347f8bfb56703d092ed90`

## Aggregate

| Metric | Count |
|---|---:|
| raw_h0iocnt0_frames | 235,466 |
| parsed_58_field_records | 352,065 |
| duplicate_sequence_groups | 61,762 |
| duplicate_sequence_excess_frames | 61,762 |
| duplicate_payload_hash_groups | 0 |
| duplicate_payload_hash_excess_frames | 0 |
| malformed_frames | 0 |
| payload_hash_mismatches | 0 |
| legacy_symbol_time_duplicate_groups | 64,962 |
| legacy_symbol_time_excess_records | 116,209 |
| exact_full_record_duplicate_groups_within_frame | 0 |
| exact_full_record_duplicate_excess_records | 0 |
| current_raw_id_collision_count | 0 |
| current_normalizer_observation_id_collision_count | 0 |

## Per-day

| Date | Raw frames | Parsed records | Duplicate seq groups | Duplicate seq excess | Legacy key groups | Legacy excess | Exact-record duplicate excess | Current ID collisions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 20261001 | 2421 | 2710 | 104 | 104 | 198 | 289 | 0 | 0 |
| 20261006 | 7952 | 10359 | 0 | 0 | 1297 | 2401 | 0 | 0 |
| 20261007 | 51517 | 69055 | 6524 | 6524 | 11103 | 17467 | 0 | 0 |
| 20261008 | 171706 | 267869 | 55134 | 55134 | 52230 | 95851 | 0 | 0 |
| 20261012 | 636 | 686 | 0 | 0 | 39 | 50 | 0 | 0 |
| 20261013 | 1234 | 1386 | 0 | 0 | 95 | 151 | 0 | 0 |

## Existing Canonical comparison (read-only)

| Date | Rows | WS rows | WS raw IDs | WS symbols | Raw symbols absent in WS Canonical | ID duplicate excess | Raw ID duplicate excess |
|---|---:|---:|---:|---:|---|---:|---:|
| 20261001 | 6330 | 1995 | 1995 | 25 | 1 | 0 | 390 |
| 20261006 | 2998 | 0 | 0 | 0 | 26 | 0 | 414 |
| 20261007 | 5139 | 0 | 0 | 0 | 26 | 0 | 596 |
| 20261008 | 3944 | 0 | 0 | 0 | 26 | 0 | 715 |
| 20261012 | 5450 | 0 | 0 | 0 | 30 | 0 | 789 |
| 20261013 | 6762 | 0 | 0 | 0 | 53 | 0 | 868 |

## Interpretation

- Raw frame count and 58-field trade-record count are independent measures.
- A repeated (short_code, BSOP_HOUR) within one frame is not by itself a duplicate execution; compare full 58-field digest.
- Duplicate sequence is not a unique frame identity. Current ingestion raw_id adds line number and payload SHA-256.
- Current normalizer adds frame-local record_index to the observation ID seed; no production code change was needed for this audit.
- 2026-10-01 legacy Canonical contains 1,995 H0IOCNT0 rows vs 2,710 Raw records (715 fewer), 25/26 symbols, missing C01610A41; it remains unchanged.
- 2026-10-06/07/08/12/13 legacy Canonical files are REST-only; no H0IOCNT0 rows there does not mean Raw trades are absent.
- Its 390 repeated raw_id references are REST duplicate references, not H0IOCNT0 observation_id collisions.
- Original Raw/Canonical/Manifest are read-only. No collection, API call, Canonical rewrite, account execution inference, or Live gate release.
