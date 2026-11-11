# Requirements–spec–code–test traceability — Strategy 2 delta v0.3

- 작성일: 2026-11-10
- 상태: USER-APPROVED TRACEABILITY BASELINE v0.3 / RUNTIME EVIDENCE NOT VERIFIED
- 기준 명세: `strategy_2_asymmetric_trap_spec_v0.5.md`
- Current Baseline v2 SHA-256: `3FDC91266DE43EAB12EDAC50EB35200F824BC352024D21374F1DB93CD3880CB4`
- 이 문서는 이전 traceability v0.2를 대체하지 않는 새 버전 초안이다. 코드/테스트 실행 증거를 새로 생성하지 않았다.

## A. S2 requirements and current code evidence

| Requirement | Code/source evidence inspected | Current disposition |
|---|---|---|
| Four-leg structure and order | `core/strategy/track2_asymmetric_trap.py`; `application/composition/track2_execution_plan_adapter.py`; `core/strategy/track2_entry_sequence.py` | Adapter creates/validates four-leg plan; full Runtime progression not proven |
| Contract identity/expiry | `application/composition/track2_option_contract_source.py`; Option Master interface | nearest expiry and ATM pair; monthly filter and all four listed offset identities/multipliers/tradability not proven |
| Entry feature provenance | `application/composition/track2_analytics_provider.py`; `core/analytics/track2.py` | snapshot has generic provenance and null instrument identity; full source timestamp lineage not proven |
| Proposal vs fill lifecycle | `core/strategy/track2_asymmetric_trap.py` | strategy active/entry counters update at proposal time; fill-confirmed activation not proven |
| U16 repair | OMS/execution report/position lot interfaces; No.1491, No.1501–1505 | policy: reconcile cancel/terminal state, fills and positions; repair only confirmed missing quantity; unknown state blocks as RECONCILIATION_REQUIRED; BID/ASK limit; max 3 additional retries and 120 seconds; final failure policy is full liquidation of filled legs and group block. Runtime path remains unimplemented/unverified; retry interval and repricing timing unresolved |
| U17 ATM tie | `Track2OptionContractSource.select()` uses (distance, strike) ordering | lower strike tie behavior aligns; monthly/offset listing/rounding unresolved |
| U18 group P&L | `Track2AsymmetricTrap.evaluate_trap()`; option mark/PnL providers | evaluate_trap returns empty sequence; stop/trailing Runtime path not wired |
| U19 restart authority | broker position read model, persisted ledger and restore boundaries | policy says broker position primary; discrepancy and durable recovery procedure unverified |
| U20 zero-fill progression | OMS cancel/fill state machine and S2 entry progression | policy says proceed only after cancel confirmed and reconciled zero fill; no end-to-end evidence |
| U21 quote fallback | quote source, `core/oms/multi_leg_plan.py`, execution pricing/config | fallback policy direction selected; numeric thresholds/formula/tick rounding unset; legacy 1-tick offset not approved |

## B. Test mapping and evidence state

- `tests/core/test_track2_spec_alignment.py`: static/spec alignment and fail-closed controls only.
- `tests/core/test_track2_option_pnl_fail_closed.py`: confirms no underlying-price proxy is used as option-group P&L; does not prove stop/trailing execution.
- `tests/application/composition/test_track2_execution_plan_adapter.py`: adapter plan validation; does not prove full Runtime progression.
- S26 focused controls: 14 tests as recorded in S26 result; validation-only, not natural-signal Runtime E2E.
- S28 active regression: S2 sequence/adapter/fail-closed tests included in 224 passed across active strategy set; no S2 Runtime E2E.
- S27: BLOCKED_RUNTIME_WIRING; Runtime E2E and FAST/DETAILED parity not run.
- No.1501–1505 decisions are policy evidence only. Every U16–U21 acceptance scenario remains NOT_RUN unless a future run provides exact test ID, input provenance, branch/commit, config hash, logs and outcome.

## C. Required future evidence (not authorization)

1. Four-leg KIS authoritative contract identity, exact monthly expiry, multiplier, tradability and fresh quote coverage.
2. Group risk/cost preflight with versioned configuration and account aggregate exposure.
3. Sequential order/fill/cancel progression including U16 repair and U20 zero-fill exception.
4. Option group MID mark, realized/unrealized fee-aware P&L, stop/trailing thresholds and close lifecycle.
5. Durable restart reconciliation using broker-held position as primary and ledger as supplementary.
6. U21 fallback pricing, quote age/spread and tick-rounding boundary tests.
7. StrategyHub/Virtual Runtime integration and FAST/DETAILED parity on identical dataset/manifest/scope/clock.

## D. Safety and status

S2 remains BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED. All new tests and Runtime evidence are NOT_RUN. No Live/REAL_VTS/account API/order authorization. This is documentation-only traceability.
