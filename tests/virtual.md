[Child Page] virtual_environment_test_spec.md
    1. Market adapter produces canonical market data.
    1. Market → Core → OrderIntent path is environment-independent.
    1. OrderIntent → Virtual Broker → ExecutionReport works.
    1. Account/Position update after fills.
    1. Reconciliation detects state mismatch.
    1. Restart restores persisted virtual state.
    1. Virtual imports no Paper/Live implementation.
    1. Synthetic data remains Virtual-only.
    1. Kill Switch prevents new order submission.
    1. Same deterministic scenario produces the same execution sequence.
Execution status: specification ready; physical workspace execution remains BLOCKED.