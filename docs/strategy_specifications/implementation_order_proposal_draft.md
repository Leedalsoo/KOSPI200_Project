# Strategy 1~9 구현 순서 제안서 (draft)

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved
- 문서 제안일 뿐이다. 코드·테스트·config/manifest·commit/push·KIS Live 주문은 수행하지 않았다.
- 이 문서의 승인도 전략 구현 승인으로 해석하지 않는다. 각 전략의 정확한 명세 버전별 별도 승인이 필요하다.

## 제안 순서

| 순서 | 전략 | 선행 조건 | 필수 검증 | 승인 게이트 |
|---:|---|---|---|---|
| 0 | 공통 데이터·주문·위험 차단 요인 | KRX calendar, exact Option Master, KIS VTS quote route, cancel/fill/position mapping | multi-day/multi-contract REAL_VTS; source vs receive timestamps; partial/late fill; runtime risk gate | 공통 기술 기준 별도 승인 |
| 1 | S1 Tail Defense | S1 명세 승인; U28 기준점 규칙; 실제 option-only hedge resolver | ±2.5pt boundary, listed strike mapping, short cap 10, partial fills, hedge lifecycle, D-4 exit, position/PnL | S1 구현 별도 승인 |
| 2 | S9 S1 풋 보험 | S1 실제 lot read model, exact expiry, D-4 11:00, rank 4/3 유동성 | S1 target→0, pending buy cancel, rank3 wait/recheck, duplicate close prevention, D-4 boundary | S9 구현 별도 승인 |
| 3 | S5 Gap Divergence | whipsaw event definition and session_end_action resolved; gap source/fills available | gap boundary, 1pt advance before/after hedge, 2 whipsaws, cancel race, 30m cutoff, REAL_VTS replay | S5 구현 별도 승인 |
| 4 | S6 Daily Tail Insurance | S6 v0.4 user-confirmed no-retry policy; exact daily contract and quote source | 11:00 boundary, 10m zero-fill + both cancels, late/partial fill, persisted no-retry fence, 15:10 exit, fees/slippage, restart | S6 구현 별도 승인; REAL_VTS/replay NOT_RUN |
| 5 | S7 Weekly Volatility Skew Insurance | Mon/Thu contract identities, skew source, retry/cutoff rules | two concurrent sets, 10m timeout, 15:00 cutoff, expiry/cancel/fill race | S7 구현 별도 승인 |
| 6 | S8 Monthly Strangle | official calendar/exact expiry; DTE10; remove old 200,000 KRW gate; common risk enforcement | DTE10 boundary, 3 trading-day retry over holidays/weekends, 10m timer, one-leg fill, account aggregation | S8 구현 별도 승인 |
| 7 | S2 Asymmetric Trap | feature source/units and four-leg limits verified; common OMS stable | independent leg lifecycle, cancel-confirm then remaining qty, late fill, stop/trailing/time exit, max loss/margin | S2 구현 별도 승인 |
| 보류 | S3 Statistical Arbitrage | enabled=false, capital_gate_min=null | No.956 scope, futures calendar identity, spread payoff/margin/risk | readiness and explicit release approval |
| 보류 | S4 Gamma Scalping | enabled=false, capital_gate_min=null | actual option lots/Greeks, futures hedge lifecycle, margin | readiness and explicit release approval |

## 전략별 공통 수락 조건
1. 정확한 명세 버전과 범위가 사용자 승인됨.
2. 필수 설정이 non-null, 검증 완료, version/hash 기록됨.
3. 계약 identity/만기 및 공식 거래일 달력이 확인됨.
4. quote source/receive time, freshness, bid/ask/depth, tick/price limit이 검증됨.
5. 주문 상태·취소 확정·부분/늦은 체결·실제 포지션·전략별 lot 귀속이 대사됨.
6. 실제 production 경로에서 전략 및 계좌 위험 게이트가 잘못된 노출을 차단하는 증거가 있음.
7. 정상/경계/부분체결/거절/취소경합/stale quote/restart/만기/전략간 중복/위험한도 초과 시나리오가 포함됨.
8. 기존 test, REAL_VTS, synthetic, virtual evidence를 구분해 보고함.
9. diff는 승인 범위만 포함하고 무관한 변경은 보존함.
10. focused/regression/E2E PASS 이후에도 commit/push는 사용자 승인 규칙을 따름.

## 현재 공통 차단 요인
No.1232에서 관측된 77,310 WS frames 중 H0IOASP0 option order-book frame은 0건이었다. REST 요청에는 rate-limit 관련 BLOCKED 응답이 있었다. 따라서 옵션 호가 신선도/유동성과 실제 orderbook 근거가 아직 충분하지 않다. 이는 S1/S2/S5/S6/S7/S8/S9의 옵션 가격과 S3/S4의 시장/헤지 준비도에 영향을 준다. 필수 authoritative input이 확보되기 전에는 전략 구현 단계로 진행하지 않는다.

사용자 확인 질문은 cross_strategy_conflict_review_draft.md의 단일 목록만 사용한다. 검증 가능한 기술 수치는 질문 대신 UNSET 설정과 검증 계획으로 관리한다.


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## S6 confirmed no-retry gate and calendar/quote prerequisites
- S6 stage must test the user-confirmed policy: if no fill occurs within 10 minutes and both CALL/PUT orders are confirmed cancelled with actual fill/position reconciliation, end entry for the day and prevent retry through a new strike rank or process restart.
- S6, S7 and S8 do not share a common retry count/window: S6 no retry under the stated condition; S7 retry until 15:00 KST per Mon/Thu set; S8 retry window three trading days after monthly start. The OMS terminal-state and cancel/fill reconciliation contract remains common.
- Before S1/S9/S8 implementation, acquire official KRX calendar notices and exact option expiry master YYYYMMDD; candidate dates in `trading_day_boundary_table_draft.md` are UNSET, not executable dates.
- Before any strategy can enter, No.1157 subscription rotation and No.1232 quote timestamp/capability gaps must be closed. Collect multi-day/multi-contract update intervals, quote age, depth, spread, and 5th/6th strike quote/remaining quantity/volume distributions. Numeric thresholds remain UNSET and block new orders until validated and approved.

## S6/S7/S8 retry distinction and common market-data gate

S6's same-day no-retry intent is confirmed, but its runtime no-retry fence and cancel/fill race are unverified. S7 retains Mon/Thu retry through 15:00 KST; S8 retains its three-trading-day window with day-three 15:00 cutoff. For all three, implementation is blocked until authoritative order/fill/position reconciliation is demonstrated. No.1157 rotation requests are not broker ACK; No.1232 reported 77,310 WS frames with zero H0IOASP0 option order-book frames in the examined set. Collect multi-day/multi-contract source/receive time distributions, quote age, depth, spread, and 5th/6th strike OI/volume/remaining quantity. Quote freshness/liquidity numeric limits remain null/UNSET and block new entries until evidence-based validation and user approval.
