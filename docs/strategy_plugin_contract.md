# Strategy Plugin, Configuration and Execution Contract

## Source of truth

- `core/strategy/trackN_*.py` owns the strategy algorithm and state machine.
- `config/strategies/strategy-manifest.v1.json` owns independently versioned configuration and the declared strategy boundary.
- `code_version` must match the Python strategy class version.
- `config_version` versions the parameters and declared capabilities separately from algorithm code.
- `manifest_version` versions the complete manifest. Its SHA-256 is captured by every loaded `StrategyDefinition`.
- A replay or verification should record `StrategyRegistry.configuration_provenance()` / `StrategyRunResult.config_provenance`. A pinned SHA-256 is accepted by `build_standard_strategy_registry(expected_sha256=...)`; a mismatch fails closed.

## Manifest contract

Each strategy declares:

- `required_sources`: source/read-model boundaries the Runtime must make available authoritatively.
- `required_analytics`: exact metric keys declared by `StrategyFeatureRequirement`; Registry construction rejects drift between manifest and implementation.
- `execution_contract`: `SINGLE_ORDER`, `MULTI_LEG_REQUIRED`, or `CONDITIONAL_MULTI_LEG`.
- `required_execution_tags` and `required_execution_directions`: proposal-specific multi-leg requirements for conditional strategies.
- `supported_exit_modes`: strategy's declared exit capabilities.
- `parameters`: typed values injected into constructor arguments or an explicit class `CONFIGURABLE_PARAMETERS` allowlist. Unknown parameters are rejected.

The manifest is declarative metadata and parameter storage; it does not replace algorithm code. Changes to the strategy's trading theory, state transitions, entry/exit logic or instrument composition remain separate code changes and require explicit strategy review.

## Input/data boundary

Common Analytics remains the single computation boundary for shared metrics. Strategy-specific data providers may resolve authoritative contracts and strategy-only payloads, but must represent missing sources with `UnavailableStrategyPayload` or metric statuses such as `UNAVAILABLE`/`BLOCKED`. Missing authoritative values must not be converted to zero, guessed strikes, synthetic fill prices, or other valid-looking substitutes.

## Execution boundary

`StrategyExecutionPlan` is the unified Decision output:

- `SINGLE_ORDER`: exactly one `StrategyExecutionProposal`.
- `MULTI_LEG`: exactly one `MultiLegExecutionPlan`.

The existing `MultiLegDecision` remains as a compatibility projection while the runtime consumes the unified plan. A strategy marked `MULTI_LEG_REQUIRED`, or a conditional signal matching its required tag/direction, fails closed if its resolver is absent or returns no plan. Single-order strategies and non-required conditional signals may continue without a multi-leg plan.

The plan is intent, not proof of execution. Filled quantity, average fill price, position and P/L remain grounded in authoritative execution reports and position read models. Strategy-local state must not be treated as evidence of broker fill.

## Required verification

- Manifest schema, unique IDs, class-code version match, required-analytics drift detection and pinned-hash checks.
- Configuration isolation: changing one strategy's config must not mutate other strategies.
- Strategy Plugin contract tests and explicit unavailable-data behavior.
- Single-order and multi-leg plan shape tests, including fail-closed required-plan behavior.
- Existing strategy unit tests, Runtime integration tests, architecture dependency rules, and PHASE J E2E validation.
