"""Independent verification entry point for the Standard Core full integration test.

This file is a verification harness specification. It must not be treated as a
production Runtime component and must not import Legacy Runtime modules.
"""

from core.strategy.test_standard_strategy_orchestrator_full_integration import (
test_all_contexts_match_standard_identity_manifest,
test_all_nine_actual_strategies_complete_full_lifecycle,
test_registry_accepts_strategy_payloads_without_optional_identity_field,
test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing,
test_same_fresh_registry_and_fixture_is_deterministic,
)


def run_independent_verification() -> None:
    """Run the five Standard Core integration assertions directly."""
    test_all_contexts_match_standard_identity_manifest()
    test_all_nine_actual_strategies_complete_full_lifecycle()
    test_registry_accepts_strategy_payloads_without_optional_identity_field()
    test_same_fresh_registry_and_fixture_is_deterministic()
    test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing()
    print("STANDARD_CORE_FULL_INTEGRATION_PASS")


if __name__ == "__main__":
    pass
    run_independent_verification()
