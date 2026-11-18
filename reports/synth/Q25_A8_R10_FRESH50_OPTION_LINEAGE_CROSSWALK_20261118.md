# FRESH-50 ? Option Master ? Quote ? OrderBook ? Execution Lineage Crosswalk

- Contract: B01611887 / CALL / 887.50 / 2026-11-12.
- Two official KIS Master snapshots (2026-10-21 and 2026-11-08) contain matching identity fields; snapshot hashes remain distinct.
- Preserved REST quote has no source timestamp.
- Preserved REST OrderBook is one-sided (5 bid levels, 0 populated ask levels).
- Synthetic quote and 5x5 depth are linked by source record, manifest hash, anchor hash and generated time; generated time is not source event time.
- One S15B virtual fill links to the Master contract identity but is not a real broker execution. Multiplier 250000 remains validation-only.
- Runtime report orderbook evidence SHA-256: `99b91c1a7f0685ab21f2a0da7d87903bd408cf39555cd9202cd7fa4744c870fc`; direct raw OrderBook-to-Execution linkage is not established.

## Counts

```json
{
  "execution_identity_matches": 1,
  "execution_records": 1,
  "execution_validation_only_multiplier": 1,
  "master_records": 2,
  "orderbook_identity_matches": 2,
  "orderbook_one_sided_or_empty": 1,
  "orderbook_quote_lineage_matches": 1,
  "orderbook_records": 2,
  "quote_identity_matches": 2,
  "quote_missing_source_time": 2,
  "quote_records": 2
}
```

## Chain judgement

```json
{
  "authoritative_multiplier_proven": false,
  "complete_observed_orderbook_available": false,
  "contract_identity_linked": true,
  "execution_to_orderbook_direct_linked": false,
  "quote_to_orderbook_lineage_linked": true,
  "real_execution_evidence": false
}
```

- Issues: `0`
- `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`.
- Report SHA-256: `a0cc94b702d745ffb8b40d02ba893fcc3ee91d31ae083fd4df534f003849b51d`
