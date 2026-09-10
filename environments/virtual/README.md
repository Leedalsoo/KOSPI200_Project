Virtual Trading owns all synthetic market behavior and VSSF-derived broker/account/position/execution behavior.

High-Speed will reuse this bundle and replace only clock/replay/scenario policies.

Paper/Live must not import these implementation modules.

Baseline stress scenarios, margin, PnL, ledger, reconciliation and recovery are migrated incrementally without changing the Standard Core contract.