# FRESH-52 addendum ? 2026-10-01 18-contract OrderBook lineage

- Original files are read-only. Raw H0IOASP0: 323 frames / 18 contracts. One earliest-received snapshot per contract was selected deterministically (18 snapshots).
- KRX 2026-10-08 identity crosswalk: 18/18 contracts matched by KIS short code, CALL/PUT, strike and expiry. KRX is identity evidence only, not proof of account tradability or multiplier.
- All 18 quote records are derived from the same H0IOASP0 payload top-of-book, not an independent Quote feed. Raw HHMMSS remains candidate only; `received_at` is separate.
- Each OrderBook preserves five bid/ask levels, quantities, raw payload SHA-256, sequence and receive time.
- 18 synthetic validation fills test Execution linkage only; they are not broker executions. No multiplier is asserted.

## Counts
```json
{
  "execution_identity_matches": 18,
  "execution_orderbook_evidence_matches": 18,
  "execution_records": 18,
  "master_records": 18,
  "orderbook_identity_matches": 18,
  "orderbook_quote_lineage_matches": 18,
  "orderbook_records": 18,
  "quote_identity_matches": 18,
  "quote_missing_source_time": 18,
  "quote_records": 18
}
```
## Chain judgement
```json
{
  "contract_identity_linked": true,
  "quote_to_orderbook_lineage_linked": true,
  "complete_observed_orderbook_available": true,
  "execution_to_orderbook_direct_linked": true,
  "real_execution_evidence": false,
  "authoritative_multiplier_proven": false
}
```
- Issues: 0; `authority_claimed=false`, `gate_release_permitted=false`, `mutation_applied=false`.
- Source hashes: Raw `efee6e6e101c6aa2fa63a2c8b4408e56bc824ba1ea7dd271d547bf3dd941ea83`, REST `1c0eb48ffca3e065d789bbee334540e9512c1a55989185712a7be5bd7f348c5b`, daily manifest `c378814aa4ee630d9a8e1ded0c1d593c6d2adea26c04184469c5a9c5f701232d`, KRX Raw `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`, KRX manifest `f91b69bc7aea2ecf462d738346f7c8cd513bc57983a1e822ffac6a51f815e411`, derived quote bundle `8f3f8b2bb0afdf382ce3d7ab45d5c2fbe8ae1dc8d7e1fda90f8460c4c813c2ed`.
- Report SHA-256: `bdeb865f4b17dddd8c5e425f72ef09c56212ecef933cde0f4877037209679fa3`.
- Limits: no independent quote feed linkage, no observed Execution evidence, no official event-time semantics, no multiplier/tick/tradability/account validation, no continuous coverage claim.
