"""S15b-only adapter for KIS Option Master short-code identity and quote scenarios.

This adapter is deliberately isolated from production composition. It maps the
approved KIS shrn_iscd field to OptionInstrumentIdentity.instrument_id only
for the manifest-bound S15b DERIVED_SCENARIO dataset.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessEvidence, FreshnessPolicy, FreshnessVerdict, evaluate_freshness
from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot
from contracts.types import OptionInstrumentIdentity

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"
DEFAULT_ORDERBOOK_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_orderbook_supplement/manifest.json"


class S15BValidationAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class S15BQuote:
    instrument_id: str
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    provenance: str
    scenario_id: str | None
    source_timestamp: datetime | None
    received_at: datetime | None
    payload_sha256: str | None


class S15BOptionValidationAdapter:
    """Read-only manifest-bound identity/quote/freshness adapter; never submits orders."""

    def __init__(
        self,
        manifest_path: Path = DEFAULT_MANIFEST,
        *,
        project_root: Path | None = None,
        order_book_manifest_path: Path = DEFAULT_ORDERBOOK_MANIFEST,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.root = Path(project_root).resolve() if project_root is not None else self.manifest_path.parents[3]
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._validate_manifest()
        self.dataset_path = self.root / self.manifest["dataset_path"]
        raw = self.dataset_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.manifest["dataset_sha256"]:
            raise S15BValidationAdapterError("S15B_DATASET_HASH_MISMATCH")
        self.rows = tuple(json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip())
        if any(row.get("master_sha256") != self.manifest["target_kis_master_sha256"] for row in self.rows if row.get("master_sha256")):
            raise S15BValidationAdapterError("S15B_ROW_MASTER_HASH_MISMATCH")
        if len(self.rows) != self.manifest["event_count"]:
            raise S15BValidationAdapterError("S15B_DATASET_EVENT_COUNT_MISMATCH")

        self.order_book_manifest_path = Path(order_book_manifest_path)
        self.order_book_manifest = json.loads(self.order_book_manifest_path.read_text(encoding="utf-8"))
        self._validate_order_book_manifest()
        order_book_path = self.root / self.order_book_manifest["dataset_path"]
        order_book_raw = order_book_path.read_bytes()
        if hashlib.sha256(order_book_raw).hexdigest() != self.order_book_manifest["dataset_sha256"]:
            raise S15BValidationAdapterError("S15B_ORDERBOOK_DATASET_HASH_MISMATCH")
        self.order_book_rows = tuple(
            json.loads(line) for line in order_book_raw.decode("utf-8").splitlines() if line.strip()
        )
        if len(self.order_book_rows) != self.order_book_manifest["event_count"]:
            raise S15BValidationAdapterError("S15B_ORDERBOOK_EVENT_COUNT_MISMATCH")
        if any(row.get("master_sha256") != self.manifest["target_kis_master_sha256"] for row in self.order_book_rows):
            raise S15BValidationAdapterError("S15B_ORDERBOOK_MASTER_HASH_MISMATCH")

    def _validate_manifest(self) -> None:
        m = self.manifest
        if m.get("validation_only") is not True or m.get("provenance") != "DERIVED_SCENARIO":
            raise S15BValidationAdapterError("S15B_VALIDATION_ONLY_MANIFEST_REQUIRED")
        for key in ("runtime_eligible", "production_runtime_eligible", "execution_enabled",
                    "orders_allowed", "allow_kis_api", "allow_live_orders", "allow_real_account"):
            if m.get(key) is not False:
                raise S15BValidationAdapterError(f"S15B_SAFETY_FLAG_NOT_FALSE:{key}")
        if not isinstance(m.get("target_kis_master_sha256"), str) or len(m["target_kis_master_sha256"]) != 64:
            raise S15BValidationAdapterError("S15B_KIS_MASTER_HASH_REQUIRED")

    def _validate_order_book_manifest(self) -> None:
        m = self.order_book_manifest
        if m.get("validation_only") is not True or m.get("provenance") != "DERIVED_SCENARIO":
            raise S15BValidationAdapterError("S15B_ORDERBOOK_VALIDATION_ONLY_MANIFEST_REQUIRED")
        for key in ("runtime_eligible", "production_runtime_eligible", "execution_enabled", "orders_allowed",
                    "allow_kis_api", "allow_live_orders", "allow_real_account"):
            if m.get(key) is not False:
                raise S15BValidationAdapterError(f"S15B_ORDERBOOK_SAFETY_FLAG_NOT_FALSE:{key}")
        if m.get("source_quote_manifest_sha256") != hashlib.sha256(self.manifest_path.read_bytes()).hexdigest():
            raise S15BValidationAdapterError("S15B_ORDERBOOK_QUOTE_MANIFEST_HASH_MISMATCH")
        if m.get("source_quote_dataset_sha256") != self.manifest.get("dataset_sha256"):
            raise S15BValidationAdapterError("S15B_ORDERBOOK_QUOTE_DATASET_HASH_MISMATCH")
        if m.get("target_kis_master_sha256") != self.manifest.get("target_kis_master_sha256"):
            raise S15BValidationAdapterError("S15B_ORDERBOOK_MASTER_BINDING_MISMATCH")

    def _row(self, symbol: str, scenario_id: str | None = None) -> dict[str, Any] | None:
        matches = [
            row for row in self.rows
            if row.get("symbol") == symbol
            and (scenario_id is None or row.get("scenario_id") == scenario_id)
        ]
        if len(matches) > 1:
            raise S15BValidationAdapterError("S15B_DUPLICATE_CONTRACT_SCENARIO")
        return matches[0] if matches else None

    def identity(self, symbol: str, scenario_id: str | None = None) -> OptionInstrumentIdentity | None:
        row = self._row(symbol, scenario_id)
        if row is None or row.get("record_type") == "OBSERVATION_GAP":
            return None
        if row.get("validation_only") is not True:
            raise S15BValidationAdapterError("S15B_ROW_NOT_VALIDATION_ONLY")
        if row.get("master_sha256") != self.manifest["target_kis_master_sha256"]:
            raise S15BValidationAdapterError("S15B_ROW_MASTER_HASH_MISMATCH")
        # Approved isolated exception: KIS Option Master shrn_iscd is the ID.
        shrn_iscd = str(row.get("symbol") or "").strip()
        if not shrn_iscd:
            raise S15BValidationAdapterError("S15B_SHRN_ISCD_IDENTITY_MISMATCH")
        if row.get("provenance") not in {"OBSERVED_KIS_VTS", "SYNTHETIC:DERIVED_SCENARIO"}:
            raise S15BValidationAdapterError("S15B_UNSUPPORTED_ROW_PROVENANCE")
        return OptionInstrumentIdentity(
            instrument_id=shrn_iscd,
            symbol=shrn_iscd,
            expiry=str(row["expiry"]),
            option_type=str(row["option_type"]),
            strike=Decimal(str(row["strike"])),
            contract_multiplier=None,
            identity_source=f"KIS_OPTION_MASTER:shrn_iscd:VALIDATION_ONLY:{self.manifest['target_kis_master_sha256']}",
        )

    def quote(self, symbol: str, scenario_id: str | None = None) -> S15BQuote | None:
        row = self._row(symbol, scenario_id)
        identity = self.identity(symbol, scenario_id)
        if row is None or identity is None:
            return None
        quote = row.get("quote") or {}
        bid = Decimal(str(quote["bid"])) if quote.get("bid") not in (None, "") else None
        ask = Decimal(str(quote["ask"])) if quote.get("ask") not in (None, "") else None
        last = Decimal(str(quote["last"])) if quote.get("last") not in (None, "") else None
        if bid is not None and bid <= 0:
            bid = None
        if ask is not None and ask <= 0:
            ask = None
        source_time = datetime.fromisoformat(row["source_timestamp"]) if row.get("source_timestamp") else None
        received_at = datetime.fromisoformat(row["received_at"]) if row.get("received_at") else None
        return S15BQuote(
            instrument_id=str(row.get("instrument_id") or "").strip(),
            symbol=identity.symbol,
            bid=bid,
            ask=ask,
            last=last,
            provenance=str(row["provenance"]),
            scenario_id=row.get("scenario_id"),
            source_timestamp=source_time,
            received_at=received_at,
            payload_sha256=row.get("payload_sha256"),
        )

    @staticmethod
    def is_complete_order_book_snapshot(
        snapshot: OptionOrderBookSnapshot | None,
        *,
        depth: int = 5,
    ) -> bool:
        """Strict S15b-only depth gate; the shared production contract is unchanged."""
        if snapshot is None or isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            return False
        if not str(snapshot.symbol).strip():
            return False
        for levels in (snapshot.ask_levels, snapshot.bid_levels):
            if len(levels) < depth:
                return False
            for level in levels[:depth]:
                if not level.price.is_finite() or level.price <= 0:
                    return False
                if not level.quantity.is_finite() or level.quantity <= 0:
                    return False
        asks = tuple(level.price for level in snapshot.ask_levels[:depth])
        bids = tuple(level.price for level in snapshot.bid_levels[:depth])
        if any(left >= right for left, right in zip(asks, asks[1:])):
            return False
        if any(left <= right for left, right in zip(bids, bids[1:])):
            return False
        if bids[0] >= asks[0]:
            return False
        return True

    def order_book(self, symbol: str, scenario_id: str | None = None) -> OptionOrderBookSnapshot | None:
        matches = [
            row for row in self.order_book_rows
            if row.get("symbol") == symbol
            and (scenario_id is None or row.get("scenario_id") == scenario_id)
        ]
        if len(matches) > 1:
            raise S15BValidationAdapterError("S15B_DUPLICATE_ORDERBOOK_CONTRACT_SCENARIO")
        if not matches:
            return None
        row = matches[0]
        if row.get("validation_only") is not True or row.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO":
            raise S15BValidationAdapterError("S15B_ORDERBOOK_ROW_PROVENANCE_INVALID")
        if row.get("quote_dataset_sha256") != self.manifest.get("dataset_sha256"):
            raise S15BValidationAdapterError("S15B_ORDERBOOK_ROW_QUOTE_HASH_MISMATCH")
        if self.identity(symbol, row.get("quote_scenario_id")) is None:
            return None
        asks = tuple(
            OptionOrderBookLevel(Decimal(str(level["price"])), Decimal(str(level["quantity"])))
            for level in row.get("ask_levels", [])
        )
        bids = tuple(
            OptionOrderBookLevel(Decimal(str(level["price"])), Decimal(str(level["quantity"])))
            for level in row.get("bid_levels", [])
        )
        return OptionOrderBookSnapshot(
            symbol=symbol,
            observed_hour=str(row.get("observed_hour") or ""),
            ask_levels=asks,
            bid_levels=bids,
            source=f"SYNTHETIC:DERIVED_SCENARIO:{row.get('scenario_id')}",
        )

    def freshness(
        self,
        symbol: str,
        scenario_id: str,
        *,
        policy: FreshnessPolicy | None = None,
    ) -> FreshnessVerdict:
        quote = self.quote(symbol, scenario_id)
        identity = self.identity(symbol, scenario_id)
        active_policy = policy or FreshnessPolicy(
            version="S15B_SYNTHETIC_VALIDATION_ONLY",
            source_age_enabled=True,
            max_age=timedelta(seconds=int(self.manifest["freshness_max_age_seconds"])),
            max_future_skew=timedelta(seconds=1),
        )
        if quote is None or identity is None or quote.provenance != "SYNTHETIC:DERIVED_SCENARIO":
            return evaluate_freshness(None, policy=active_policy)
        evidence = FreshnessEvidence(
            source="SYNTHETIC:DERIVED_SCENARIO",
            endpoint="synthetic://s15b-option-quote",
            tr_id="S15B_SYNTHETIC",
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
                "master_sha256": self.manifest["target_kis_master_sha256"],
                "identity_source_field": "shrn_iscd",
            },
        )
        return evaluate_freshness(
            evidence,
            policy=active_policy,
            expected_instrument_id=identity.instrument_id,
            expected_symbol=identity.symbol,
            expected_environment="SYNTHETIC",
        )
