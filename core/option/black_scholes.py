"""표준 Black-Scholes-Merton 유럽형 옵션 가격·Greeks의 순수 계산 함수다.

외부 source를 조회하거나 risk-free rate, DTE, option type을 추정하지 않는다.
- 유럽형 옵션.
- S, K, sigma, T, r, q는 각각 underlying price, strike, annualized volatility,
  time-to-expiry in years, continuously compounded risk-free rate, continuous
  dividend yield.
- T와 r은 호출자가 authoritative source에서 공급한다.
- option_type은 명시적인 CALL 또는 PUT만 허용한다.

목적: Black-Scholes 유럽형 Greeks를 순수 계산으로 제공한다.

산식 및 가정: 표준 BSM 폐형식을 사용한다.

검증 참고: Cboe는 Delta/Gamma/Theta를 옵션 risk sensitivity의 핵심 지표로 설명한다.
Black-Scholes 유럽형 Greeks의 폐형식은
https://book.derivative-securities.org/Chapter_BlackScholes.html 및
https://quantpie.co.uk/bsm_formula/bs_summary.php 의 식과 대조했다.
"""




# 검증 참고: Cboe는 Delta/Gamma/Theta를 옵션 risk sensitivity의 핵심 지표로 설명한다. Black-Scholes 유럽형 Greeks의 폐형식은 https://book.derivative-securities.org/Chapter_BlackScholes.html 및 https://quantpie.co.uk/bsm_formula/bs_summary.php 의 식과 대조했다.
