from __future__ import annotations

from collections.abc import Callable
from typing import Any

from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    FreshnessStatus,
    FreshnessVerdict,
    evaluate_freshness,
)


class AuthoritativeOptionQuoteFreshnessProvider:
    """Bind a leg to Option Master before evaluating source-backed quote freshness.

    No evidence provider is configured in the current Virtual composition. In that
    case the provider returns UNKNOWN; it never upgrades quote presence or receipt
    time into a FRESH verdict.
    """

    def __init__(
        self,
        *,
        option_master: Any,
        evidence_provider: Callable[..., FreshnessEvidence | None] | None = None,
        policy: FreshnessPolicy | None = None,
        environment: str = "VIRTUAL",
        expected_source_environment: str | None = None,
    ) -> None:
        self._option_master = option_master
        self._evidence_provider = evidence_provider
        self._policy = policy or FreshnessPolicy(version="runtime-option-quote-v1")
        self._environment = environment
        self._expected_source_environment = expected_source_environment

    def __call__(self, plan: Any, leg: Any, identity: Any, command: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "").strip()
        symbol = str(getattr(command, "broker_symbol", "") or "").strip()
        policy_version = self._policy.version

        def verdict(status: FreshnessStatus, reason: str) -> FreshnessVerdict:
            return FreshnessVerdict(
                status=status,
                reason=reason,
                policy_version=policy_version,
                environment=self._environment,
                instrument_id=instrument_id or None,
                symbol=symbol or None,
            )

        if not instrument_id or not symbol:
            return verdict(FreshnessStatus.UNKNOWN, "EXACT_COMMAND_CONTRACT_IDENTITY_REQUIRED")

        # Futures identity has a different authoritative master/provider contract.
        # Do not interpret an option-master miss as a valid futures identity.
        if str(getattr(command, "asset_type", "")).upper() == "FUTURES":
            return verdict(FreshnessStatus.UNKNOWN, "AUTHORITATIVE_FUTURES_QUOTE_FRESHNESS_PROVIDER_UNAVAILABLE")
        if identity is None:
            return verdict(FreshnessStatus.UNKNOWN, "EXACT_COMMAND_CONTRACT_IDENTITY_REQUIRED")

        try:
            master_identity = self._option_master.get_contract_identity(symbol)
        except Exception:
            master_identity = None
        if master_identity is None:
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "OPTION_MASTER_CONTRACT_NOT_FOUND")

        master_instrument_id = str(getattr(master_identity, "stnd_iscd", None) or getattr(master_identity, "shrn_iscd", "")).strip()
        master_symbol = str(getattr(master_identity, "shrn_iscd", "")).strip()
        master_expiry = str(getattr(master_identity, "expiry", "")).replace("-", "")[:8]
        expected_expiry = str(getattr(identity, "expiry", "") or "").replace("-", "")[:8]
        master_type = str(getattr(master_identity, "option_type", "") or "").upper()
        expected_type = str(getattr(identity, "option_type", "") or "").upper()
        master_strike = getattr(master_identity, "strike", None)
        expected_strike = getattr(identity, "strike", None)
        master_multiplier = getattr(master_identity, "contract_multiplier", None)
        expected_multiplier = getattr(identity, "contract_multiplier", None)
        if (
            master_instrument_id != instrument_id
            or master_symbol != symbol
            or master_expiry != expected_expiry
            or master_type != expected_type
            or master_strike is None
            or expected_strike is None
            or str(master_strike) != str(expected_strike)
            or master_multiplier is None
            or expected_multiplier is None
            or str(master_multiplier) != str(expected_multiplier)
        ):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "OPTION_MASTER_COMMAND_IDENTITY_MISMATCH")

        if self._evidence_provider is None:
            return verdict(FreshnessStatus.UNKNOWN, "AUTHORITATIVE_QUOTE_FRESHNESS_EVIDENCE_UNAVAILABLE")
        try:
            evidence = self._evidence_provider(plan, leg, identity, command)
        except Exception:
            evidence = None
        if evidence is None:
            return verdict(FreshnessStatus.UNKNOWN, "AUTHORITATIVE_QUOTE_FRESHNESS_EVIDENCE_UNAVAILABLE")
        return evaluate_freshness(
            evidence,
            policy=self._policy,
            expected_instrument_id=instrument_id,
            expected_symbol=symbol,
            expected_environment=self._expected_source_environment,
        )
