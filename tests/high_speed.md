[Child Page] high_speed_test_spec.md
## Required invariants
    1. High-Speed uses the same Standard Core/Strategy/Contract as Virtual.
    1. Only Clock/Replay/Scenario execution policy is accelerated.
    1. No Paper/Live credential or adapter can be imported.
    1. Replay events remain deterministically ordered.
    1. Pause/resume/seek/reset do not mutate Core state directly.
    1. Supported speed policies: 1x, 100x, 300x, 500x, 1000x, MAX.
    1. MAX has explicit CPU/memory safe-stop thresholds.
    1. 1x and accelerated execution must preserve event/order/decision semantics.
    1. Identical seed/scenario input must reproduce the same result.
    1. Failure stops execution safely and preserves the result evidence.
## Verification status
Structural design: PASS
Physical execution: BLOCKED
Performance benchmark: BLOCKED
High-Speed ↔ Virtual result comparison: deferred to Phase 13.