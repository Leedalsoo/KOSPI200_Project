## CanonicalMarketTick

Required semantic groups:

- instrument identity

- market timestamp

- received timestamp

- price

- bid/ask where available

- volume

- source status

- freshness/data quality

Missing data must be explicit; synthetic fallback cannot masquerade as real input.

## OrderIntent

Core output only:

- instrument

- side

- quantity

- intent type

- strategy/risk context

No broker-specific endpoint fields.

## BrokerOrderCommand

Environment translation of OrderIntent.

May contain broker-specific symbol/order type/session identifiers.

## ExecutionReport

- client order id

- broker order id

- execution id

- status

- filled quantity

- remaining quantity

- execution price

- execution timestamp

- source freshness

## AccountSnapshot / PositionSnapshot

Environment-neutral read models with as-of timestamp and freshness metadata.