from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    FreshnessVerdict,
    evaluate_freshness,
)
from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot
from contracts.types import CanonicalMarketTick
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input
from environments.high_speed.validation_only_s15b_option_adapter import (
    S15BOptionValidationAdapter,
    S15BQuote,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_observed_s1_call_alignment/manifest.json"


class S15BObservedOptionMarketError(ValueError):
    pass


class S15BObservedOptionMarketAdapter:
    """Manifest-bound S15b adapter combining observed VTS index/book with explicit synthetic mark/freshness."""

    def __init__(self, manifest_path: Path = DEFAULT_MANIFEST, *, project_root: Path | None = None) -> None:
        self.manifest_path = Path(manifest_path)
        self.root = Path(project_root).resolve() if project_root is not None else self.manifest_path.parents[3]
        self.manifest_bytes = self.manifest_path.read_bytes()
        self.manifest_sha256 = hashlib.sha256(self.manifest_bytes).hexdigest()
        self.manifest = json.loads(self.manifest_bytes)
        self._validate_manifest()
        self.dataset_path = self._within_root(self.manifest["dataset_path"])
        raw = self.dataset_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.manifest["dataset_sha256"]:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_DATASET_HASH_MISMATCH")
        self.events = tuple(json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip())
        if len(self.events) != self.manifest["event_count"]:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_EVENT_COUNT_MISMATCH")
        self.by_type = {event["event_type"]: event for event in self.events}
        if len(self.by_type) != len(self.events):
            raise S15BObservedOptionMarketError("S15B_OBSERVED_DUPLICATE_EVENT_TYPE")
        self._validate_source_records()
        self._validate_scenario()
        self._identity_adapter = S15BOptionValidationAdapter(project_root=self.root)
        self._book_observation = KISIndexOptionMarketWebSocketAdapter().adapt(
            self.by_type["OPTION_ORDERBOOK"]["source"]["payload"]
        )
        parsed_book = self._book_observation.order_book
        if parsed_book is None:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_ORDERBOOK_MISSING")
        self._book = OptionOrderBookSnapshot(
            symbol=parsed_book.symbol,
            observed_hour=parsed_book.observed_hour,
            ask_levels=tuple(OptionOrderBookLevel(level.price, level.quantity) for level in parsed_book.ask_levels),
            bid_levels=tuple(OptionOrderBookLevel(level.price, level.quantity) for level in parsed_book.bid_levels),
            source="OBSERVED_KIS_VTS:H0IOASP0:VALIDATION_ONLY",
        )
        if not S15BOptionValidationAdapter.is_complete_order_book_snapshot(self._book):
            raise S15BObservedOptionMarketError("S15B_OBSERVED_ORDERBOOK_STRICT_GATE_FAILED")

    def _within_root(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_PATH_OUTSIDE_PROJECT_ROOT")
        if not candidate.is_file():
            raise FileNotFoundError(str(candidate))
        return candidate

    def _validate_manifest(self) -> None:
        m = self.manifest
        if (m.get("schema") != "q25-a5-s15b-observed-s1-call-alignment-manifest-v1"
                or m.get("validation_only") is not True
                or m.get("synthetic") is not True
                or m.get("provenance") != "DERIVED_SCENARIO"):
            raise S15BObservedOptionMarketError("S15B_OBSERVED_VALIDATION_MANIFEST_INVALID")
        for key in ("runtime_eligible", "production_runtime_eligible", "execution_enabled", "orders_allowed",
                    "allow_kis_api", "allow_live_orders", "allow_real_account", "original_source_mutated", "s15a_mutated"):
            if m.get(key) is not False:
                raise S15BObservedOptionMarketError(f"S15B_OBSERVED_SAFETY_FLAG_NOT_FALSE:{key}")
        if not isinstance(m.get("source_raw_file_sha256"), str) or len(m["source_raw_file_sha256"]) != 64:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_RAW_FILE_HASH_REQUIRED")
        if m.get("freshness_policy", {}).get("production_freshness_eligible") is not False:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_PRODUCTION_FRESHNESS_MUST_REMAIN_FALSE")
        if m.get("multiplier_profile", {}).get("production_runtime_eligible") is not False:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_MULTIPLIER_PROFILE_MUST_REMAIN_VALIDATION_ONLY")

    def _validate_source_records(self) -> None:
        expected_raw_sha = self.manifest["source_raw_file_sha256"]
        source_events = ("UNDERLYING_ANCHOR", "UNDERLYING_MARKET_EVENT", "OPTION_ORDERBOOK")
        for event_type in source_events:
            event = self.by_type.get(event_type)
            if event is None or event.get("provenance") != "OBSERVED_KIS_VTS":
                raise S15BObservedOptionMarketError(f"S15B_OBSERVED_SOURCE_EVENT_MISSING:{event_type}")
            source = event.get("source") or {}
            if source.get("raw_file_sha256") != expected_raw_sha:
                raise S15BObservedOptionMarketError("S15B_OBSERVED_RAW_FILE_HASH_BINDING_MISMATCH")
            payload = str(source.get("payload") or "")
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != source.get("payload_sha256"):
                raise S15BObservedOptionMarketError("S15B_OBSERVED_PAYLOAD_HASH_MISMATCH")
            if source.get("tr_id") not in {"H0UPCNT0", "H0IOASP0"}:
                raise S15BObservedOptionMarketError("S15B_OBSERVED_SOURCE_TR_ID_INVALID")
            if datetime.fromisoformat(source["received_at"]).tzinfo is None:
                raise S15BObservedOptionMarketError("S15B_OBSERVED_RECEIVE_TIMEZONE_REQUIRED")

    def _validate_scenario(self) -> None:
        signal = self.by_type.get("STRATEGY_SIGNAL_SCENARIO")
        mark = self.by_type.get("SYNTHETIC_MARK_PRICE")
        if signal is None or mark is None:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_SCENARIO_EVENT_MISSING")
        if signal.get("validation_only") is not True or signal.get("runtime_eligible") is not False:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_SIGNAL_SCENARIO_NOT_VALIDATION_ONLY")
        if mark.get("validation_only") is not True or mark.get("actual_trade_price") is not None:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_SYNTHETIC_MARK_INVALID")
        mapping = self.manifest.get("scenario_contract_mapping", {})
        if "S1_SHORT_CALL_887_5" not in mapping:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_SCENARIO_CONTRACT_MAPPING_MISSING")
        contract = mapping["S1_SHORT_CALL_887_5"]
        if (contract.get("symbol") != "B01611887" or contract.get("option_type") != "CALL"
                or Decimal(str(contract.get("strike"))) != Decimal("887.50")
                or contract.get("expiry") != "20261112"
                or contract.get("master_sha256") != self.manifest["target_kis_master_sha256"]):
            raise S15BObservedOptionMarketError("S15B_OBSERVED_SCENARIO_CONTRACT_MAPPING_INVALID")

    @property
    def scenario_id(self) -> str:
        return str(self.manifest["scenario_ids"][0])

    @property
    def expected_proposal(self) -> dict[str, Any]:
        return dict(self.by_type["STRATEGY_SIGNAL_SCENARIO"]["expected_proposal"])

    def contract_mapping(self, scenario_contract_key: str) -> dict[str, Any]:
        mapping = self.manifest.get("scenario_contract_mapping", {}).get(scenario_contract_key)
        if mapping is None:
            raise S15BObservedOptionMarketError("S15B_SCENARIO_CONTRACT_KEY_UNKNOWN")
        return dict(mapping)

    def identity(self, scenario_contract_key: str):
        mapping = self.contract_mapping(scenario_contract_key)
        identity = self._identity_adapter.identity(mapping["symbol"], "fresh_two_sided")
        if identity is None:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_OPTION_IDENTITY_UNAVAILABLE")
        if (identity.symbol != mapping["symbol"] or identity.option_type != mapping["option_type"]
                or identity.strike != Decimal(mapping["strike"]) or identity.expiry != mapping["expiry"]):
            raise S15BObservedOptionMarketError("S15B_OBSERVED_OPTION_IDENTITY_MISMATCH")
        multiplier = Decimal(str(self.manifest["multiplier_profile"]["value"]))
        return replace(
            identity,
            contract_multiplier=multiplier,
            identity_source=f"{identity.identity_source}|KRX_STANDARD_MULTIPLIER_VALIDATION_ONLY",
        )

    def order_book(self, scenario_contract_key: str) -> OptionOrderBookSnapshot:
        mapping = self.contract_mapping(scenario_contract_key)
        if mapping["symbol"] != self._book.symbol:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_ORDERBOOK_SYMBOL_MISMATCH")
        return self._book

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        mapping = self.contract_mapping("S1_SHORT_CALL_887_5")
        if str(symbol).strip() != mapping["symbol"]:
            return None
        snapshot = self.order_book("S1_SHORT_CALL_887_5")
        if not S15BOptionValidationAdapter.is_complete_order_book_snapshot(snapshot):
            return None
        return snapshot

    def quote(self, scenario_contract_key: str) -> S15BQuote:
        identity = self.identity(scenario_contract_key)
        book = self.order_book(scenario_contract_key)
        bid = book.bid_levels[0].price
        ask = book.ask_levels[0].price
        mark = (bid + ask) / Decimal("2")
        received_at = datetime.fromisoformat(self.by_type["OPTION_ORDERBOOK"]["source"]["received_at"])
        return S15BQuote(
            instrument_id=identity.instrument_id,
            symbol=identity.symbol,
            bid=bid,
            ask=ask,
            last=mark,
            provenance="MIXED:OBSERVED_KIS_VTS+SYNTHETIC:DERIVED_SCENARIO",
            scenario_id=self.scenario_id,
            source_timestamp=received_at,
            received_at=received_at,
            payload_sha256=self.by_type["OPTION_ORDERBOOK"]["source"]["payload_sha256"],
        )

    def freshness(self, scenario_contract_key: str) -> FreshnessVerdict:
        quote = self.quote(scenario_contract_key)
        identity = self.identity(scenario_contract_key)
        policy = FreshnessPolicy(
            version=str(self.manifest["freshness_policy"]["version"]),
            source_age_enabled=True,
            max_age=timedelta(seconds=int(self.manifest["freshness_policy"]["max_age_seconds"])),
            max_future_skew=timedelta(seconds=1),
        )
        evidence = FreshnessEvidence(
            source="SYNTHETIC:DERIVED_SCENARIO",
            endpoint="synthetic://s15b-observed-orderbook-replay",
            tr_id="S15B_OBSERVED_VALIDATION",
            environment="SYNTHETIC",
            instrument_id=quote.instrument_id,
            symbol=identity.symbol,
            raw_source_time=quote.source_timestamp.isoformat() if quote.source_timestamp else "",
            source_instant=quote.source_timestamp,
            received_at=quote.received_at,
            raw_payload_sha256=quote.payload_sha256,
            source_time_semantics_verified=True,
            capability_verified=True,
            metadata={
                "synthetic": "true",
                "validation_only": "true",
                "timestamp_basis": "COLLECTOR_RECEIVED_AT_ONLY",
                "observed_market_fields": "H0IOASP0_BID_ASK_DEPTH",
                "h0ioasp0_observed_hour_semantics_verified": "false",
                "master_sha256": self.manifest["target_kis_master_sha256"],
            },
        )
        return evaluate_freshness(
            evidence,
            policy=policy,
            expected_instrument_id=identity.instrument_id,
            expected_symbol=identity.symbol,
            expected_environment="SYNTHETIC",
        )

    def apply_to_strategy(self, strategy: Any) -> None:
        meta = self.by_type["STRATEGY_SIGNAL_SCENARIO"]["strategy"]
        if getattr(strategy, "strategy_id", None) != meta["strategy_id"]:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_STRATEGY_ID_MISMATCH")
        if getattr(strategy, "version", None) != meta["code_version"]:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_STRATEGY_VERSION_MISMATCH")
        strategy.runtime_config_verified = bool(meta["runtime_config_verified_test_only"])
        strategy.risk_limits_available = bool(meta["risk_limits_available_test_only"])

    def build_strategy_context(self) -> StrategyContext:
        event = self.by_type["UNDERLYING_MARKET_EVENT"]
        source = event["source"]
        parts = str(source["payload"]).split("|")
        if len(parts) != 4 or parts[1] != "H0UPCNT0":
            raise S15BObservedOptionMarketError("S15B_OBSERVED_UNDERLYING_FRAME_INVALID")
        fields = parts[3].split("^")
        price = Decimal(str(event["value"]["price"]))
        if fields[0] != "2001" or Decimal(fields[2]) != price:
            raise S15BObservedOptionMarketError("S15B_OBSERVED_UNDERLYING_EVENT_MISMATCH")
        observed_at = datetime.fromisoformat(source["received_at"]).astimezone(timezone(timedelta(hours=9)))
        tick = CanonicalMarketTick(instrument_id="KOSPI200", observed_at=observed_at, price=price)
        market_state = MarketState(as_of=observed_at, ticks={"KOSPI200": tick}, quality={})
        strategy_meta = self.by_type["STRATEGY_SIGNAL_SCENARIO"]["strategy"]
        payload = Track1Input(
            days_to_expiry=float(strategy_meta["days_to_expiry_test_value"]),
            current_time=observed_at,
            reference_point=Decimal(str(strategy_meta["initial_reference_point"])),
            reference_point_verified=True,
            open_short_quantity=int(strategy_meta["open_short_quantity_test_value"]),
            pending_short_quantity=int(strategy_meta["pending_short_quantity_test_value"]),
            exposure_snapshot_verified=True,
            dte_basis_verified=True,
        )
        return StrategyContext(
            market_state=market_state,
            strategy_id=strategy_meta["strategy_id"],
            input=StrategyInput(payload=payload),
        )
