# FRESH-52 ? Quote / OrderBook / Execution Evidence Lineage

- Contract: B01611887 / CALL / 887.50 / 2026-11-12.
- Preserved KIS REST quote: source timestamp missing; receive time retained separately.
- Preserved KIS REST OrderBook: one-sided (5 bid levels, no ask levels).
- Synthetic quote and depth remain separate validation-only records; quote-to-book link uses quote dataset hash, source anchor hash, scenario and generation/receive time.
- One raw KIS VTS H0IOASP0 WebSocket OrderBook snapshot was recovered from the original 2026-10-21 Raw file and cross-checked against Canonical. Five bid and five ask levels, including quantities, match the Canonical observation. Payload SHA-256 exactly matches the S15B virtual Execution evidence hash; contract identity also matches.
- WebSocket raw HHMMSS `090115` is retained as a candidate only; it is not promoted to authoritative event time. Raw receive time is `2026-10-21T00:01:16.106074+00:00`. The virtual Execution timestamp is exactly equal to that receive time (0 seconds receive-to-execution lag); candidate HHMMSS-to-receive lag is recorded separately.
- This establishes source-payload-to-validation-virtual-fill evidence linkage, not a real KIS execution or proof of actual exchange fill. Only one observed OrderBook snapshot is available; continuous coverage is not proven. Multiplier 250000 remains a validation-only assumption.

## Counts

```json
{
  "execution_identity_matches": 1,
  "execution_orderbook_evidence_matches": 1,
  "execution_records": 1,
  "execution_validation_only_multiplier": 1,
  "master_records": 2,
  "orderbook_identity_matches": 3,
  "orderbook_one_sided_or_empty": 1,
  "orderbook_quote_lineage_matches": 1,
  "orderbook_records": 3,
  "quote_identity_matches": 2,
  "quote_missing_source_time": 2,
  "quote_records": 2
}
```

## Judgement

```json
{
  "authoritative_multiplier_proven": false,
  "complete_observed_orderbook_available": true,
  "contract_identity_linked": true,
  "execution_to_orderbook_direct_linked": true,
  "quote_to_orderbook_lineage_linked": true,
  "real_execution_evidence": false
}
```

- Issues: `0`
- Report SHA-256: `6877d1beb1cdf14cf56aeaf3b4417e144172d8c1414a4a2987de861596d94cad`
- `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`.
