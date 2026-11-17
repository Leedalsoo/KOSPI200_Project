from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import math
import re
from statistics import mean, pstdev
from typing import Mapping

from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput


class ValidationOnlyProfileError(ValueError):
    """Raised when a synthetic profile lacks reproducible validation provenance."""


class ValidationOnlyS3S4InputAdapter:
    """Build typed S3/S4 inputs from an explicitly non-production scenario profile.

    The verified flags on Track3MarketInput are scenario-local structural attestations.
    This adapter is deliberately not registered in production Runtime composition and
    never creates a broker order, authoritative KIS identity, or account/option lot.
    """

    REQUIRED_NAMESPACE = "SYNTHETIC:DERIVED_SCENARIO"
    _SHA256 = re.compile(r"^[0-9a-f]{64}$")

    def __init__(self, profile: Mapping[str, object]) -> None:
        self._profile = dict(profile)
        self._validate_profile()

    @property
    def profile_id(self) -> str:
        return str(self._profile["profile_id"])

    @property
    def provenance(self) -> Mapping[str, object]:
        return {
            "profile_id": self.profile_id,
            "namespace": self.REQUIRED_NAMESPACE,
            "source_anchors": tuple(self._profile["source_anchors"]),
            "authority": dict(self._profile["authority"]),
        }

    def build_track3_input(self) -> Track3MarketInput:
        s3 = self._profile["s3"]
        observations = tuple(s3["observations"])
        basis_history = tuple(float(row["basis"]) for row in observations)
        basis_history += (float(s3["current_basis"]),)
        last = observations[-1]
        return Track3MarketInput(
            spread_history=basis_history,
            active_vol=20.0,
            base_vol=15.0,
            price_change_rate=0.0,
            bid_ask_spread=0.1,
            gap_pct=0.0,
            is_gap=False,
            time_str=str(s3["time_str"]),
            market_stable=True,
            spread_normalizing=False,
            allow_size_up=False,
            current_pnl=0.0,
            total_fees=0.0,
            premium_spent=0.0,
            current_price=float(last["index_price"]),
            contract_multiplier=float(s3["contract_multiplier"]),
            regime=str(s3["regime"]),
            date_str=str(s3["date_str"]),
            # These booleans attest only to this synthetic scenario's internal
            # consistency. The namespace and provenance are mandatory safeguards.
            spread_identity_verified=True,
            futures_identity_verified=True,
            cost_model_verified=True,
        )

    def build_track4_input(self) -> Track4MarketInput:
        s4 = self._profile["s4"]
        observed_at = datetime.fromisoformat(str(s4["observed_at"]))
        return Track4MarketInput(
            observed_at=observed_at,
            current_price=Decimal(str(s4["current_price"])),
            active_vol=Decimal(str(s4["active_vol"])),
            base_vol=Decimal(str(s4["base_vol"])),
            time_str=observed_at.strftime("%H:%M:%S"),
            current_delta=Decimal(str(s4["current_delta"])),
            current_gamma=Decimal(str(s4["current_gamma"])),
            current_pnl=Decimal(str(s4["current_pnl_initial"])),
            current_equity=Decimal(str(s4["current_equity"])),
            price_history=tuple(Decimal(str(value)) for value in s4["price_history"]),
            premium_spent=Decimal(str(s4["premium_spent"])),
            current_theta=Decimal(str(s4["current_theta"])),
            max_hedge_qty=int(s4["max_hedge_qty"]),
        )

    def _validate_profile(self) -> None:
        if not self._profile.get("profile_id"):
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_ID_REQUIRED")
        if self._profile.get("namespace") != self.REQUIRED_NAMESPACE:
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_NAMESPACE_REQUIRED")
        authority = self._profile.get("authority")
        if not isinstance(authority, Mapping) or authority.get("production_eligible") is not False or authority.get("live_eligible") is not False:
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_AUTHORITY_BOUNDARY_REQUIRED")
        if authority.get("identity_authority") != "NONE" or authority.get("execution_authority") != "NONE":
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_MUST_NOT_CLAIM_AUTHORITY")

        anchors = self._profile.get("source_anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_SOURCE_ANCHOR_REQUIRED")
        for anchor in anchors:
            if not isinstance(anchor, Mapping) or not anchor.get("path") or not self._SHA256.fullmatch(str(anchor.get("sha256", ""))):
                raise ValidationOnlyProfileError("VALIDATION_PROFILE_SOURCE_ANCHOR_INVALID")

        rules = self._profile.get("generation_rules")
        if not isinstance(rules, Mapping) or not rules.get("s3") or not rules.get("s4"):
            raise ValidationOnlyProfileError("VALIDATION_PROFILE_GENERATION_RULE_REQUIRED")

        s3 = self._profile.get("s3")
        if not isinstance(s3, Mapping) or not str(s3.get("synthetic_contract_namespace", "")).startswith("SYNTHETIC_CONTRACT:"):
            raise ValidationOnlyProfileError("S3_SYNTHETIC_CONTRACT_NAMESPACE_REQUIRED")
        rows = s3.get("observations")
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValidationOnlyProfileError("S3_BASIS_ANCHOR_OBSERVATIONS_REQUIRED")
        times = [str(row.get("time", "")) for row in rows]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValidationOnlyProfileError("S3_BASIS_EVENT_TIME_ORDER_INVALID")
        for row in rows:
            if not math.isclose(float(row["basis"]), round(float(row["futures_price"]) - float(row["index_price"]), 2), abs_tol=1e-9):
                raise ValidationOnlyProfileError("S3_BASIS_CROSSWALK_MISMATCH")
            for key in ("futures_payload_sha256", "index_payload_sha256"):
                if not self._SHA256.fullmatch(str(row.get(key, ""))):
                    raise ValidationOnlyProfileError("S3_SOURCE_FRAME_HASH_REQUIRED")
        observed_basis = [float(row["basis"]) for row in rows]
        expected_std = pstdev(observed_basis)
        if not math.isclose(expected_std, float(s3["spread_std"]), rel_tol=1e-9, abs_tol=1e-9):
            raise ValidationOnlyProfileError("S3_SPREAD_STD_REPRODUCTION_MISMATCH")
        expected_shock = mean(observed_basis) + float(s3["z_score"]) * expected_std
        if not math.isclose(expected_shock, float(s3["current_basis"]), rel_tol=1e-6, abs_tol=1e-6):
            raise ValidationOnlyProfileError("S3_SYNTHETIC_SHOCK_REPRODUCTION_MISMATCH")

        s4 = self._profile.get("s4")
        if not isinstance(s4, Mapping) or not s4.get("greeks_provenance"):
            raise ValidationOnlyProfileError("S4_SYNTHETIC_GREEKS_PROVENANCE_REQUIRED")
        if s4.get("option_identity") is not None or s4.get("option_lot_owner") is not None:
            raise ValidationOnlyProfileError("S4_MUST_NOT_CLAIM_OPTION_IDENTITY_OR_LOT_OWNER")
        if int(s4.get("max_hedge_qty", 0)) <= 0 or not s4.get("price_history"):
            raise ValidationOnlyProfileError("S4_VALIDATION_STRESS_INPUT_INVALID")
