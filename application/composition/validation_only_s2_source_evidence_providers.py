
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


class _ScopedS2EvidenceProvider:
    def __init__(self, *, scope_provider: Any, candidate_id: str) -> None:
        if not callable(getattr(scope_provider, "is_applicable", None)):
            raise TypeError("T9_SCOPED_TICK_PROVIDER_REQUIRED")
        self.scope_provider = scope_provider
        self.candidate_id = str(candidate_id)
        self.last_diagnostic = "NOT_EVALUATED"

    def is_applicable(self, tick: Any) -> bool:
        return bool(self.scope_provider.is_applicable(tick))

    @staticmethod
    def _aware(value: Any) -> datetime:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("T9_SOURCE_TIMESTAMP_TIMEZONE_REQUIRED")
        return parsed

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"T9_JSON_OBJECT_REQUIRED:{path.name}")
        return value

    def _candidate_inputs(self, root: Path) -> dict[str, Any]:
        path = root / "data" / "derived_scenario" / (
            "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
        ) / "candidate_inputs.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        candidate = next((row for row in rows if row.get("candidate_id") == self.candidate_id), None)
        if candidate is None:
            raise ValueError("T9_SCENARIO_CANDIDATE_NOT_FOUND")
        if self._sha256(path) != "d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32":
            raise ValueError("T9_CANDIDATE_INPUTS_SHA256_MISMATCH")
        return candidate

    def _accepted_rows(self, accepted_root: Path, trading_date: str) -> tuple[dict[str, Any], ...]:
        manifest_path = accepted_root / "manifest.json"
        manifest = self._load_json(manifest_path)
        if manifest.get("acceptance") != "ACCEPTED_FOR_PROJECT_VERIFICATION":
            raise ValueError("T9_ACCEPTED_MANIFEST_NOT_ACCEPTED")
        day = next((item for item in manifest.get("days", ()) if item.get("date") == trading_date), None)
        if day is None:
            raise ValueError(f"T9_ACCEPTED_DAY_NOT_FOUND:{trading_date}")
        partition = accepted_root / f"{trading_date}.jsonl"
        if not partition.is_file() or self._sha256(partition) != day.get("sha256"):
            raise ValueError(f"T9_ACCEPTED_PARTITION_HASH_MISMATCH:{trading_date}")
        rows = tuple(
            json.loads(line)
            for line in partition.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        return rows

    @staticmethod
    def _matching_original_rows(
        rows: tuple[dict[str, Any], ...],
        candidate: Mapping[str, Any],
        timestamp: str,
    ) -> tuple[dict[str, Any], ...]:
        matches = []
        for leg in candidate.get("legs", ()):
            target = (
                str(candidate.get("expiry")),
                str(leg.get("option_type", "")).upper(),
                Decimal(str(leg.get("strike"))),
            )
            found = [
                row for row in rows
                if str(row.get("tick", {}).get("timestamp")) == timestamp
                and str(row.get("tick", {}).get("expiry")) == target[0]
                and str(row.get("tick", {}).get("option_type", "")).upper() == target[1]
                and Decimal(str(row.get("tick", {}).get("strike_price", "NaN"))) == target[2]
                and str(row.get("tick", {}).get("option_source", "")).startswith("KIS:")
                and "SYNTHETIC" not in str(row.get("tick", {}).get("option_source", "")).upper()
                and "bid_price" not in row.get("scenario_metadata", {}).get("generated_fields", ())
                and "ask_price" not in row.get("scenario_metadata", {}).get("generated_fields", ())
            ]
            if len(found) == 1:
                matches.append(found[0])
        return tuple(matches)


class ValidationOnlyS2AcceptedOriginalPrimaryProvider(_ScopedS2EvidenceProvider):
    """Use exact accepted source observations only; never synthesize a primary quote."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        scope_provider: Any,
        candidate_id: str = "S2-CANDIDATE-001",
        candidate_builder: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(scope_provider=scope_provider, candidate_id=candidate_id)
        self.root = Path(project_root).resolve()
        self.accepted_root = self.root / "data" / "accepted_market_data" / "runtime_v2"
        self.candidate_builder = candidate_builder

    def __call__(self, tick: Any):
        if not self.is_applicable(tick):
            self.last_diagnostic = "TICK_OUTSIDE_EVIDENCE_SCOPE"
            return None
        candidate = self._candidate_inputs(self.root)
        tick_time = self._aware(getattr(tick, "timestamp", None))
        if tick_time != self._aware(candidate.get("observed_at")):
            self.last_diagnostic = "ACCEPTED_ORIGINAL_TICK_TIME_MISMATCH"
            return None
        rows = self._accepted_rows(self.accepted_root, tick_time.strftime("%Y%m%d"))
        exact = self._matching_original_rows(rows, candidate, tick_time.isoformat())
        if len(exact) != 4:
            self.last_diagnostic = f"ACCEPTED_ORIGINAL_SYNCHRONOUS_LEG_COVERAGE_{len(exact)}_OF_4"
            return None
        if self.candidate_builder is None:
            self.last_diagnostic = "ACCEPTED_QUOTES_PRESENT_INDEPENDENT_BROKER_AND_FRESHNESS_SOURCES_REQUIRED"
            return None
        result = self.candidate_builder(tick=tick, candidate=candidate, original_rows=exact)
        self.last_diagnostic = "ACCEPTED_ORIGINAL_CANDIDATE_BUILT" if result is not None else "ACCEPTED_ORIGINAL_CANDIDATE_BUILDER_UNAVAILABLE"
        return result


class ValidationOnlyS2NotionSourceReconciliationProvider(_ScopedS2EvidenceProvider):
    """Reconcile No.1534 decisions, accepted lineage, and original WS file hashes read-only."""

    REQUIRED_DECISIONS = ("No.1534", "No.1535", "No.1538", "No.1554", "No.1555")

    def __init__(
        self,
        *,
        project_root: str | Path,
        original_source_root: str | Path,
        scope_provider: Any,
        notion_decision_refs: tuple[str, ...],
        candidate_id: str = "S2-CANDIDATE-001",
        candidate_builder: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(scope_provider=scope_provider, candidate_id=candidate_id)
        missing = tuple(value for value in self.REQUIRED_DECISIONS if value not in notion_decision_refs)
        if missing:
            raise ValueError("T9_REQUIRED_NOTION_DECISIONS_MISSING:" + ",".join(missing))
        self.notion_decision_refs = tuple(notion_decision_refs)
        self.root = Path(project_root).resolve()
        self.original_root = Path(original_source_root).resolve()
        self.accepted_root = self.root / "data" / "accepted_market_data" / "runtime_v2"
        self.scenario_dir = self.root / "data" / "derived_scenario" / (
            "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
        )
        self.candidate_builder = candidate_builder

    def __call__(self, tick: Any, attempts: tuple[str, ...] = ()):
        del attempts
        if not self.is_applicable(tick):
            self.last_diagnostic = "TICK_OUTSIDE_EVIDENCE_SCOPE"
            return None
        candidate = self._candidate_inputs(self.root)
        as_of = self._aware(getattr(tick, "timestamp", None))
        trading_date = as_of.strftime("%Y%m%d")
        day_root = self.original_root / trading_date
        day_manifest_path = day_root / "manifest.json"
        raw_manifest_path = day_root / "kis_vts_websocket_raw.jsonl.manifest.json"
        day_manifest = self._load_json(day_manifest_path)
        raw_manifest = self._load_json(raw_manifest_path)
        raw_name = "kis_vts_websocket_raw.jsonl"
        raw_file = day_root / raw_name
        if day_manifest.get("trading_date") != trading_date or raw_manifest.get("trading_date") != trading_date:
            raise ValueError("T9_ORIGINAL_SOURCE_TRADING_DATE_MISMATCH")
        listed = next((item for item in day_manifest.get("files", ()) if item.get("path") == raw_name), None)
        raw_digest = str(raw_manifest.get("file_sha256") or "").lower()
        if listed is None or str(listed.get("sha256") or "").lower() != raw_digest:
            raise ValueError("T9_ORIGINAL_DAY_MANIFEST_CROSSWALK_MISMATCH")
        if not raw_file.is_file() or self._sha256(raw_file) != raw_digest:
            raise ValueError("T9_ORIGINAL_WS_RAW_SHA256_MISMATCH")
        if raw_manifest.get("source") != "KIS_VTS_WEBSOCKET_RAW" or raw_manifest.get("record_count", 0) <= 0:
            raise ValueError("T9_ORIGINAL_WS_RAW_MANIFEST_INVALID")

        accepted_manifest = self._load_json(self.accepted_root / "manifest.json")
        scenario_manifest = self._load_json(self.scenario_dir / "manifest.json")
        if accepted_manifest.get("registry_id") != scenario_manifest.get("base_registry_id"):
            raise ValueError("T9_ACCEPTED_SCENARIO_REGISTRY_CROSSWALK_MISMATCH")
        if not str(scenario_manifest.get("status", "")).startswith("SYNTHETIC_VALIDATION_ONLY"):
            raise ValueError("T9_SCENARIO_NOT_VALIDATION_ONLY")
        rows = self._accepted_rows(self.accepted_root, trading_date)
        source_hashes = {
            str(row.get("scenario_metadata", {}).get("source_raw_sha256") or "").lower()
            for row in rows
        }
        if source_hashes != {raw_digest}:
            raise ValueError("T9_ACCEPTED_TO_ORIGINAL_RAW_LINEAGE_MISMATCH")

        candidate_time = self._aware(candidate.get("observed_at"))
        underlying_anchor_rows = [
            row for row in rows
            if str(row.get("tick", {}).get("timestamp")) == candidate_time.isoformat()
            and Decimal(str(row.get("tick", {}).get("underlying_price"))) == Decimal(str(candidate.get("underlying_price")))
        ]
        if not underlying_anchor_rows:
            raise ValueError("T9_ACCEPTED_UNDERLYING_SCENARIO_ANCHOR_MISSING")
        quote_rows = [
            json.loads(line)
            for line in (self.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        selected_quotes = [row for row in quote_rows if row.get("candidate_id") == self.candidate_id]
        anchor_ids = {
            str(value)
            for row in selected_quotes
            for value in row.get("market_calibration", {}).get("iv_anchor_observation_ids", ())
        }
        accepted_observation_ids = {
            str(row.get("scenario_metadata", {}).get("source_observation_id") or "")
            for row in rows
        }
        if not anchor_ids or not anchor_ids.issubset(accepted_observation_ids):
            raise ValueError("T9_SCENARIO_ANCHOR_NOT_FOUND_IN_ACCEPTED_ORIGINAL_LINEAGE")

        exact = self._matching_original_rows(rows, candidate, as_of.isoformat())
        if len(exact) != 4:
            self.last_diagnostic = (
                "NOTION_SOURCE_RECONCILIATION_VERIFIED:"
                + ",".join(self.notion_decision_refs)
                + ":RAW_WS_SHA256_MATCHED:ANCHORS_"
                + str(len(anchor_ids))
                + "_OF_"
                + str(len(anchor_ids))
                + ":ORIGINAL_LEG_COVERAGE_"
                + str(len(exact))
                + "_OF_4"
            )
            return None
        if self.candidate_builder is None:
            self.last_diagnostic = "ORIGINAL_4LEG_QUOTES_PRESENT_INDEPENDENT_BROKER_SNAPSHOT_REQUIRED"
            return None
        result = self.candidate_builder(tick=tick, candidate=candidate, original_rows=exact)
        self.last_diagnostic = "NOTION_SOURCE_RECONCILIATION_CANDIDATE_BUILT" if result is not None else "NOTION_SOURCE_RECONCILIATION_CANDIDATE_BUILDER_UNAVAILABLE"
        return result

Path(r'C:\Users\white\Desktop\MovingProject\Q25_A8_R10\application\composition\validation_only_s2_source_evidence_providers.py').write_text(Path(__file__).read_text(encoding='utf-8'), encoding='utf-8')
