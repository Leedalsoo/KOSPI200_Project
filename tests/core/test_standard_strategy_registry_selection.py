import pytest

from core.strategy.standard_registry import (
    STANDARD_STRATEGY_KEYS,
    build_standard_strategy_registry,
)


S2_STRATEGY_ID = "track2_asymmetric_trap"
S2_STRATEGY_VERSION = dict(STANDARD_STRATEGY_KEYS)[S2_STRATEGY_ID]


def test_registry_builds_only_requested_s2_strategy():
    registry = build_standard_strategy_registry(strategy_ids={S2_STRATEGY_ID})

    strategy = registry.get(S2_STRATEGY_ID, S2_STRATEGY_VERSION)
    assert strategy.strategy_id == S2_STRATEGY_ID
    assert strategy.version == S2_STRATEGY_VERSION

    with pytest.raises(KeyError, match="strategy not registered"):
        registry.get("TRACK1_TAIL_DEFENSE", "1.2.0")


def test_registry_rejects_unknown_strategy_id():
    with pytest.raises(ValueError, match="STRATEGY_SELECTION_UNKNOWN_IDS"):
        build_standard_strategy_registry(strategy_ids={"unknown_strategy"})


@pytest.mark.parametrize("selection", [set(), (), [""], ["track2_asymmetric_trap", " "]])
def test_registry_rejects_empty_or_invalid_selection(selection):
    with pytest.raises(ValueError, match="STRATEGY_SELECTION_EMPTY_OR_INVALID"):
        build_standard_strategy_registry(strategy_ids=selection)


def test_registry_rejects_string_instead_of_id_collection():
    with pytest.raises(ValueError, match="STRATEGY_SELECTION_MUST_BE_ITERABLE_OF_IDS"):
        build_standard_strategy_registry(strategy_ids=S2_STRATEGY_ID)
