from __future__ import annotations

from types import MappingProxyType

from verification.export_s6_golden_baseline import canonical_json, jsonable


def test_jsonable_preserves_read_only_mapping_contents():
    value = MappingProxyType({"z": 2, "a": MappingProxyType({"metric": "AVAILABLE"})})
    assert jsonable(value) == {"a": {"metric": "AVAILABLE"}, "z": 2}


def test_canonical_json_is_stable_for_mapping_order():
    left = {"b": 2, "a": {"y": 1, "x": 0}}
    right = {"a": {"x": 0, "y": 1}, "b": 2}
    assert canonical_json(left) == canonical_json(right)


def test_jsonable_does_not_coerce_decimal_precision_to_float():
    from decimal import Decimal

    assert jsonable(Decimal("0.0000001234500")) == "0.0000001234500"
