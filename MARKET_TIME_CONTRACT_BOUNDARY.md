## Data path

Source

→ Transport

→ Environment Adapter

→ CanonicalMarketTick

→ Market State

→ Standard Core

Core never receives raw KIS/VMS/VSSF payload.

## Data validity

UNAVAILABLE, STALE, PARTIAL, SYNTHETIC must be distinguishable.

Synthetic is permitted only when the active Environment explicitly declares it.

## Clock policy

- Virtual Trading: simulated or real-time policy

- High-Speed: accelerated/replay policy

- Paper: real clock

- Live: real clock

Strategy/Core cannot directly call wall-clock APIs as a source of business time.

Market timestamp and execution timestamp remain distinct.