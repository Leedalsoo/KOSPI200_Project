# KIS Master Type-Code Mapping — Evidence Draft

작성일: 2026-10-14
상태: 검증 중 / 공식 코드 사전 미확인 / 사용자 승인 전

## Source and limitation
- Source archive: verification/evidence/fo_idx_code_mts_20261014.zip
- SHA-256: f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e
- KIS official master download: https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip
- The master is official source data, and its name field correlates type code with CALL/PUT and monthly/weekly labels. An independent KIS official type-code dictionary/field-definition document for all codes below was not located in this run. Therefore this is a row-corroborated mapping, not an independently documented official code dictionary.
- Runtime parser must accept a row only when code and human-readable label corroborate one another; unknown code, missing label, or mismatch is excluded/BLOCKED.

## Row-correlated mapping table
| Type code | Candidate interpretation | KOSPI200 row count | Example labels | Evidence state |
|---|---|---:|---|---|
| 5 | Monthly standard CALL | 2143 | C 202611   750.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| 6 | Monthly standard PUT | 2143 | P 202611   750.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| D | Monthly mini CALL | 1108 | 미니C 202611   750.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| E | Monthly mini PUT | 1108 | 미니P 202611   750.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| L | Thursday weekly CALL | 124 | 위클리C 2610W3   885.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| M | Thursday weekly PUT | 124 | 위클리P 2610W3   885.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| N | Monday weekly CALL | 113 | 위클리M C 2610W3   885.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |
| O | Monday weekly PUT | 113 | 위클리M P 2610W3   885.0 | ROW_CORROBORATED / OFFICIAL_DICTIONARY_NOT_FOUND |

## Result
- Codes 5/6/D/E/L/M/N/O: 6976 rows; weekly L/M/N/O: 474 rows.
- The row label is used as a mandatory consistency check. It is not used to infer an exact expiry date. Exact YYYYMMDD still comes only from KIS REST futs_last_tr_date with provenance.
- Mini option exact-expiry cache sample is absent; mini identity is not considered fully validated until exact KIS expiry records are captured. Contract multiplier remains UNSET.
- Evidence JSON: verification/evidence/kis_master_identity_join_20261014.json and verification/evidence/kis_expiry_crosscheck_20261014.json.
