"""Track 4 Gamma Scalping — Standard Core 순수 전략 구현.

원격 Legacy의 price_high/low/close는 실제 OHLC가 아니라 동일 tick.last_price를 세 버퍼에 반복 저장했다.
현재 Canonical/Market 계층에도 authoritative OHLC source가 없으므로 fake OHLC를 유지하지 않는다.
기존 Legacy의 실제 계산 결과를 보존하기 위해 연속 관측 tick 가격의 평균 절대 변화량을 deadband 원천으로 명시한다.
기존 ×5 정규화와 0.2~0.6 clamp는 유지하여 Gamma Scalping의 동적 Delta Hedge 목적을 보존한다.

현재 Canonical MarketState에 gamma/delta/ATR/Theta/equity가 모두 없으므로
Track4MarketInput을 명시적 입력 DTO로 둔다. 입력이 없는 경우 synthetic 값을 생성하여
실제 기능이 작동하는 것처럼 처리하지 않는다.

순수 ATR/Deadband, Basecamp 조건, Delta Hedge Intent, Theta Guard, Profit Trailing을
구현하고 독립 테스트한다. 이후 Registry/Runtime 연결은 전략 개별 기능 검증 뒤 진행한다.

원격 Track4 원문의 수치와 실행 의미를 유지하면서 실행 객체 생성은 제외했다.
"""


## 원격 원문 기반 Standard Core 이식 — Track 4 Gamma Scalping


### 보존 기능


# Legacy OrderRequest, MarketTick, TimeService, Broker 직접 호출은 Standard Strategy에 복사하지 않는다. Strategy는 Signal/순수 판단을 만들고, 실제 FUT hedge 주문·가격·IOC/fallback은 Decision/OMS/Environment Execution으로 전달한다.


