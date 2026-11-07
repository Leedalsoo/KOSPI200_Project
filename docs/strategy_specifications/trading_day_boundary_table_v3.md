# 거래일 경계표 v3 — KIS exact expiry 기반 후보(미승인)

작성일: 2026-10-14 KST  
상태: 검증 중 / 사용자 승인 전 / 운영 기준 아님  
정책: KRX 마스터·KRX 달력·둘째 목요일 추정은 사용하지 않는다. exact expiry는 성공한 KIS REST 응답의 `output1.futs_last_tr_date`만 인정한다.

## 월물 — 향후 12개월(2026-11 ~ 2027-10)

| KIS 마스터 월 라벨 | exact 만기 YYYYMMDD | D-4 | DTE10 진입 날짜 | 상태/사유 |
|---|---|---|---|---|
| 202611 | 20261112 | UNSET | UNSET | exact 만기 KIS VTS 5/5 성공. 연간 달력 완전성 미검증 |
| 202612 | 20261210 | UNSET | UNSET | exact 만기 KIS VTS 5/5 성공. 연간 달력 완전성 미검증 |
| 202701 | 20270114 | UNSET | UNSET | exact 만기 KIS VTS 5/5 성공. 연간 달력 완전성 미검증 |
| 202702 | UNSET | UNSET | UNSET | 마스터 라벨 존재; 개별 exact expiry 조회 미완료 |
| 202703 | UNSET | UNSET | UNSET | 마스터 라벨 존재; 개별 exact expiry 조회 미완료 |
| 202704 | UNSET | UNSET | UNSET | 마스터 라벨 존재; 개별 exact expiry 조회 미완료 |
| 202705 | UNSET | UNSET | UNSET | 현재 KIS 마스터 snapshot에 해당 표준 월물 라벨 없음 |
| 202706 | UNSET | UNSET | UNSET | 마스터 라벨 존재; 개별 exact expiry 조회 미완료 |
| 202707 | UNSET | UNSET | UNSET | 현재 KIS 마스터 snapshot에 해당 표준 월물 라벨 없음 |
| 202708 | UNSET | UNSET | UNSET | 현재 KIS 마스터 snapshot에 해당 표준 월물 라벨 없음 |
| 202709 | UNSET | UNSET | UNSET | 마스터 라벨 존재; 개별 exact expiry 조회 미완료 |
| 202710 | UNSET | UNSET | UNSET | 현재 KIS 마스터 snapshot에 해당 표준 월물 라벨 없음 |

## 위클리 — 현재 KIS 마스터에 존재하는 대표 계약

| 상품 구분 | 라벨 | 단축코드 표본 | exact 만기 YYYYMMDD | D-4 | DTE10 | 상태/사유 |
|---|---|---|---|---|---|---|
| 목요일 위클리 | 2610W3 | B09FGW942 | 20261015 | UNSET | UNSET | KIS REST 표본 5/5 성공; 연간 달력 미검증 |
| 월요일 위클리 | 2610W3 | BAFC2W942 | 20261019 | UNSET | UNSET | KIS REST 표본 3/5 성공; 2건 HTTP 500 / EGW00201; 연간 달력 미검증 |

## 경계 규칙

- D-4: 만기일 D=0을 제외하고 만기 전 네 번째 실제 거래일. 주말·공식 휴장·임시휴장을 제외한다.
- DTE: 오늘 이후 만기일까지의 실제 거래 세션 수(만기일 포함). DTE10은 이 값이 10 이상일 때만 참이다.
- 현재 휴장일 API는 완전한 연간 커버리지를 입증하지 못했고 사용자 승인 목록도 없다. 따라서 위의 D-4/DTE10은 계산값을 추정하지 않고 UNSET으로 유지한다.
- 단위 테스트는 달력 stub으로 계산 로직을 검증할 뿐, 운영 달력이나 전략 진입 승인을 의미하지 않는다.
- 아직 마스터에 상장되지 않은 월물/위클리의 exact expiry는 KIS에서 추정하지 않는다. 신규 상장 후 실제 마스터와 REST 응답이 확인될 때만 채운다.

## 관련 증거

- 마스터 ZIP: `verification/evidence/fo_idx_code_mts_20261014.zip`
- exact expiry 표본: `verification/evidence/kis_expiry_generalization_20261014_dda0ee9c.json`
- append-only exact expiry cache: `data/reference/kis/option_expiry/`
- 계산기: `core/trading_day_calculator.py`
- 상태: 표는 후보이며 승인되지 않았다.
