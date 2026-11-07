"""Manifest-bound S9 synthetic Runtime input, quote freshness and Virtual order gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.strategy.track9_independent_policy import (
    Track9OpenLot, Track9RuntimeInput, Track9SyntheticQuote,
    select_nearest_expiry_atm_pair,
)
from application.composition.track9_validation_only_contract_adapter import Track9SyntheticContractProfile

STRATEGY_ID = "track9_event_overnight_insurance"
SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:S9-"
MANIFEST_SCHEMA = "q25-a2-1-s6-syn-evt-manifest-v1"


@dataclass(frozen=True)
class S9ValidationEvidence:
    scenario_id: str
    manifest_sha256: str
    dataset_sha256: str
    contract_profile_sha256: str
    risk_profile_sha256: str
    initial_capital_krw: int
    max_gross_premium_krw: int
    max_loss_krw: int
    max_quantity_per_leg: int
    max_concurrent_groups: int
    max_quote_age_seconds: Decimal


class Track9ValidationOnlyRuntimeAdapter:
    """Supplies only DERIVED_SCENARIO inputs to the registered S9 StrategyHub path."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path,
                 contract_profile_path: str | Path, risk_profile_path: str | Path) -> None:
        self.dataset = Path(dataset).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.contract_profile_path = Path(contract_profile_path).resolve()
        self.risk_profile_path = Path(risk_profile_path).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.contract_profile = Track9SyntheticContractProfile.load(self.contract_profile_path)
        self.risk_profile = json.loads(self.risk_profile_path.read_text(encoding="utf-8"))
        self._validate_inputs()
        self.manifest_sha256 = sha256(self.manifest_path.read_bytes()).hexdigest()
        self.dataset_sha256 = str(self.manifest["output_sha256"]).lower()
        self.contract_profile_sha256 = sha256(self.contract_profile_path.read_bytes()).hexdigest()
        self.risk_profile_sha256 = sha256(self.risk_profile_path.read_bytes()).hexdigest()
        limits = self.risk_profile["limits"]
        self.evidence = S9ValidationEvidence(
            scenario_id=str(self.manifest["scenario_id"]),
            manifest_sha256=self.manifest_sha256,
            dataset_sha256=self.dataset_sha256,
            contract_profile_sha256=self.contract_profile_sha256,
            risk_profile_sha256=self.risk_profile_sha256,
            initial_capital_krw=int(self.risk_profile["initial_capital_krw"]),
            max_gross_premium_krw=int(limits["max_gross_premium_krw"]),
            max_loss_krw=int(limits["max_loss_krw"]),
            max_quantity_per_leg=int(limits["max_quantity_per_leg"]),
            max_concurrent_groups=int(limits["max_concurrent_groups"]),
            max_quote_age_seconds=Decimal(str(limits["max_quote_age_seconds"])),
        )
        self.run_id = "UNBOUND"
        self._last_input: Track9RuntimeInput | None = None
        self._reserved: dict[str, Decimal] = {}
        self.risk_audit_records: list[dict[str, Any]] = []

    @staticmethod
    def _parse_expiry(value: Any) -> date:
        text = str(value or "").replace("-", "")
        if len(text) != 8 or not text.isdigit():
            raise ValueError("S9_SYNTHETIC_EXACT_EXPIRY_REQUIRED")
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))

    def _validate_inputs(self) -> None:
        m, r = self.manifest, self.risk_profile
        if (m.get("schema_version") != MANIFEST_SCHEMA
                or m.get("source_type") != "DERIVED_SCENARIO"
                or m.get("provenance") != "DERIVED_SCENARIO"
                or m.get("synthetic") is not True
                or m.get("validation_only") is not True
                or m.get("runtime_eligible") is not False
                or m.get("production_runtime_eligible") is not False
                or m.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
                or m.get("expiry_is_authoritative") is not False
                or m.get("strategy_id") != STRATEGY_ID
                or m.get("orders_allowed") is not False):
            raise ValueError("S9_VALIDATION_MANIFEST_INVALID")
        output_path = str(m.get("output_path") or "")
        output = (Path.cwd() / output_path).resolve()
        if output.parent != self.dataset or not output.is_file():
            raise ValueError("S9_VALIDATION_DATASET_PATH_MISMATCH")
        digest = sha256(output.read_bytes()).hexdigest()
        if (digest != str(m.get("output_sha256", "")).lower()
                or output.stat().st_size != m.get("output_bytes")):
            raise ValueError("S9_VALIDATION_DATASET_HASH_OR_SIZE_MISMATCH")
        rows = sum(1 for line in output.read_text(encoding="utf-8").splitlines() if line.strip())
        if rows != m.get("rows"):
            raise ValueError("S9_VALIDATION_DATASET_ROW_COUNT_MISMATCH")
        if (m.get("contract_profile_path") != self.contract_profile_path.relative_to(Path.cwd()).as_posix()
                or m.get("contract_profile_sha256") != sha256(self.contract_profile_path.read_bytes()).hexdigest()):
            raise ValueError("S9_VALIDATION_CONTRACT_PROFILE_BINDING_MISMATCH")
        if (m.get("risk_profile_path") != self.risk_profile_path.relative_to(Path.cwd()).as_posix()
                or m.get("risk_profile_sha256") != sha256(self.risk_profile_path.read_bytes()).hexdigest()):
            raise ValueError("S9_VALIDATION_RISK_PROFILE_BINDING_MISMATCH")
        required_false = ("runtime_eligible", "production_runtime_eligible", "allow_kis_api",
                          "allow_real_vts", "allow_live_orders", "allow_real_account",
                          "operational_config_mutated")
        if (r.get("provenance") != "SYNTHETIC" or r.get("validation_only") is not True
                or any(r.get(key) is not False for key in required_false)
                or r.get("risk_checks_enabled") is not True
                or r.get("virtual_broker_orders_allowed") is not True):
            raise ValueError("S9_VALIDATION_RISK_PROFILE_INVALID")
        limits = r.get("limits")
        if not isinstance(limits, dict):
            raise ValueError("S9_VALIDATION_RISK_LIMITS_REQUIRED")
        for key in ("max_gross_premium_krw", "max_loss_krw", "max_quantity_per_leg",
                    "max_concurrent_groups", "max_quote_age_seconds"):
            if Decimal(str(limits.get(key, 0))) <= 0:
                raise ValueError(f"S9_VALIDATION_RISK_LIMIT_INVALID:{key}")
        expected_policy = {
            "entry_evaluation_time": "15:00:00",
            "entry_evaluation_timezone": "Asia/Seoul",
            "entry_instrument_selection": "NEAREST_EXPIRY_SAME_STRIKE_ATM_PUT_CALL",
            "pair_quantity_per_leg": 1,
            "opening_move_threshold": "0.01",
            "opening_move_metric": "ABS((next_session_open-previous_close)/previous_close)",
            "at_or_above_threshold_action": "CLOSE_INSURANCE",
            "below_threshold_action": "STOP_LOSS",
            "trailing_profit_exit": "NOT_USED",
        }
        if m.get("strategy_code_version") != "3.0" or m.get("strategy_policy") != expected_policy:
            raise ValueError("S9_VALIDATION_STRATEGY_POLICY_BINDING_MISMATCH")
        official_status = m.get("official_data_status")
        if not isinstance(official_status, dict) or not official_status or any(value != "MISSING" for value in official_status.values()):
            raise ValueError("S9_OFFICIAL_DATA_MUST_REMAIN_EXPLICITLY_MISSING")
        refs = m.get("synthetic_reference_inputs")
        if (not isinstance(refs, dict) or Decimal(str(refs.get("previous_official_close", 0))) <= 0
                or Decimal(str(refs.get("next_session_official_open", 0))) <= 0):
            raise ValueError("S9_SYNTHETIC_OPEN_CLOSE_REFERENCE_REQUIRED")

    def bind_run_id(self, run_id: str) -> None:
        if not run_id or not str(run_id).strip():
            raise ValueError("S9_VALIDATION_RUN_ID_REQUIRED")
        if self.run_id != "UNBOUND" and self.run_id != str(run_id):
            raise ValueError("S9_VALIDATION_RUN_ID_ALREADY_BOUND")
        self.run_id = str(run_id)

    def apply_to_strategy(self, strategy: Any, *, synthetic_sources: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S9_VALIDATION_STRATEGY_MISMATCH")
        if not str(getattr(synthetic_sources, "source_name", "")).startswith("SYNTHETIC:"):
            raise ValueError("S9_VALIDATION_SYNTHETIC_SOURCE_REQUIRED")
        strategy.validation_only_runtime = True

    def build_runtime_input(self, *, tick: Any, data: Any, market: Any,
                            option_master: Any, position_lot_store: Any) -> Track9RuntimeInput:
        if (getattr(tick, "validation_only", False) is not True
                or getattr(tick, "scenario_id", "") != self.evidence.scenario_id):
            raise ValueError("S9_VALIDATION_TICK_SCENARIO_MISMATCH")
        candidates = self.contract_profile.build_candidates(option_master.list_contract_identities())
        if any(not item.symbol.startswith(SYNTHETIC_ID_PREFIX) for item in candidates):
            raise ValueError("S9_VALIDATION_SYNTHETIC_CONTRACT_NAMESPACE_REQUIRED")
        as_of = datetime.fromisoformat(str(tick.timestamp))
        quote_map = getattr(market, "option_quotes_by_instrument_id", {})
        quotes: list[Track9SyntheticQuote] = []
        for candidate in candidates:
            raw = quote_map.get(candidate.symbol) if isinstance(quote_map, dict) else None
            if not isinstance(raw, dict):
                continue
            try:
                observed = datetime.fromisoformat(str(raw["timestamp"]))
                quote = Track9SyntheticQuote(
                    instrument_id=str(raw["instrument_id"]),
                    option_type=str(raw["option_type"]).upper(),
                    strike=Decimal(str(raw["strike"])),
                    expiry=self._parse_expiry(raw["expiry"]),
                    bid=Decimal(str(raw["bid"])), ask=Decimal(str(raw["ask"])),
                    last=Decimal(str(raw["last"])), observed_at=observed,
                    source=str(raw["source"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("S9_VALIDATION_SYNTHETIC_QUOTE_INVALID") from exc
            age = (as_of - observed).total_seconds()
            if (quote.source != "SYNTHETIC:DERIVED_SCENARIO"
                    or quote.instrument_id != candidate.symbol
                    or quote.option_type != candidate.option_type
                    or quote.strike != candidate.strike or quote.expiry != candidate.expiry
                    or Decimal(str(raw.get("contract_multiplier", 0))) != candidate.contract_multiplier
                    or observed.tzinfo is None or as_of.tzinfo is None
                    or age < 0 or quote.bid <= 0 or quote.ask < quote.bid or quote.last <= 0):
                raise ValueError("S9_VALIDATION_SYNTHETIC_QUOTE_IDENTITY_OR_FRESHNESS_INVALID")
            if Decimal(str(age)) > self.evidence.max_quote_age_seconds:
                continue
            quotes.append(quote)
        open_lots: list[Track9OpenLot] = []
        if position_lot_store is not None:
            for lot in position_lot_store.open_lots():
                if (getattr(lot, "run_id", None) != self.run_id
                        or getattr(lot, "strategy_id", None) != STRATEGY_ID
                        or str(getattr(lot, "side", "")).upper() != "BUY"
                        or int(getattr(lot, "remaining_quantity", 0)) <= 0):
                    continue
                identity = getattr(lot, "instrument_identity", None)
                if identity is None:
                    raise ValueError("S9_VALIDATION_OPEN_LOT_IDENTITY_MISSING")
                open_lots.append(Track9OpenLot(
                    strategy_id=STRATEGY_ID, instrument_id=str(lot.instrument_id),
                    expiry=self._parse_expiry(identity.expiry),
                    option_type=str(identity.option_type).upper(),
                    strike=Decimal(str(identity.strike)),
                    remaining_quantity=int(lot.remaining_quantity), side=str(lot.side).upper(),
                    entry_price=None, contract_multiplier=Decimal(str(lot.contract_multiplier)),
                    executed_at=lot.execution_timestamp,
                ))
        refs = self.manifest["synthetic_reference_inputs"]
        provenance = tuple((key, "SYNTHETIC") for key in (
            "contract_identity", "contract_multiplier", "tradability", "option_quotes",
            "previous_official_close", "next_session_official_open", "trading_calendar",
            "account", "position", "risk_limits",
        )) + tuple((key, "MISSING") for key in self.manifest["official_data_status"])
        runtime_input = Track9RuntimeInput(
            contract_candidates=tuple(candidates),
            underlying_price=Decimal(str(tick.underlying_price)), as_of=as_of,
            previous_official_close=Decimal(str(refs["previous_official_close"])),
            next_session_official_open=Decimal(str(refs["next_session_official_open"])),
            option_quotes=tuple(quotes), open_lots=tuple(open_lots), provenance="SYNTHETIC",
            source_provenance=provenance, scenario_id=self.evidence.scenario_id,
            manifest_sha256=self.evidence.manifest_sha256, dataset_sha256=self.evidence.dataset_sha256,
            contract_profile_sha256=self.evidence.contract_profile_sha256,
            risk_profile_sha256=self.evidence.risk_profile_sha256,
            max_quote_age_seconds=self.evidence.max_quote_age_seconds,
        )
        self._last_input = runtime_input
        return runtime_input

    def validate_group(self, plan: Any, prepared: list[tuple]) -> None:
        if getattr(plan, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S9_VALIDATION_ORDER_SCOPE_INVALID")
        purpose = str(getattr(plan, "purpose", "") or "")
        group_id = str(getattr(plan, "group_id", "") or "")
        if not group_id or not prepared:
            raise ValueError("S9_VALIDATION_GROUP_REQUIRED")
        expected_types = {"PUT", "CALL"}
        if self._last_input is None:
            raise ValueError("S9_VALIDATION_RUNTIME_INPUT_REQUIRED")
        expected_symbols: dict[str, str] = {}
        expected_lots: dict[str, Track9OpenLot] = {}
        if purpose == "OVERNIGHT_INSURANCE":
            pair = select_nearest_expiry_atm_pair(
                self._last_input.contract_candidates,
                underlying_price=self._last_input.underlying_price,
                as_of_date=self._last_input.as_of.date(),
            )
            expected_symbols = {"PUT": pair.put.symbol, "CALL": pair.call.symbol}
        elif purpose == "OVERNIGHT_INSURANCE_CLOSE":
            lots = tuple(item for item in self._last_input.open_lots
                         if item.strategy_id == STRATEGY_ID and item.side.upper() == "BUY"
                         and item.remaining_quantity > 0)
            expected_lots = {item.option_type.upper(): item for item in lots}
            if len(lots) != 2 or set(expected_lots) != expected_types:
                raise ValueError("S9_VALIDATION_CLOSE_REQUIRES_EXACT_OPEN_PUT_CALL_PAIR")
        else:
            raise ValueError("S9_VALIDATION_PURPOSE_INVALID")
        seen: set[str] = set()
        gross = Decimal("0")
        for leg, identity, _client_id, _command, _canonical, bid, ask in prepared:
            option_type = str(getattr(identity, "option_type", "")).upper()
            instrument_id = str(getattr(identity, "instrument_id", ""))
            multiplier = Decimal(str(getattr(identity, "contract_multiplier", 0)))
            quantity = int(getattr(leg, "quantity", 0))
            role = getattr(leg, "position_role", None)
            role_value = getattr(role, "value", role)
            if (option_type not in expected_types or option_type in seen
                    or not instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                    or str(getattr(identity, "identity_source", "")) != "SYNTHETIC:DERIVED_SCENARIO"
                    or str(role_value).upper() != "OVERNIGHT_INSURANCE"
                    or quantity <= 0 or quantity > self.evidence.max_quantity_per_leg
                    or multiplier != self.contract_profile.contract_multiplier):
                raise ValueError("S9_VALIDATION_LEG_IDENTITY_ROLE_OR_QUANTITY_INVALID")
            if purpose == "OVERNIGHT_INSURANCE" and instrument_id != expected_symbols.get(option_type):
                raise ValueError("S9_VALIDATION_ENTRY_NOT_SELECTED_ATM_PAIR")
            if purpose == "OVERNIGHT_INSURANCE_CLOSE":
                expected_lot = expected_lots.get(option_type)
                if (expected_lot is None or instrument_id != expected_lot.instrument_id
                        or quantity != expected_lot.remaining_quantity
                        or multiplier != expected_lot.contract_multiplier):
                    raise ValueError("S9_VALIDATION_CLOSE_MUST_MATCH_OPEN_POSITION_LOT")
            seen.add(option_type)
            bid_d, ask_d = Decimal(str(bid)), Decimal(str(ask))
            if bid_d <= 0 or ask_d < bid_d:
                raise ValueError("S9_VALIDATION_ORDER_QUOTE_INVALID")
            if purpose == "OVERNIGHT_INSURANCE":
                if str(getattr(leg, "side", "")).upper() != "BUY":
                    raise ValueError("S9_VALIDATION_ENTRY_BUY_ONLY")
                gross += ask_d * quantity * multiplier
            elif purpose == "OVERNIGHT_INSURANCE_CLOSE":
                if str(getattr(leg, "side", "")).upper() != "SELL":
                    raise ValueError("S9_VALIDATION_CLOSE_SELL_ONLY")
        if seen != expected_types:
            raise ValueError("S9_VALIDATION_PUT_CALL_PAIR_REQUIRED")
        if purpose == "OVERNIGHT_INSURANCE":
            if self._last_input is None:
                raise ValueError("S9_VALIDATION_RUNTIME_INPUT_REQUIRED")
            if group_id not in self._reserved and len(self._reserved) >= self.evidence.max_concurrent_groups:
                raise ValueError("S9_VALIDATION_CONCURRENT_GROUP_LIMIT_EXCEEDED")
            if gross > self.evidence.max_gross_premium_krw or gross > self.evidence.max_loss_krw:
                raise ValueError("S9_VALIDATION_SYNTHETIC_PREMIUM_RISK_LIMIT_EXCEEDED")
            self._reserved[group_id] = gross
        self.risk_audit_records.append({
            "run_id": self.run_id, "scenario_id": self.evidence.scenario_id,
            "manifest_sha256": self.evidence.manifest_sha256,
            "dataset_sha256": self.evidence.dataset_sha256,
            "risk_profile_sha256": self.evidence.risk_profile_sha256,
            "group_id": group_id, "purpose": purpose, "gross_premium_krw": str(gross),
            "max_gross_premium_krw": self.evidence.max_gross_premium_krw,
            "max_loss_krw": self.evidence.max_loss_krw, "status": "ALLOW_VIRTUAL_ONLY",
        })

    def freshness_verdict(self, *, plan: Any, identity: Any, command: Any,
                          option_master: Any, market: Any, synthetic_sources: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "")
        symbol = str(getattr(command, "broker_symbol", "") or instrument_id)
        def verdict(status: FreshnessStatus, reason: str, observed=None, digest=None):
            return FreshnessVerdict(
                status=status, reason=reason, policy_version="S9-SYNTHETIC-FRESHNESS-v1",
                source="SYNTHETIC:DERIVED_SCENARIO", tr_id="S9_VALIDATION_MANIFEST",
                environment="SYNTHETIC_VALIDATION_ONLY", instrument_id=instrument_id,
                symbol=symbol, source_instant=observed, received_at=observed, evidence_sha256=digest,
            )
        if (getattr(plan, "strategy_id", None) != STRATEGY_ID
                or not instrument_id.startswith(SYNTHETIC_ID_PREFIX)):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S9_SYNTHETIC_IDENTITY_REQUIRED")
        master = option_master.get_contract_identity(instrument_id)
        quote = getattr(market, "option_quotes_by_instrument_id", {}).get(instrument_id)
        if master is None or not isinstance(quote, dict):
            return verdict(FreshnessStatus.UNKNOWN, "S9_SYNTHETIC_MASTER_OR_QUOTE_MISSING")
        try:
            observed = datetime.fromisoformat(str(quote["timestamp"]))
            replay_now = datetime.fromisoformat(str(synthetic_sources._tick.timestamp))
            bid, ask, last = (Decimal(str(quote[key])) for key in ("bid", "ask", "last"))
            multiplier = Decimal(str(quote["contract_multiplier"]))
        except Exception:
            return verdict(FreshnessStatus.UNKNOWN, "S9_SYNTHETIC_QUOTE_FIELDS_INVALID")
        if (quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO"
                or str(master.shrn_iscd) != instrument_id
                or str(master.option_type).upper() != str(identity.option_type).upper()
                or Decimal(str(master.strike)) != Decimal(str(identity.strike))
                or self._parse_expiry(master.expiry) != self._parse_expiry(identity.expiry)
                or multiplier != self.contract_profile.contract_multiplier
                or bid <= 0 or ask < bid or last <= 0
                or observed.tzinfo is None or replay_now.tzinfo is None):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S9_SYNTHETIC_QUOTE_IDENTITY_MISMATCH", observed)
        age = (replay_now - observed).total_seconds()
        if age < 0 or Decimal(str(age)) > self.evidence.max_quote_age_seconds:
            return verdict(FreshnessStatus.STALE, "S9_SYNTHETIC_QUOTE_STALE", observed)
        digest = sha256(
            f"{self.manifest_sha256}|{self.dataset_sha256}|{observed.isoformat()}|{instrument_id}|{bid}|{ask}|{last}".encode()
        ).hexdigest()
        return verdict(FreshnessStatus.FRESH, "S9_MANIFEST_BOUND_SYNTHETIC_QUOTE", observed, digest)

    def release_group(self, group_id: str) -> None:
        self._reserved.pop(str(group_id), None)

    def release_all_groups(self) -> None:
        self._reserved.clear()
