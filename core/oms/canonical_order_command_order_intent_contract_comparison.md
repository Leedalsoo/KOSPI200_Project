## Baseline

Reference Runtime: CanonicalStrategySignal → CanonicalOrderCommand → RiskGate → OrderRouter → Environment.

## Comparison

<!-- Notion table block -->
| Field | CanonicalOrderCommand | Standard OrderIntentExecutionInput / OrderIntent | Decision |
| client_order_id | str | str | Direct 1:1 |
| quantity | qty: int | quantity: int | Use authoritative post-Risk quantity; never Strategy qty as fallback |
| requested_price | price: float | `requested_price: Decimal | None` |
| side | CanonicalOrderSide BUY/SELL | OrderIntent side: str; Factory currently derives from Signal.direction | Preserve Canonical BUY/SELL; do not reverse-map through LONG/SHORT |
| asset_type | CanonicalAssetType | execution asset_type / OrderIntent asset_type | Direct semantic mapping |
| track_id | str | `str | None` |
| tag_id | str | `str | None` |
| option_type | optional CanonicalOptionType | OptionInstrumentIdentity.option_type | Identity mapping + equality validation |
| strike | float | OptionInstrumentIdentity.strike | Identity mapping + equality validation |
| symbol | str | OptionInstrumentIdentity.symbol | Preserve authoritative identity value; no default supplementation |
| expiry | str | OptionInstrumentIdentity.expiry | Preserve authoritative value; no inference |
| instrument_id | absent as stored field; command exposes get_instrument_key() | required by OrderIntent | Requires explicit identity equivalence validation; no synthetic ID |
| order_type | absent | required by execution input / optional on OrderIntent | No safe source in current Canonical Runtime |
| order_purpose | absent | required by execution input / optional on OrderIntent | No safe source in current Canonical Runtime |
| broker-specific fields | absent | absent from Core; BrokerOrderCommand owns them | Environment-only |

## Non-negotiable mapping rules

- No order_type default such as LIMIT may be introduced from legacy OrderRequest.

- No order_purpose may be inferred from track/tag/action/side.

- No new instrument_id may be generated when authoritative identity is absent.

- OPTION identity must remain internally consistent with symbol/expiry/option_type/strike and its instrument_id.

- Risk ALLOW/REDUCE determines executable quantity; DENY creates no execution intent.

## Current implementation decision

Do not replace the Reference Runtime's CanonicalOrderCommand path yet. A non-invasive adapter may be introduced only after an authoritative supplier for order_type and order_purpose is defined and identity equivalence is validated.