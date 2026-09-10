Baseline contains strategy-adjacent logic across:

- option_program/strategy

- option_program/signal

- option_program/decision

- option_program/sensor/graph_strategy.py

- runtime Track-oriented execution paths

## Migration rule

The documented 9 strategies are not assumed to equal 9 clean standalone files.

Phase 5 must first create a Strategy Registry and common Strategy Contract, then migrate each strategy by:

1. identity/name

1. input features

1. signal rules

1. entry/exit rules

1. risk interaction

1. order intent output

1. runtime activation path

Unused or duplicate strategy artifacts remain Reference-only until explicitly classified.