## Domain

OptionContract, Expiry, DTE semantics belong to core/domain.

## External source

KIS fo_idx_code_mts.mst download/parsing is infrastructure.

It supplies OptionContractMaster data through a Contract.

## Calendar

Trading-day policy is a Calendar Contract implementation.

The current Trading Calendar source boundary remains BLOCKED where official runtime source validation is unavailable.

No KRX Futures/Options response is promoted to a Calendar source merely as a substitute.

## Safety

Core must distinguish:

- verified source

- unavailable source

- injected test calendar

- synthetic environment calendar

DTE logic may consume a Calendar Contract but may not embed KIS/HTTP/API logic.