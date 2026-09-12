"""Unit tests for Authoritative KIS Live Runtime Composition.

Verifies fail-loud error handling when credentials or dependencies are missing,
and confirms explicit assembly of the complete Live lifecycle graph without
fake defaults.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from application.composition.live_runtime_authoritative_composition import (
    AuthoritativeLiveRuntimeCompositionError,
    create_authoritative_kis_live_runtime_composition,
)
from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)
from contracts.futures_contract_master import (
    KisCurrentFuturesContractSource,
    KisFuturesContractIdentity,
)
from environments.live.contracts import LiveCredentialRef


def test_composition_fails_when_credentials_missing(monkeypatch):
    """Fail loud when required KIS environment variables are missing."""
    monkeypatch.delenv("KIS_REAL_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_REAL_APP_SECRET", raising=False)
    monkeypatch.delenv("KIS_REAL_ACCOUNT_NO", raising=False)

    with pytest.raises(AuthoritativeLiveRuntimeCompositionError) as exc_info:
        create_authoritative_kis_live_runtime_composition()

    assert "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE" in str(exc_info.value)
    assert "Live credentials incomplete" in str(exc_info.value)


def test_composition_fails_when_hts_id_missing(monkeypatch):
    """Fail loud when KIS_HTS_ID is missing despite having credentials."""
    monkeypatch.setenv("KIS_REAL_APP_KEY", "TEST_KEY")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "TEST_SECRET")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678-01")
    monkeypatch.delenv("KIS_HTS_ID", raising=False)
    monkeypatch.delenv("KIS_REAL_HTS_ID", raising=False)

    with pytest.raises(AuthoritativeLiveRuntimeCompositionError) as exc_info:
        create_authoritative_kis_live_runtime_composition()

    assert "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE" in str(exc_info.value)
    assert "HTS ID is required" in str(exc_info.value)


def test_composition_fails_when_account_missing(monkeypatch):
    """Fail loud when live account provider is missing (no synthetic account defaults)."""
    monkeypatch.setenv("KIS_REAL_APP_KEY", "TEST_KEY")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "TEST_SECRET")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678-01")
    monkeypatch.setenv("KIS_HTS_ID", "TEST_HTS")

    with pytest.raises(AuthoritativeLiveRuntimeCompositionError) as exc_info:
        create_authoritative_kis_live_runtime_composition()

    assert "AUTHORITATIVE_LIVE_RUNTIME_COMPOSITION_NOT_AVAILABLE" in str(exc_info.value)
    assert "account provider is required" in str(exc_info.value)


def test_composition_assembles_full_live_coordinator_with_explicit_dependencies(monkeypatch):
    """Verify that when authoritative inputs are present, the complete Live coordinator is assembled.

    NOTE: This is a synthetic logic verification test ensuring proper assembly wiring.
    It does not claim real external KIS network connectivity.
    """
    monkeypatch.setenv("KIS_REAL_APP_KEY", "TEST_KEY")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "TEST_SECRET")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678-01")
    monkeypatch.setenv("KIS_HTS_ID", "TEST_HTS")

    # Mock contract provider
    mock_master_provider = MagicMock()
    contract = KisFuturesContractIdentity(
        info_type="B",
        shrn_iscd="A05610",
        stnd_iscd="KRDRVFU2001",
        kor_name="KOSPI200 MINI FUT",
        mmsc_cls_code="1",
        unas_shrn_iscd="2001",
        unas_kor_name="KOSPI200",
    )
    mock_master_provider.current_mini_futures_source.return_value = (
        KisCurrentFuturesContractSource((contract,), underlying_short_code="2001")
    )

    mock_account = MagicMock()
    mock_exec_transport = MagicMock()
    mock_market_transport = MagicMock()
    mock_order_transport = MagicMock()
    mock_recovery_transport = MagicMock()

    coordinator = create_authoritative_kis_live_runtime_composition(
        master_provider=mock_master_provider,
        account=mock_account,
        execution_transport=mock_exec_transport,
        market_transport=mock_market_transport,
        order_transport=mock_order_transport,
        recovery_transport=mock_recovery_transport,
    )

    assert isinstance(coordinator, LiveRuntimeLifecycleCoordinator)
    assert coordinator._controller is not None
    assert coordinator._bootstrap is not None
    assert coordinator._bootstrap.execution is not None
    assert coordinator._bootstrap.order_router is not None


def test_runtime_evidence_does_not_use_virtual_bootstrap():
    """Verify verification/runtime_evidence.py never imports or calls create_virtual_runtime_bootstrap."""
    from pathlib import Path
    evidence_code = Path("verification/runtime_evidence.py").read_text(encoding="utf-8")
    assert "create_virtual_runtime_bootstrap" not in evidence_code
    assert "create_authoritative_kis_live_runtime_composition" in evidence_code
