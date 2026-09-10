"""Test Track3 Statistical Arbitrage — test specification.

- 15:15 이상이면 다른 청산 조건보다 먼저 MARKET_CLOSE_FLATTEN, cooldown=20.
- 청산 적용 후 active position/group/legs가 초기화되고 last_exit_z_score와 cooldown이 기록되는지 검증한다.
- SHORT spread에서 Z >= 3.5, LONG spread에서 Z <= -3.5이면 STOP_LOSS, cooldown=40.
- holding_ticks >= max_holding_ticks이면 TIMEOUT_EXIT, cooldown=20.
- convergence + economic profitability + group integrity가 모두 충족될 때만 CLOSED.
- 경제성 기준은 current_pnl - fees - estimated_cost >= -5000.
- HIGH_VOLATILITY의 current PnL > 10,000 및 GAP의 convergence + PnL > 5,000 예외를 각각 검증한다.
"""
