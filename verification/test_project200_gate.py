"""Unit tests for Project200 Deterministic Verification Gate."""

from pathlib import Path

from verification.project200_gate import (
    Check,
    check_branch,
    check_required_files,
    check_runtime_evidence,
    check_runtime_path_test,
    check_runtime_wiring_source,
    check_source_literals,
    check_test_suite,
    main,
)


def test_gate_check_branch():
    c = check_branch()
    assert isinstance(c, Check)
    assert c.name == "branch_project200"
    assert c.status in {"PASS", "FAIL"}


def test_gate_check_required_files():
    c = check_required_files()
    assert isinstance(c, Check)
    assert c.name == "required_files"
    assert c.status == "PASS"


def test_gate_check_source_literals():
    c = check_source_literals()
    assert isinstance(c, Check)
    assert c.name == "no_known_fake_operational_literals"
    assert c.status == "PASS"


def test_gate_check_runtime_wiring_source():
    c = check_runtime_wiring_source()
    assert isinstance(c, Check)
    assert c.name == "runtime_wiring_source"
    assert c.status == "PASS"


def test_gate_check_runtime_evidence():
    c = check_runtime_evidence()
    assert isinstance(c, Check)
    assert c.name == "runtime_evidence_probe"
    assert c.status == "PASS"


def test_gate_main_returns_zero_on_pass():
    exit_code = main()
    assert exit_code == 0
