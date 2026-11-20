from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from core.risk.track2_u21_quote_policy import (
    QuoteSide,
    U21Quote,
    U21QuotePolicy,
    evaluate_u21_quote,
)


class ValidationOnlyU21QuotePolicyAdapter:
    """Evaluate U21 against manifest-bound synthetic S2 quote rows only."""

    validation_only = True
    order_submission_enabled = False

    def __init__(self, provider: Any) -> None:
        if provider.__class__.__name__ != "ValidationOnlyS2ScenarioAlternativeProvider":
            raise ValueError("U21_VALIDATION_ADAPTER_REQUIRES_S2_SYNTHETIC_PROVIDER")
        self.provider = provider
        _manifest, _candidate, profile, _quotes, _hashes = provider._load_verified_sources()
        values = profile.get("U21_quote_policy", {})
        self.policy = U21QuotePolicy(
            max_age_seconds=Decimal(str(values.get("max_age_seconds")))
            if values.get("max_age_seconds") is not None else None,
            max_spread=Decimal(str(values.get("max_spread")))
            if values.get("max_spread") is not None else None,
            spread_measure=values.get("spread_measure"),
            fallback_formula=values.get("fallback_formula"),
            fallback_priority=values.get("fallback_priority"),
            tick_size=Decimal(str(values.get("tick_size")))
            if values.get("tick_size") is not None else None,
            tick_rounding=values.get("tick_rounding"),
            approved=values.get("approved_for_synthetic_scenarios_only") is True,
        )
        self.last_quote_digest: str | None = None
        self.last_leg_role: str | None = None
        self.last_quote_side: str | None = None

    def evaluate(self, tick: Any):
        if getattr(tick, "validation_only", False) is not True:
            raise ValueError("U21_SYNTHETIC_TICK_VALIDATION_ONLY_MARKER_REQUIRED")
        if getattr(tick, "option_source", None) != "SYNTHETIC:DERIVED_SCENARIO":
            raise ValueError("U21_SYNTHETIC_SOURCE_NAMESPACE_REQUIRED")
        _manifest, candidate, _profile, quotes, hashes = self.provider._load_verified_sources()
        if getattr(tick, "candidate_id", None) != self.provider.candidate_id:
            raise ValueError("U21_SCENARIO_CANDIDATE_MISMATCH")
        self.last_quote_digest = None
        self.last_leg_role = None
        self.last_quote_side = None
        instrument_id = getattr(tick, "instrument_id", None)
        leg_role = str(getattr(tick, "leg_role", "") or "")
        quote_side = str(getattr(tick, "u21_quote_side", "") or "")
        expected_side = self.provider.ROLE_SIDE.get(leg_role)
        if expected_side is None or quote_side != expected_side:
            raise ValueError("U21_SYNTHETIC_LEG_ROLE_SIDE_MISMATCH")
        self.last_leg_role = leg_role
        self.last_quote_side = quote_side
        symbol = getattr(tick, "symbol", None)
        identity_valid = bool(
            instrument_id
            and symbol == instrument_id
            and getattr(tick, "synthetic_contract_id", None) == instrument_id
            and getattr(tick, "instrument_identity_status", None) == "SYNTHETIC_VALIDATION_ONLY"
        )
        row = (
            next((item for item in quotes if item.get("instrument_id") == instrument_id), None)
            if identity_valid else None
        )
        observed_at = None
        bid = ask = None
        derived_digest = None
        source = None
        source_time_verified = False
        capability_verified = False
        if row is not None:
            if (
                row.get("leg_role") != leg_role
                or str(row.get("option_type", "")).upper() != str(getattr(tick, "option_type", "")).upper()
                or Decimal(str(row.get("strike"))) != Decimal(str(getattr(tick, "strike_price", "NaN")))
                or str(row.get("expiry")) != str(getattr(tick, "expiry", ""))
                or Decimal(str(row.get("bid"))) != Decimal(str(getattr(tick, "bid_price", "NaN")))
                or Decimal(str(row.get("ask"))) != Decimal(str(getattr(tick, "ask_price", "NaN")))
                or Decimal(str(row.get("contract_multiplier"))) != Decimal(str(getattr(tick, "contract_multiplier", "NaN")))
                or row.get("candidate_id") != self.provider.candidate_id
                or row.get("source") != "SYNTHETIC:DERIVED_SCENARIO"
            ):
                raise ValueError("U21_SYNTHETIC_QUOTE_ROW_TICK_MISMATCH")
            observed_at = datetime.fromisoformat(str(row.get("timestamp")))
            bid = Decimal(str(row.get("bid"))) if row.get("bid") is not None else None
            ask = Decimal(str(row.get("ask"))) if row.get("ask") is not None else None
            source = row.get("source")
            derived_digest = self.provider._hash_json(row)
            self.last_quote_digest = derived_digest
            source_time_verified = (
                observed_at == datetime.fromisoformat(str(candidate.get("observed_at")))
                and row.get("source_manifest_sha256") == hashes["accepted_manifest"]
                and row.get("source") == "SYNTHETIC:DERIVED_SCENARIO"
            )
            capability_verified = (
                bool(instrument_id)
                and row.get("contract_identity_authority") == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
                and bid is not None and ask is not None
            )
        quote = U21Quote(
            instrument_id=str(instrument_id or ""),
            symbol=str(symbol or ""),
            bid=bid,
            ask=ask,
            observed_at=observed_at,
            source_time_semantics_verified=source_time_verified,
            capability_verified=capability_verified,
            source=source,
            raw_payload_sha256=None,
            provenance_kind="DERIVED_SYNTHETIC",
            derived_quote_digest=derived_digest,
        )
        now = datetime.fromisoformat(str(getattr(tick, "timestamp", "")))
        return evaluate_u21_quote(
            primary=quote,
            fallback=None,
            side=QuoteSide[quote_side],
            now=now,
            policy=self.policy,
            expected_instrument_id=str(instrument_id or "") if identity_valid else "",
            expected_symbol=str(symbol or "") if identity_valid else "",
        )
