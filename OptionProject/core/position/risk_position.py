"""- Reference/VSSF PositionManager는 실제 체결의 side, qty, price, symbol 등을 받아 aggregate position을 관리한다.
- PaperPositionSnapshot/현재 canonical PositionSnapshot에는 side가 없으므로 canonical snapshot에서 side를 추측하지 않는다.
# - 따라서 authoritative Position source에서 직접 RiskPositionInput을 구성한다."""

## 목적
# Authoritative PositionManager 상태의 side/qty를 Standard Core Risk 입력으로 전달하는 최소 Adapter 계약.
## 확인된 기준
## 계약