"""Test Track4 Gamma Scalping — test specification.

- active_vol <= base_vol*0.85: Call ATM+2.5 / Put ATM-2.5.
- active_vol >= base_vol*1.30: Call/Put ATM.
- 15:15 이후 Basecamp 신규 진입 차단.
- Delta 절대값이 deadband 이하이면 hedge 없음.
- Delta가 deadband 초과이면 반대 방향 hedge intent 생성.
- hedge quantity가 100을 초과하지 않음.
- Delta hedge는 Theta guard 실패와 무관하게 작동.
- 입력 부족 시 synthetic market values를 생성하지 않음.
- ATR deadband가 0.2~0.6으로 clamp되는지 확인.
- equity threshold 미달 시 신규 hedge 차단 및 기존 hedge unwind intent.
- accumulated gamma profit이 theta decay cost 이하이면 Theta 확장 승인 거부.
- high-watermark 30,000 초과 이후 trailing 0.85/0.88/0.90 단계 확인.
- trailing trigger 후 high-watermark/active hedge 상태 초기화.
"""
