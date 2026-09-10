Core와 실행환경 사이의 유일한 기술적 경계다.

작성 순서:

1. types.py

1. market_data.py

1. clock.py

1. account.py

1. broker.py

1. execution.py

1. environment.py

1. runtime.py

규칙:

- 특정 증권사 이름을 Contract에 넣지 않는다.

- Virtual 구현체 이름을 Contract에 넣지 않는다.

- DTO는 Canonical Model을 사용한다.

- Contract 변경은 4개 환경 영향 분석 후에만 허용한다.