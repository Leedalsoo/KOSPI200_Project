# Strategy 1~9 통합설계표 — S9 변경 delta v0.5

- 상태: draft / unverified / unapproved
- 기존 02_decision_factor_integrated_design_matrix_v0.4.md 보존. 본 문서는 S9 변경 부록이다.
- S9는 v0.2 overnight PUT/CALL에서 S1-linked OTM PUT 보험으로 의도 변경되었다. S1~S8의 기존 표 셀은 이 부록에서 수정하지 않는다.
- 작성만 수행하며 코드/테스트/Git 변경이나 구현 승인이 아니다.

## 1. 핵심 변경
- 폐기: 장 마감 전 PUT+CALL 양매수, 이벤트/야간 보험, 다음 거래일 시초가 급변동 기반 청산.
- 신규: S1 authoritative short PUT 잔여 수량을 trigger/basis로 OTM PUT만 매수; rank 4 우선/rank 3 fallback; 30분 LIMIT timeout 및 cancel-confirm; TP multiple; 이전 매수가×1.30 이하 동일 종목 재매수; DTE7 청산/차기 월물 준비.
- 월 프리미엄 한도는 별도 설정하지 않는다. 파생 비용은 실제 체결 수량×가격×승수 및 수수료다. 공통 계좌 위험/증거금 게이트 유지.
- ID/파일명 변경은 제안만 하며 기존 참조를 보존한다.

## 2. F01–F29 재분류 집계
- 확정/확정-검증 16; 설정·검증값 7; 사용자 확인 필요 6.
- 행별 근거: strategy_9_s1_put_insurance_spec_v0.3.md §2. 의도 분류이며 실행 검증 PASS가 아니다.

## 3. 기존 U01–U15 전체 분류 (삭제·재번호 변경 금지)

| ID | 기존 미결 항목 | S9 delta 분류 | S9 처리 |
|---|---|---|---|
| U01 | S1 payoff/3-leg structure | 사용자 확인 필요 | S9는 S1 short PUT 수량을 소비하지만 S1 payoff 결정권 없음 |
| U02 | S2 4-leg payoff/stop/trailing | 사용자 확인 필요 | S9 premium/stress를 account aggregation에 포함 |
| U03 | S3 tradable spread identity | 사용자 확인 필요 | 실제 계약 identity 필요 |
| U04 | S4 option lots/delta ownership | 사용자 확인 필요 | duplicate position attribution 방지 |
| U05 | S5 Futures role/quantity/terminal sequence | 사용자 확인 필요 | S9 수량을 Futures 수량으로 환산하지 않음 |
| U06 | S6 pair MTM/partial/cutoff | 사용자 확인 필요 | premium/stress 합산 |
| U07 | S7 IV skew trigger/expiry | 사용자 확인 필요 | expiry/source provenance |
| U08 | S8 add-on/rounding/DTE | 사용자 확인 필요 | S8 overlay와 S9 보험을 계좌 위험에 포함 |
| U09 | S9 latest entry/open/skipped-window exit | 의도상 해결, 실행 검증 미완료 | overnight/opening structure를 S1 position trigger로 대체 |
| U10 | account capital/premium/max-loss values | 설정으로 이관 | S9 monthly cap 없음; common caps/margin/stress 유지 |
| U11 | common partial/cancel/restart persistence | 사용자 확인 필요 | S9 cancel race/partial/restart runtime evidence 없음 |
| U12 | account-wide exposure/correlation/netting | 설정으로 이관 + 사용자 확인 필요 | aggregate model unresolved |
| U13 | authoritative P&L/fee/multiplier | 사용자 확인 필요 | actual fills/marks/fees required |
| U14 | exact expiry/session/rollover | 사용자 확인 필요 | YYYYMMDD required; DTE semantics/roll boundary unresolved |
| U15 | Shrimp Resume Context | UNAVAILABLE / 사용자 확인 필요 | 접근/갱신 증거 없음 |

## 4. 기존 G01–G12 미충족 게이트 전체

| Gate | S9 상태 | 근거/남은 일 |
|---|---|---|
| G01 payoff/role | PARTIAL/BLOCKED | partial insurance intent set; payoff/stress effectiveness needs validation |
| G02 entry/scale/exit | BLOCKED | S1 trigger/fallback specified; TP/rebuy/resize priority needs validation |
| G03 contract/expiry/qty/multiplier | BLOCKED | exact YYYYMMDD, rank ladder, integer sizing, DTE semantics |
| G04 partial/reject/cancel race | SPECIFIED/UNVERIFIED | no scenario run; cancel race/resize pending tests |
| G05 hedge/rebalance/overlay | PARTIAL/BLOCKED | PUT insurance role specified; coverage/overlap evidence absent |
| G06 stop/target/trailing/time exit | BLOCKED | TP null; DTE7 vs S1 DTE4 conflict U35 |
| G07 session/expiry/rollover | BLOCKED | next expiry delay, DTE definition, roll timestamp |
| G08 capital/premium/max-loss/account risk | BLOCKED | no S9 monthly cap, but common account risk applies; enforcement unverified |
| G09 failure/restart/recovery | BLOCKED | persistence/late-fill/reconciliation unverified |
| G10 requirements-spec-code-test | BLOCKED | exact tests/evidence not run/mapped |
| G11 assumptions/external dependencies | DRAFT/BLOCKED | U30–U37 and authoritative source evidence remain |
| G12 validation vs approval | process rule only PASS | remains draft/unverified/unapproved |

## 5. I01–I16 interaction register (all IDs retained)

| ID | S9 interaction | Status |
|---|---|---|
| I01 | S9 derived premium/margin contributes to account exposure; no monthly cap does not exempt common risk | BLOCKED until runtime gate |
| I02 | S9 uses no Futures and no Futures-to-option quantity conversion | S9 intent resolved; global S3/S4/S5 issues remain |
| I03 | S1 short PUT is S9 quantity source; no account-wide/unowned PUT counts | BLOCKED: authoritative lot ownership |
| I04 | S1/S6/S7/S8/S9 insurance overlap: aggregate premium/margin/expiry/stress; no double-credit | BLOCKED: stress model |
| I05 | 4th cancel-confirm then 3rd fallback; late fill reconciled per leg | specified/unverified |
| I06 | realized P&L uses actual fill/qty/multiplier/fees; marks are not fills | BLOCKED: ledger evidence |
| I07 | S9 DTE7 roll vs S1 DTE4 close | BLOCKED: U35 |
| I08 | simultaneous TP, S1 qty change, roll, cancel/fill and risk triggers need priority | BLOCKED: U35/U36 |
| I09 | missing/stale S1 position, quote, volume, expiry or config blocks orders | specified/enforcement unverified |
| I10 | restart reconciles S1/S9 lots and pending orders before resume | specified/persistence unverified |
| I11 | S9 quantity from S1 PUT link ratio, never Mini Futures conversion | intent resolved |
| I12 | S3 spread identity remains independent of S9 insurance | S3 user confirmation remains |
| I13 | S4 delta ownership must not count S9 lots twice or claim S9 lot as S4 inventory | attribution specified/evidence blocked |
| I14 | S8 overlay and S9 PUT overlap; aggregate risk without changing S8 trigger | BLOCKED |
| I15 | S1 DTE4 full close vs S9 DTE7 roll and linked target zero | BLOCKED: U35 |
| I16 | config version/hash and source/order/fill/position provenance per run | specified/enforcement unverified |

## 6. 신규 U30–U37 (S1 기존 U16–U29와 ID 충돌 방지)

| ID | 항목 | 상태 |
|---|---|---|
| U30 | 3rd strike도 liquidity/quote gate 미충족 시 포기 vs 대기 | 사용자 확인 필요; BLOCK_FOR_SESSION / WAIT_AND_RECHECK 후보 |
| U31 | take_profit_multiple 후보와 acceptance threshold | REAL_VTS tuning/holdout; 2x/3x/5x 후보만 |
| U32 | min_volume 및 quote/liquidity composite gate | REAL_VTS 검증; volume 단독 판단 금지 |
| U33 | s1_put_link_ratio 및 정수화 | REAL_VTS 검증; delta-equivalent 추정 금지 |
| U34 | 차기 월물 상장 지연 시 동작 | 사용자 확인 필요; default BLOCKED |
| U35 | S1 DTE4 short PUT flat vs S9 DTE7 roll/target zero | 사용자 확인 필요 |
| U36 | initial LIMIT/reprice count 및 동시 trigger priority | 사용자 확인 필요 |
| U37 | strategy_id/file alias 및 migration impact | 제안만; 기존 ID/path 보존 |

## 7. S1↔S9 timeline conflict
S9 target quantity는 S1 short PUT 잔여 수량에 연동되므로 S1 수량이 0이면 S9 target도 0이다. S1 명세는 DTE4에 short PUT을 포함한 관련 포지션을 청산하고, S9는 DTE7에 현 월물 청산/차기 월물 준비를 한다. 따라서 S9가 DTE7에 차기 월물 보험을 매수해도 S1이 DTE4에 short PUT을 닫으면 S9 target은 0이 되어야 한다. 차기 월물 보험을 DTE4에 즉시 줄일지, S1 종료 후에도 DTE7 보유를 유지할지 자동 해석하지 않고 U35로 사용자 확인을 받는다.

## 8. 이름 변경 후보와 영향 범위 (제안만)
- 문서 후보: strategy_9_s1_put_insurance_spec_v0.3.md.
- strategy_id 후보: track9_s1_put_insurance 또는 strategy_9_s1_put_insurance.
- 기존 track9_event_overnight_insurance와 v0.2 path는 역사적 alias/retired mapping으로 보존.
- 영향: core class/strategy_id, resolve_track9, registry, config schema/key, tests/fixtures, persisted state, position provenance, Control Tower labels, metrics/logs, traceability/matrix/scenario docs. 실제 변경 없음.

## 9. 상태
Draft / unverified / unapproved. 기존 U/G/I IDs 유지. 코드 변경·테스트·Git operations·commit/push·KIS Live 주문 없음.

## S9 user decision amendment (2026-10-12)
- S1 U-ID를 유지하고 S5 신규 U 항목은 S5-U16…S5-U20으로 분리한다.
- S9는 S1 short PUT exposure가 0이어도 독립 lot으로 DTE7 rollover 정책까지 보유한다.
- lot별 stop: current premium <= 50% of that lot's actual entry fill price -> close that lot's remaining quantity.
- lot별 trailing: when premium first reaches 2.00x that lot's actual entry fill price, start high-water tracking; close when premium falls 10% from its own high-water mark.
- DTE7 rollover applies only to lots not already closed by stop/trailing. Exact DTE calendar/trading semantics and execution time remain validation blockers. Draft only; no code/tests/live order.

## User-confirmed DTE7 and recovery policy (2026-10-12)
- DTE uses trading days. Rollover decision/execution reference time is 11:00 KST (Asia/Seoul).
- If next-month expiry is not listed at 11:00, do not substitute a different contract or submit an order; keep monitoring and trade only after listing plus full contract/quote/liquidity/cost/risk preflight.
- Restart must restore each lot's actual entry fills, remaining filled quantity, exact contract/expiry identity, trailing armed flag, high-water mark and last processed market-data timestamp. Missing/mismatched state blocks entry/rebuy/roll until broker position/fill reconciliation.
- Use only fresh authoritative quotes for the same contract. Reconcile partial/late fills and actual positions; ACK/cancel request is not final fill/cancel evidence.
- Simultaneous per-lot exit priority: trailing exit > stop-loss > DTE7 rollover. After an exit trigger, no rollover/re-entry for that lot in the same evaluation cycle; reconcile actual fills before advancing.
- Calendar source, freshness limits and operational implementation remain validation items; all scenarios NOT_RUN.


## S9 validation gate addendum (2026-10-12; BLOCKED/NOT_RUN)
- Calendar source: KRX official derivatives schedule; exact expiry/listing cross-check via authoritative Option Master. DTE7 inclusion/off-by-one and exceptional holiday vectors remain NOT_RUN.
- Quote freshness threshold: UNSET; confirm KIS option REST/WS timestamp semantics and derive approved threshold from VTS observations. No arbitrary age limit.
- Restart: restore each lot's actual entry executions, residual filled quantity, contract/expiry, trailing flag, high-water mark and last market-data timestamp; reconcile broker orders/fills/positions before actions.
- Evidence and scenarios: see `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`. No implementation or runtime PASS implied.

---
## v0.6 — S9 D-4 exit and third-strike liquidity
The user's latest rule supersedes the earlier DTE7 rollover proposal: S9 must enter forced liquidation at D-4 trading-session gate, 11:00 KST; no rollover past this gate. Count remaining KRX trading sessions against authoritative exact expiry and fail closed on calendar/identity uncertainty. If S1 and S9 expire together, close priority is S1 → S9, without allowing unresolved S1 status to indefinitely starve S9's mandatory exit. If the third strike is illiquid/stale/wide, wait and recheck the same contract using a fresh quote; never invent a price or silently substitute a strike. Liquidity thresholds and retry interval remain UNSET until evidence-backed. DRAFT / VERIFYING / UNAPPROVED.
