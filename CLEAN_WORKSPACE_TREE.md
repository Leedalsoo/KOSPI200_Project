```plain text
OptionProject/
├── README.md
├── ARCHITECTURE.md
├── DEPENDENCY_RULES.md
├── PROJECT_STATUS.md
├── AGENTS.md
├── pyproject.toml
├── BASELINE_AUDIT.md
├── MIGRATION_RULES.md
├── ASSET_CLASSIFICATION.md
├── RUNTIME_TRACE.md
├── FEATURE_PRESERVATION_MATRIX.md
├── PHASE1_BOUNDARY_LOCK.md
├── CORE_STRATEGY_BOUNDARY.md
├── ENVIRONMENT_BUNDLE_BOUNDARY.md
├── RUNTIME_UI_BOUNDARY.md
├── LEGACY_QUARANTINE.md
├── ASSET_MIGRATION_MAP.md
├── TEST_MIGRATION_POLICY.md
├── STANDARD_CONTRACTS_SPEC.md
├── CANONICAL_DTO_SPEC.md
├── MARKET_TIME_CONTRACT_BOUNDARY.md
├── BROKER_LIFECYCLE_CONTRACT_BOUNDARY.md
├── PHASE4_ASSET_CLASSIFICATION.md
├── CONDUCTOR_DECOMPOSITION.md
├── RESPONSIBILITY_RELOCATION.md
├── STRATEGY_ASSET_DISCOVERY.md
├── OPTION_DOMAIN_SOURCE_BOUNDARY.md
├── MIGRATION_DECISION_MATRIX.md
├── ARCHITECTURE_SKELETON.md
├── ARCHITECTURE_LINT_SPEC.md
├── FEATURE_MIGRATION_PROTOCOL.md
├── MINIMAL_CORE_PIPELINE_SPEC.md
├── PHASE5_ENTRY_GATE.md
├── application/
│   ├── use_cases/
│   ├── runtime_controller/
│   ├── environment_hub/
│   └── composition/
├── core/
│   ├── domain/
│   ├── strategy/
│   ├── signal/
│   ├── decision/
│   ├── risk/
│   ├── position/
│   ├── oms/
│   ├── option/
│   ├── runtime/
│   └── sensor/
├── contracts/
│   ├── market_data/
│   ├── clock/
│   ├── broker/
│   ├── account/
│   ├── execution/
│   ├── environment/
│   ├── runtime/
│   ├── lifecycle/
│   ├── status/
│   └── option/futures/track4 contracts and providers
├── environments/
│   ├── high_speed/
│   ├── virtual/
│   ├── paper/
│   └── live/
├── infrastructure/
│   ├── persistence/
│   ├── telemetry/
│   ├── time/
│   └── kis/
├── interfaces/
│   └── control_tower/
├── support/
│   ├── configuration/
│   └── observability/
└── tests/
    ├── unit/
    ├── integration/
    ├── e2e/
    ├── regression/
    ├── safety/
    ├── architecture/
    ├── virtual/
    ├── high_speed/
    ├── paper/
    ├── live/
    └── control_tower/

LEGACY EXCEPTION:
├── shared/
│   └── contracts/canonical.py
└── shared는 Standard canonical DTO SSoT와 중복되는 legacy compatibility artifact로 취급하며 신규 production 코드의 정상 경로로 사용하지 않는다.
```

현재 Notion의 실제 폴더 페이지와 파일 배치를 기준으로 갱신했다. 테스트 파일은 production 폴더(core/application/contracts)에서 제거하여 tests 하위로 이동했다. root의 구현 파일도 각 책임 소유 폴더로 이동했다.