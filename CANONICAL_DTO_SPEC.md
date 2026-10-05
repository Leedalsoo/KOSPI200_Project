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

## Market time and data provenance

Canonical data flow is:

Source → Transport → Environment Adapter → CanonicalMarketTick → Market State.

Raw KIS/VMS/VSSF payloads do not enter Standard Core.

Data validity states such as UNAVAILABLE, STALE, PARTIAL and SYNTHETIC must remain distinguishable. Synthetic data is valid only when the active environment explicitly declares it.

Market timestamp and execution timestamp are separate fields. Business time is supplied through the injected ClockProvider; Strategy/Core must not obtain business time directly from wall-clock APIs.

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

May contain broker-specific symbol/order type/session identifiers. The translation preserves authoritative instrument identity and execution meaning; mapping failure is fail-closed.

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

Execution timestamp is not interchangeable with requested order price or market timestamp.

## AccountSnapshot / PositionSnapshot

Environment-neutral read models with as-of timestamp and freshness metadata.

## Option and calendar provenance

OptionContract, expiry and DTE semantics belong to the domain. External Option Master and Trading Calendar sources enter through contracts and authoritative adapters.

Core must distinguish verified source, unavailable source, injected test calendar and synthetic environment calendar. It must not embed KIS/HTTP/API source logic or substitute an unverified source for an authoritative calendar.
