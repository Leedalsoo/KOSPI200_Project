# Strategy 2 — Asymmetric Trap 통합 명세 v0.5

- 작성일: 2026-11-10
- 상태: **USER-APPROVED SPEC v0.5 / OPEN IMPLEMENTATION BLOCKERS** — 명세 기준 승인; Runtime/구현/주문 경로는 별도 승인 필요
- 기준 브랜치: `cleanup/p2-quarantine-20261026`
- 조사 기준 HEAD: `3cc0e677848f99315e002b448c771ca2ffc72813`
- Current Baseline v2 SHA-256: 3FDC91266DE43EAB12EDAC50EB35200F824BC352024D21374F1DB93CD3880CB4
- 목적: v0.4 본문/부록, 보조 문서, S24~S28 검증 기록 및 S2-U16~U21 사용자 결정을 통합한 승인 명세다. 2026-11-10 정정은 No.1501~1505의 기존 결정을 반영하며 새로운 정책을 추가하지 않는다.
- 본 v0.5 명세는 No.1500에서 사용자 승인되었다. 이번 정정은 이미 승인된 No.1501~1505 결정을 문서에 일치시키는 편집이며, 코드 구현·Runtime/OMS 연결·Runtime E2E·Replay·실거래 권한을 부여하지 않는다.

## 1. 적용 우선순위와 상태

1. 사용자의 직접 지시 및 Current Baseline v2
2. 확정된 S2 결정 기록 No.1491~1499
3. 본 v0.5 통합 초안
4. v0.4 및 이전 S2 보조 문서 — 이력/근거로 보존

U16~U21의 결정된 정책 부분은 본 문서에 반영한다. 결정되지 않은 세부사항은 UNSET/BLOCKING으로 유지한다. 이 문서의 모든 정책은 검증·구현 완료를 뜻하지 않는다.

## 2. 전략 구조 및 상품

Asymmetric Trap은 안쪽 PUT/CALL 매수와 바깥쪽 PUT/CALL 매도로 구성되는 네 레그 구조다.

| 순서 | Leg ID | 상품 | 방향 | 목표 수량 |
|---:|---|---|---|---:|
| 1 | inner_put_buy | 일반 KOSPI200 옵션 PUT | BUY | 1 |
| 2 | inner_call_buy | 일반 KOSPI200 옵션 CALL | BUY | 1 |
| 3 | outer_put_sell | 일반 KOSPI200 옵션 PUT | SELL | 1 |
| 4 | outer_call_sell | 일반 KOSPI200 옵션 CALL | SELL | 1 |

- Mini 옵션, Futures hedge, 추가 overlay leg는 사용하지 않는다.
- 네 계약 모두 정확한 월물 만기(YYYYMMDD), 표준 상품 여부, strike, option type, broker symbol, multiplier, tradability가 KIS authoritative source로 확인되어야 한다.
- 네 계약 중 하나라도 identity 또는 필수 값이 확인되지 않으면 그룹 전체 신규 진입은 BLOCKED/UNAVAILABLE.
- `ZERO_COST`라는 이름은 경제적 사실을 보장하지 않는다. 실제 fill, MID mark, multiplier, fees 및 slippage로 그룹 비용과 손익을 계산한다.

## 3. 구조 선택 및 진입 조건

### 3.1 변동성 구조

| 조건 | 구조 | 안쪽 BUY | 바깥쪽 SELL |
|---|---|---|---|
| active_vol / base_vol <= low_vol_ratio | WIDE | PUT ATM−5.0pt / CALL ATM+5.0pt | PUT ATM−10.0pt / CALL ATM+10.0pt |
| 그 외 | NARROW | PUT ATM−2.5pt / CALL ATM+2.5pt | PUT ATM−7.5pt / CALL ATM+7.5pt |

`low_vol_ratio=0.85`는 PROVISIONAL. active/base 정의·산식·window·sample sufficiency·freshness·경계값은 미확정이다. base_vol<=0, 입력 stale/mismatch 또는 비율 산출 불가 시 진입 차단.

### 3.2 기존 진입 feature 집합

아래 feature 집합은 삭제·완화하지 않는다. 단, 정의·단위·source·기간·경계·freshness가 검증되지 않은 값은 승인 파라미터가 아니다.

- Bollinger Band Width 조건
- volume Z-score > 3.0
- abs(OBI) > 0.5
- Futures basis > 0.3 — 단위/부호 미확정
- abs(price − POC) > 1.0pt 및 POC 위/아래 위치
- POC 위: put_iv < call_iv; POC 아래 또는 같음: call_iv < put_iv
- active/base volatility ratio 기반 WIDE/NARROW 선택

BBW 산식·window, Z-score sample, OBI source/depth, basis 단위·동기화, POC 정의, IV expiry/strike identity, volatility source와 각 feature freshness는 미확정이다. 누락·stale·mismatch·PROVISIONAL 입력은 fail-closed.

## 4. ATM·행사가·만기 결정 (S2-U17)

- ATM 후보 두 상장 행사가의 지수 가격까지 거리가 동일하면 지수 가격 이하의 낮은 행사가를 선택한다. (No.1492)
- 이 규칙은 tie-break만 확정한다.
- 실제 상장 계약 존재 확인, strike offset 적용 후 listed strike 매핑, strike/tick rounding, exact monthly expiry 선택·공식 source, volatility 경계는 미확정.
- nearest expiry를 monthly expiry로 간주하지 않는다. 월물임을 확인할 authoritative series/calendar 기준이 없으면 BLOCKED.

## 5. 월물 lifecycle

- 대상 expiry series는 monthly only. 일물/주물은 미승인.
- 월물 시작 후 첫 3일에만 진입을 평가하고, 매일 15:00 KST 이후 신규 진입을 금지한다.
- 월물당 최대 1 cycle. 같은 월물 내 재진입 금지.
- 만기일 15:10 KST에 terminal close 절차를 시작한다. 15:10 도달이나 주문 ACK는 flat 증거가 아니다.
- 모든 주문이 terminal이고 authoritative position/lot가 flat으로 대사되어야 CLOSED 처리 가능.
- 공식 거래일·월물 시작일·만기일·세션 cutoff의 authoritative calendar/broker semantics는 미검증이며 추정 금지.

## 6. 순차 주문 및 예외 처리 (S2-U16/U20)

기본 제출 순서는 §2 표의 1→4 순서다. 네 레그를 한꺼번에 제출하지 않는다. 각 주문은 10분 timeout 정책을 유지하되, timeout 수치의 실제 운영 적용은 별도 검증 전까지 validation-only 초안이다.

### 6.1 정상 진행
- 이전 레그의 fill/order/position 상태를 대사한 후 다음 순서의 레그를 평가한다.
- 두 안쪽 BUY의 보호 상태를 확인하기 전 바깥쪽 SELL을 임의로 앞당기지 않는다.
- ACK/submit/cancel request는 fill/terminal 상태가 아니다.

### 6.2 U20 — 취소 확인 후 0체결
- 취소 요청과 취소 확정을 구분한다.
- 취소가 확정되고 execution/fill 및 position 대사 결과 해당 레그의 체결 수량이 정확히 0임을 확인하면 해당 레그를 ZERO_FILL_CONFIRMED로 기록하고 다음 순서의 레그로 진행한다. (No.1498)
- 이는 순차 진행 포인터만 다음 레그로 이동한다는 뜻이다. 0체결 레그가 목표 수량을 충족한 것으로 간주되거나 그룹 ACTIVE/월물 cycle consumed로 처리되는 것은 아니다. 네 레그 목표 수량이 모두 실제 체결·대사되거나 U16에 따른 승인된 보정이 완료되기 전에는 ACTIVE 금지; 미충족이면 RECONCILIATION_REQUIRED/BLOCKED.
- 취소 확정 전, fill 조회 미완료, late fill 가능성, order/position 불일치가 있으면 진행 금지.
- 이 0체결 예외는 기존 초안의 “zero-fill이면 자동 다음 레그 금지” 문구를 대체한다.

### 6.3 U16 — 부분체결·거절·취소 경합
- 원주문의 취소/terminal 상태, 실제 체결 내역 및 포지션을 먼저 재대사하고, 확인된 실제 체결량을 기준으로 부족 수량만 보정한다. (No.1501)
- 체결/취소 상태가 불명확하면 중복 주문과 blind retry를 금지하고 RECONCILIATION_REQUIRED로 그룹을 차단한다. 각 retry 전에도 원주문·보정주문의 취소/terminal 상태, fill 및 position을 재대사한다. (No.1502–1503)
- 보정 주문 가격은 최우선 BID/ASK 기반 지정가를 사용한다. (No.1505)
- 최초 보정 주문 이후 추가 retry는 최대 3회이며, 최초 보정 주문 제출부터 전체 미체결 수량 보정 완료까지 최대 120초다. 둘 중 하나라도 초과하면 보정 실패다. (No.1503–1504)
- 보정이 최종 실패하면 이미 체결된 레그를 반대 방향 주문으로 전체 청산하는 정책을 적용하고 그룹을 차단한다. 이는 정책 결정일 뿐 실제 청산 주문 제출 또는 자동화 구현 승인이 아니다. (No.1501)
- 미확정 항목은 retry 간격 및 가격 재산정 시점이다. 이 두 항목과 U21의 quote age/spread/fallback 경계가 해결되기 전에는 해당 경로를 구현 가능하다고 간주하지 않는다.
## 7. 옵션 그룹 P&L·손절·트레일링 (S2-U18)

- 평가가격은 각 옵션 BID/ASK의 중간값 MID. (No.1493)
- MID는 손익 평가용 mark 기준이며 주문 제출가격을 뜻하지 않는다. 주문가격은 별도 U21 유효성/fallback 규칙을 통과해야 한다.
- 순비용 비율의 분모는 최초 진입 시점의 그룹 순프리미엄 수취액. (No.1494)
- 수수료와 슬리피지는 실현 손익과 평가 손익 모두에 반영. (No.1495)
- 손절: 누적 순손실이 최초 그룹 순프리미엄 수취액 대비 확정 비율에 도달하면 청산.
- 트레일링: 최대 누적 순이익에서 확정 비율의 되돌림이 발생하면 청산. (No.1496)
- 손절 비율과 trailing pullback 비율은 미확정. 이전 초안의 -30%, 30%, 50/100%, 85/88/90%는 승인 파라미터로 승격하지 않고 PROVISIONAL/UNSET으로 유지.
- 분모가 0 이하, MID 산출 불가, stale/missing quote, multiplier/fee/slippage 미확인, 실제 잔여 수량 불일치이면 해당 P&L trigger를 계산하지 않고 fail-closed.
- underlying/index price proxy를 option-group P&L로 사용하지 않는다.

## 8. 재시작 및 포지션 대사 (S2-U19)

- 재시작 복구 시 broker/exchange-held account positions가 기준 포지션이며, persisted execution ledger는 보조 자료다. (No.1497)
- 이 결정은 계좌 조회 API 호출 권한을 부여하지 않는다.
- broker position과 저장 원장 간 불일치 시 조정·중단·재개 절차, 미완료 주문·late fill·중복 이벤트 처리, durable state schema 및 복구 증거는 미확정.
- 불일치 또는 authoritative position 확인 불가 시 신규 진입·재개·flat 판정을 차단한다.

## 9. 호가·지정가·보수적 fallback (S2-U21)

- BID/ASK 누락, stale 또는 spread 한도 초과 시 보수적 대체가격 계산을 적용한다.
- 유효한 대체가격을 계산할 수 없으면 주문을 차단한다. (No.1499)
- max quote age, max spread 및 단위, fallback 산식/우선순위, tick rounding, 주문가격 상·하한 및 허용 slippage는 미확정.
- 이전 초안의 1-tick offset은 승인된 가격 정책이 아니다.
- 모든 값이 검증된 versioned config에 존재하지 않으면 신규 주문 BLOCKED.

## 10. Risk·preflight·provenance

첫 주문 전 4개 계약·호가·순프리미엄·최대손실·stress loss·margin·fees/slippage·계좌 aggregate exposure를 그룹 단위로 검증한다. 설정 누락/null/PROVISIONAL, group budget 미검증, multiplier/contract identity 불명은 BLOCKED.

각 run/group/leg/order/execution/position에는 strategy_id, group_id, leg_id, client_order_id, execution_id, expiry, contract identity, quantity, source/provenance, config version/hash, as-of/received timestamp를 연결한다. REAL_VTS, SYNTHETIC, DERIVED_SCENARIO, VIRTUAL_EXECUTION은 구분한다. Synthetic/derived는 validation-only이며 Production authoritative source가 아니다.

## 11. 코드 대조 결과 — 관찰 사실, 구현 승인 아님

기준 HEAD의 정적 조사 결과:

- `Track2ExecutionPlanAdapter`는 S2 signal을 4-leg plan으로 변환하고 sequence validator를 호출하는 경계를 제공한다. 이는 full Runtime progression E2E 증거가 아니다.
- 현재 strategy `evaluate()`는 proposal 시점에 `_trap_active`, entry fields 및 daily counter를 갱신한다. 실제 4-leg fill 완료 후에만 ACTIVE로 전환된다는 증거가 없다.
- `build_asymmetric_trap()`는 `UNRESOLVED_LIMIT_PRICE`와 legacy `limit_offset_ticks=1`을 노출한다. 이는 승인 가격 정책이 아니다.
- `Track2OptionContractSource.nearest_expiry()`는 nearest expiry를 고르며 monthly-series filter 증거가 없다. `select()`는 동일 ATM의 PUT/CALL pair 및 multiplier만 확인하며 네 offset leg 모두의 authoritative identity/multiplier/tradability를 입증하지 않는다.
- `build_track2_analytics_snapshot()`는 `instrument_identity=None` 및 generic provenance를 사용한다. 완전한 source timestamp/identity lineage가 확인되지 않는다.
- `evaluate_trap()`은 빈 sequence를 반환한다. Option-group P&L stop/trailing Runtime 경로는 미연결/미검증이다.
- S28 결과는 S2를 `BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED`로 판정했다. S26 validation-only controls 및 S27 blocked preflight는 이 결론을 대체하지 않는다.

## 12. 미결 항목 및 진입 차단표

| ID | 결정된 부분 | 여전히 미확정 / 차단 |
|---|---|---|
| U16 | 실제 체결량 기준 부족 수량만 보정; 취소·fill·position 재대사; 상태 불명 시 RECONCILIATION_REQUIRED; BID/ASK 지정가; 추가 retry 최대 3회; 총 120초; 최종 실패 시 기체결 레그 전체 청산 정책 및 그룹 차단 | retry 간격, 가격 재산정 시점; 구현/실제 청산 주문은 별도 승인 및 증거 필요 |
| U17 | ATM tie는 지수 이하 낮은 strike | exact monthly expiry source, listed strike mapping, tick/strike rounding, volatility boundaries |
| U18 | MID, 최초 그룹 순프리미엄 수취액 분모, realized/unrealized 모두 fees/slippage, stop/trailing 구조 | stop %와 trailing pullback %, MID freshness/validity, non-positive denominator behavior beyond fail-closed |
| U19 | broker/exchange position 우선, ledger 보조 | mismatch reconciliation, resume/stop policy, durable restore evidence |
| U20 | cancel confirmed + reconciled zero fill이면 다음 leg 진행 | partial/reject/cancel-race는 U16; event ordering/late-fill evidence |
| U21 | 보수적 fallback, 유효 fallback 없으면 block | quote age/spread limits, units, formula/priority, tick rounding |

## 13. 검증·승인 상태

- Specification: USER-APPROVED v0.5 (No.1500); 문서 정합성 정정은 No.1501–1505 결정 반영.
- S2 Runtime E2E / FAST-DETAILED parity: NOT RUN / BLOCKED_RUNTIME_WIRING.
- New entry: BLOCKED.
- KIS Live/REAL_VTS/account API/actual orders: 금지.
- 승인 범위는 명세/정책 기준에 한정된다. 코드 수정·테스트·Runtime/OMS 연결·Runtime E2E·Replay·주문 경로 활성화는 별도 승인 전 금지.
- 문서 버전 정합성 검토 결과: v0.4 파일명과 본문 v0.3, matrix v0.5 파일명과 본문 v0.4, traceability v0.2 파일명과 본문 v0.1, scenario plan v0.2 파일명과 본문 v0.1의 불일치를 확인했다. 본 v0.5는 새 통합 기준 초안이며 과거 파일을 덮어쓰지 않는다.

## 14. 근거

- No.1491 U16 base repair policy; No.1492 U17; No.1493 MID; No.1494 denominator; No.1495 fees/slippage; No.1496 stop/trailing structure; No.1497 restart position authority; No.1498 zero-fill progression; No.1499 conservative pricing fallback; No.1501 full-liquidation failure policy; No.1502 retry/time failure rule; No.1503 max 3 additional retries; No.1504 max 120 seconds; No.1505 BID/ASK limit pricing.
- No.1486 S24 spec-code gap matrix; No.1488 S26 implementation/validation; No.1489 S27 preflight; No.1490 S28 integrated regression.
- Companion draft files: decision matrix S2 delta v0.6, traceability S2 delta v0.3, scenario plan S2 delta v0.3.
