# Strategy 1–9 integrated decision matrix — Strategy 2 delta v0.6

- 작성일: 2026-11-10
- 상태: USER-APPROVED SUPPORTING MATRIX v0.6 / IMPLEMENTATION BLOCKERS OPEN
- 기준: S2 통합 명세 v0.5; Current Baseline v2 SHA-256 `3FDC91266DE43EAB12EDAC50EB35200F824BC352024D21374F1DB93CD3880CB4`
- 본 문서는 S2 delta이며 전체 Strategy 1–9 matrix를 대체하지 않는다.

## 1. 결정 register — U16~U21

| ID | 확정된 정책 부분 | 잔여 차단 항목 |
|---|---|---|
| U16 | 확인된 실제 체결량 기준 부족 수량만 보정; 취소/fill/position 재대사; 상태 불명 시 RECONCILIATION_REQUIRED; BID/ASK 지정가; 추가 retry 최대 3회; 총 120초; 최종 실패 시 기체결 레그 전체 청산 정책 및 그룹 차단 | retry 간격·가격 재산정 시점; 실제 주문/Runtime 구현은 별도 승인 필요 |
| U17 | ATM tie는 지수 가격 이하 낮은 상장 strike | monthly expiry source, listed offset strike, tick/strike rounding, volatility boundaries |
| U18 | MID mark; denominator=initial group net premium received; fees/slippage in realized & unrealized P&L; stop/trailing formula structure | stop percentage, trailing pullback percentage, valid MID/freshness |
| U19 | broker/exchange-held positions authoritative; persisted execution ledger supplementary | mismatch reconciliation and resume/stop disposition; durable restore evidence |
| U20 | cancel-confirmed + reconciled zero-fill leg advances to next leg | partial/reject/race handled under U16; late-fill/order-position reconciliation |
| U21 | conservative alternate price fallback; block if no valid fallback | quote age/spread limits, units, fallback formula/priority, tick rounding |

## 2. F01–F29 영향 행

| ID | S2 disposition as of v0.6 | Status |
|---|---|---|
| F08 contract/expiry | U17 tie-break selected; monthly series and exact expiry source still required | BLOCKED_INPUT/SPEC |
| F15 partial/reject/cancel | U16 repair intent; U20 zero-fill cancel exception; detailed recovery incomplete | BLOCKED_SPEC |
| F17 inventory/exposure | U19 account position is authoritative; durable source/reconciliation not implemented | BLOCKED_INPUT |
| F18 stop loss | group cumulative net loss vs initial group net premium received; threshold unset | BLOCKED_SPEC |
| F19 trailing | pullback from maximum cumulative net profit; threshold unset | BLOCKED_SPEC |
| F21 close scope/qty | actual remaining lots and reconciled account position required | BLOCKED_INPUT |
| F22 P&L/fees/slippage | MID marks; fees/slippage included in realized and unrealized; denominator set | BLOCKED_INPUT |
| F24 lifecycle/provenance | broker positions primary, execution ledger supplementary; mismatch policy unresolved | BLOCKED_INPUT |

Unchanged F01–F14, F16, F20, F23, F25–F29 remain governed by v0.4 historical matrix and the consolidated v0.5 specification. No prior “resolved” label means Runtime PASS.

## 3. Cross-system and group gates

- Four standard KOSPI200 option contract identities, exact monthly expiry, multiplier and tradability: BLOCKED until authoritative KIS source evidence exists for every leg.
- Group premium, max-loss, stress, margin, fees/slippage and account aggregate exposure: BLOCKED until versioned risk settings and group-level preflight evidence exist.
- Quote validity/pricing: BLOCKED until max age, max spread, fallback formula, tick rounding and per-leg limit policy are approved and evidenced.
- Runtime order progression, partial-fill repair, cancel race, restart reconciliation and group P&L exit: NOT VERIFIED.
- S2 new entry remains BLOCKED; no Live/REAL_VTS/account/order authorization.

## 4. Code and verification status

Static evidence from S24/S28 and current source inspection:
- Four-leg plan adapter and sequence validator exist, but full Runtime progression is not evidenced.
- Strategy state is mutated at proposal time; fill-confirmed activation is not evidenced.
- Contract source selects nearest expiry and ATM PUT/CALL pair; monthly filtering and all four offset contract identities are not evidenced.
- Option P&L exit method returns no signals; group P&L stop/trailing is not wired.
- S26 is validation-only controls; S27 preflight is blocked; S28 overall S2 verdict remains BLOCKED_RUNTIME_WIRING / PSB_UNVERIFIED.

## 5. Acceptance gates — all NOT RUN or BLOCKED

G03 contract identity/expiry/multiplier; G04 order/fill recovery; G06 P&L/exit; G08 group/account risk; G09 durable recovery; G10 test traceability remain blocked. S2-V03 scenario design is not Runtime acceptance. No tests or market/API calls were executed for this document draft.

## 6. Status

Planning/document delta only. User-approved supporting matrix under No.1500; this errata aligns existing No.1501–1505 decisions. Documentation only. No code edits, tests, Runtime, Replay, REAL_VTS, KIS API, Live/account API, actual orders, commit or push.
