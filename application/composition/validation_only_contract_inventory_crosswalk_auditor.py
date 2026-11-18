"""Validation-only contract inventory and identity crosswalk audit (FRESH-51)."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


class ValidationOnlyContractInventoryCrosswalkAuditor:
    REPORT_VERSION = "Q25-A8-VALIDATION-ONLY-CONTRACT-INVENTORY-CROSSWALK-v1"
    _TYPE_SIDE = {
        "5": "CALL", "6": "PUT", "D": "CALL", "E": "PUT",
        "L": "CALL", "M": "PUT", "N": "CALL", "O": "PUT",
    }

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("CONTRACT_INVENTORY_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _decimal(value: Any) -> str:
        try:
            return format(Decimal(str(value).replace(",", "")).normalize(), "f")
        except (InvalidOperation, ValueError, TypeError):
            return ""

    @staticmethod
    def _time_ordered(first: Any, second: Any) -> bool:
        from datetime import datetime
        try:
            a = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(second).replace("Z", "+00:00"))
            return a.tzinfo is not None and b.tzinfo is not None and a <= b
        except (TypeError, ValueError):
            return False

    @classmethod
    def _master_expiry_label_matches(cls, row: Mapping[str, Any], expiry: str) -> bool:
        name = str(row.get("name") or row.get("master_name") or "")
        monthly = re.search(r"(?<!\d)(20\d{4})(?!\d)", name)
        if monthly:
            return monthly.group(1) == expiry[:6]
        weekly = re.search(r"(?<!\d)(\d{2})(\d{2})W([1-5])(?!\d)", name, re.IGNORECASE)
        if not weekly:
            return False
        try:
            year, month, week = 2000 + int(weekly.group(1)), int(weekly.group(2)), int(weekly.group(3))
            type_code = str(row.get("type_code") or "").upper()
            weekday = 3 if type_code in {"L", "M"} else 0 if type_code in {"N", "O"} else None
            if weekday is None:
                return False
            first = date(year, month, 1)
            day_number = 1 + ((weekday - first.weekday()) % 7) + (week - 1) * 7
            return date.fromisoformat(f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}") == date(year, month, day_number)
        except (ValueError, TypeError):
            return False

    @classmethod
    def _master_identity_match(cls, row: Mapping[str, Any], side: str, month: str, strike: str) -> bool:
        name = str(row.get("name") or row.get("master_name") or "")
        monthly = re.search(r"(?<!\d)(20\d{4})(?!\d)", name)
        weekly = re.search(r"(?<!\d)(\d{2})(\d{2})W[1-5](?!\d)", name, re.IGNORECASE)
        if monthly:
            month_matches = monthly.group(1) == month
        elif weekly:
            month_matches = f"20{weekly.group(1)}{weekly.group(2)}" == month
        else:
            month_matches = False
        return (
            cls._TYPE_SIDE.get(str(row.get("type_code") or "")) == side
            and cls._decimal(row.get("strike")) == cls._decimal(strike)
            and month_matches
            and str(row.get("underlying") or "") == "2001"
        )

    @staticmethod
    def _crosswalk_match(candidates: Sequence[Mapping[str, Any]], side: str, month: str, strike: str) -> bool:
        expected = (side, month, ValidationOnlyContractInventoryCrosswalkAuditor._decimal(strike))
        identities = {
            (str(item.get("side") or ""), str(item.get("month") or ""),
             ValidationOnlyContractInventoryCrosswalkAuditor._decimal(item.get("strike")))
            for item in candidates
        }
        return expected in identities and len(identities) == 1

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def audit(
        self,
        *,
        master_snapshots: Sequence[Mapping[str, Any]],
        expiry_records: Sequence[Mapping[str, Any]],
        krx_crosswalk: Mapping[str, Sequence[Mapping[str, Any]]],
        rest_contracts: Sequence[Mapping[str, Any]],
        websocket_days: Sequence[Mapping[str, Any]],
        websocket_orderbook: Mapping[str, Any],
        time_alignment: Mapping[str, Any],
        source_hashes: Mapping[str, str],
        krx_inventory: Mapping[str, Any],
        synthetic_expiry_assignments: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        issues: list[str] = []
        master_by_hash: dict[str, Mapping[str, Any]] = {}
        legacy_aliases = 0
        for item in master_snapshots:
            declared = str(item.get("archive_sha256") or "").lower()
            actual = str(item.get("actual_archive_sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", declared) or declared != actual:
                issues.append(f"MASTER_ARCHIVE_HASH_MISMATCH:{item.get('manifest_file')}")
                continue
            if item.get("legacy_alias"):
                legacy_aliases += 1
            if item.get("market_date_kst"):
                master_by_hash[declared] = item

        for name, digest in source_hashes.items():
            if not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)):
                issues.append(f"SOURCE_SHA256_INVALID:{name}")

        expiry_details: list[dict[str, Any]] = []
        expiry_codes: set[str] = set()
        expiry_identities: set[tuple[str, str, str]] = set()
        for index, item in enumerate(expiry_records):
            symbol = str(item.get("symbol") or "")
            expiry = str(item.get("expiry") or "")
            side = str(item.get("side") or "")
            strike = self._decimal(item.get("strike"))
            master_hash = str(item.get("master_sha256") or "").lower()
            master_row = item.get("master_row") or {}
            snapshot_ok = master_hash in master_by_hash
            code_ok = bool(item.get("master_code_found")) and bool(master_row)
            identity_ok = (
                code_ok
                and self._TYPE_SIDE.get(str(master_row.get("type_code") or "")) == side
                and self._decimal(master_row.get("strike")) == strike
                and self._master_expiry_label_matches(master_row, expiry)
                and str(master_row.get("underlying") or "") == "2001"
            )
            temporal_ok = self._time_ordered(item.get("requested_at"), item.get("received_at"))
            response_ok = bool(item.get("response_hash_valid")) and bool(item.get("file_hash_valid")) and bool(item.get("http_rt_ok")) and str(item.get("response_expiry") or "") == expiry
            if not (snapshot_ok and identity_ok and temporal_ok and response_ok):
                issues.append(f"EXPIRY_EVIDENCE_MISMATCH:{symbol or index}")
            expiry_codes.add(symbol)
            expiry_identities.add((side, expiry, strike))
            expiry_details.append({
                "symbol": symbol, "expiry": expiry, "side": side, "strike": strike,
                "master_sha256": master_hash, "master_market_date_kst": (master_by_hash.get(master_hash) or {}).get("market_date_kst"),
                "master_code_found": code_ok, "master_identity_match": identity_ok,
                "requested_at": item.get("requested_at"), "received_at": item.get("received_at"),
                "request_before_receive": temporal_ok, "response_and_file_hashes_valid": response_ok,
                "krx_monthly_crosswalk_match": self._crosswalk_match(krx_crosswalk.get(symbol, ()), side, expiry[:6], strike),
            })

        rest_details: list[dict[str, Any]] = []
        rest_codes: set[str] = set()
        rest_identities: set[tuple[str, str, str]] = set()
        for item in rest_contracts:
            symbol = str(item.get("symbol") or "")
            side = str(item.get("side") or "")
            month = str(item.get("month") or "")
            strike = self._decimal(item.get("strike"))
            expiry = str(item.get("expiry") or "")
            candidates = krx_crosswalk.get(symbol, ())
            krx_ok = self._crosswalk_match(candidates, side, month, strike)
            response_ok = int(item.get("request_response_mismatch_count") or 0) == 0
            master_row = item.get("master_postdate_row") or {}
            master_hash = str(item.get("master_postdate_sha256") or "").lower()
            master_snapshot = master_by_hash.get(master_hash)
            master_match = bool(master_snapshot and master_row and self._master_identity_match(master_row, side, month, strike))
            expected_expired_absence = not master_row and expiry < str(item.get("postdate_master_market_date") or "99999999")
            if not (krx_ok and response_ok):
                issues.append(f"REST_CONTRACT_IDENTITY_MISMATCH:{symbol}")
            if master_row and not master_match:
                issues.append(f"REST_POSTDATE_MASTER_IDENTITY_MISMATCH:{symbol}")
            rest_codes.add(symbol)
            rest_identities.add((side, expiry, strike))
            rest_details.append({
                "symbol": symbol, "side": side, "month": month, "strike": strike, "expiry": expiry,
                "row_count": int(item.get("row_count") or 0), "trading_dates": list(item.get("trading_dates") or []),
                "request_response_identity_match": response_ok, "krx_crosswalk_match": krx_ok,
                "postdate_master_match": master_match,
                "postdate_master_absence_expected_after_expiry": bool(expected_expired_absence),
                "postdate_master_market_date": (master_snapshot or {}).get("market_date_kst"),
                "exact_expiry_source": item.get("exact_expiry_source"),
            })

        ws_details: list[dict[str, Any]] = []
        ws_codes: set[str] = set()
        for day in websocket_days:
            symbols = list(day.get("symbols") or [])
            krx_matches = 0
            master_matches = 0
            for item in symbols:
                if isinstance(item, str):
                    symbol, side, month, strike, master_row = item, "", "", "", {}
                else:
                    symbol = str(item.get("symbol") or "")
                    side, month, strike = str(item.get("side") or ""), str(item.get("month") or ""), self._decimal(item.get("strike"))
                    master_row = item.get("master_postdate_row") or {}
                if symbol:
                    ws_codes.add(symbol)
                krx_ok = bool(side and month and strike and self._crosswalk_match(krx_crosswalk.get(symbol, ()), side, month, strike))
                krx_matches += int(krx_ok)
                if side and month and strike and master_row:
                    master_matches += int(self._master_identity_match(master_row, side, month, strike))
            if krx_matches != len(symbols):
                issues.append(f"WEBSOCKET_KRX_CROSSWALK_GAP:{day.get('trading_date')}")
            declared_master = int(day.get("master_postdate_match_count") or 0)
            if declared_master != master_matches:
                issues.append(f"WEBSOCKET_POSTDATE_MASTER_COUNT_MISMATCH:{day.get('trading_date')}")
            ws_details.append({
                "trading_date": str(day.get("trading_date") or ""),
                "raw_frame_count": int(day.get("raw_frame_count") or 0),
                "tr_counts": dict(day.get("tr_counts") or {}),
                "h0iocnt0_frames": int(day.get("h0iocnt0_frames") or 0),
                "parsed_58_field_records": int(day.get("parsed_58_field_records") or 0),
                "unique_symbols": len(symbols), "krx_crosswalk_matches": krx_matches,
                "postdate_master_identity_matches": master_matches,
                "event_time_future_vs_received": int(day.get("event_time_future_vs_received") or 0),
                "source_time_metrics": dict(day.get("source_time_metrics") or {}),
                "exact_expiry_resolution": dict(day.get("exact_expiry_resolution") or {}),
                "source_backed_expiry_symbols": int(day.get("source_backed_expiry_symbols") or 0),
                "synthetic_assigned_symbols": int(day.get("synthetic_assigned_symbols") or 0),
            })

        ob_symbols = list(websocket_orderbook.get("symbols") or [])
        ob_matches = sum(
            1 for item in ob_symbols
            if self._crosswalk_match(krx_crosswalk.get(str(item.get("symbol") or ""), ()),
                                     str(item.get("side") or ""), str(item.get("month") or ""),
                                     self._decimal(item.get("strike")))
        )
        if ob_matches != len(ob_symbols):
            issues.append("WEBSOCKET_ORDERBOOK_KRX_CROSSWALK_GAP")

        expiry_rest_code_overlap = sorted(expiry_codes & rest_codes)
        expiry_rest_identity_overlap = sorted(expiry_identities & rest_identities)
        synthetic_details: list[dict[str, Any]] = []
        rest_by_symbol = {str(x.get("symbol") or ""): x for x in rest_contracts}
        for item in synthetic_expiry_assignments:
            symbol = str(item.get("symbol") or "")
            side = str(item.get("side") or "")
            month = str(item.get("month") or "")
            strike = self._decimal(item.get("strike"))
            expiry = str(item.get("expiry") or "")
            anchors = [str(x) for x in (item.get("source_anchor_symbols") or [])]
            anchor_rows = [rest_by_symbol.get(x) for x in anchors]
            anchor_ok = bool(anchors) and all(
                row is not None and str(row.get("expiry") or "") == str(item.get("source_anchor_expiry") or "")
                and str(row.get("month") or "") == month
                for row in anchor_rows
            )
            source_hash = str(item.get("source_anchor_sha256") or "").lower()
            krx_hash = str(item.get("krx_reference_sha256") or "").lower()
            manifest_hash = str(item.get("source_anchor_manifest_sha256") or "").lower()
            hash_ok = (
                re.fullmatch(r"[0-9a-f]{64}", source_hash) is not None
                and re.fullmatch(r"[0-9a-f]{64}", krx_hash) is not None
                and re.fullmatch(r"[0-9a-f]{64}", manifest_hash) is not None
                and source_hash == str(source_hashes.get("rest_raw/20261001") or "").lower()
                and krx_hash == str(source_hashes.get("krx_options_daily") or "").lower()
                and manifest_hash == str(source_hashes.get("rest_day_manifest/20261001") or "").lower()
            )
            temporal_ok = self._time_ordered(item.get("source_anchor_received_at"), item.get("generated_at"))
            record_material = {k: v for k, v in item.items() if k != "record_sha256"}
            record_hash_ok = str(item.get("record_sha256") or "").lower() == self._hash(record_material)
            krx_ok = self._crosswalk_match(krx_crosswalk.get(symbol, ()), side, month, strike)
            valid = (
                item.get("validation_only") is True
                and item.get("authoritative") is False
                and str(item.get("source_namespace") or "") == "SYNTHETIC:DERIVED_SCENARIO"
                and bool(item.get("deterministic_rule"))
                and str(item.get("source_anchor_type") or "") == "KIS_REST:futs_last_tr_date"
                and str(item.get("source_anchor_series_key") or "") == str(item.get("target_series_key") or "")
                and str(item.get("target_series_key") or "") == f"KOSPI200_STANDARD_MONTHLY:{month}"
                and int(item.get("source_anchor_contract_count") or 0) == len(anchors)
                and expiry == str(item.get("source_anchor_expiry") or "")
                and expiry[:6] == month
                and item.get("source_event_time") is None and item.get("quote_generated_at") is None
                and anchor_ok and hash_ok and record_hash_ok and temporal_ok and krx_ok
                and symbol not in rest_by_symbol
                and not item.get("master_postdate_row")
            )
            if not valid:
                issues.append(f"SYNTHETIC_EXPIRY_PROVENANCE_INVALID:{symbol}")
            synthetic_details.append({
                "record_id": item.get("record_id"), "symbol": symbol, "side": side, "month": month,
                "strike": strike, "expiry": expiry, "source_namespace": item.get("source_namespace"),
                "deterministic_rule": item.get("deterministic_rule"), "source_anchor_symbols": anchors,
                "source_anchor_expiry": item.get("source_anchor_expiry"),
                "source_anchor_sha256": source_hash, "source_anchor_manifest_sha256": manifest_hash,
                "source_anchor_type": item.get("source_anchor_type"),
                "source_anchor_series_key": item.get("source_anchor_series_key"),
                "target_series_key": item.get("target_series_key"),
                "source_anchor_contract_count": int(item.get("source_anchor_contract_count") or 0),
                "krx_reference_sha256": krx_hash, "krx_isu_codes": list(item.get("krx_isu_codes") or []),
                "krx_product_name": item.get("krx_product_name"),
                "source_anchor_received_at": item.get("source_anchor_received_at"),
                "generated_at": item.get("generated_at"), "source_anchor_valid": anchor_ok,
                "hashes_valid": hash_ok, "record_hash_valid": record_hash_ok, "time_order_valid": temporal_ok,
                "krx_identity_match": krx_ok, "validation_only": bool(item.get("validation_only")),
                "authoritative": bool(item.get("authoritative")), "record_sha256": item.get("record_sha256"),
            })

        source_time = dict(time_alignment)
        rest_time = source_time.get("rest") or {}
        ws_time = source_time.get("h0iocnt0") or {}
        if int(rest_time.get("valid_source_time_rows") or 0) + int(rest_time.get("missing_or_zero_source_time_rows") or 0) != int(rest_time.get("rows") or 0):
            issues.append("REST_SOURCE_TIME_COVERAGE_COUNT_MISMATCH")
        if int(ws_time.get("parsed_records") or 0) != int(ws_time.get("valid_source_time_records") or 0):
            issues.append("WEBSOCKET_SOURCE_TIME_COVERAGE_COUNT_MISMATCH")
        if int(rest_time.get("negative_lag_rows") or 0) or int(ws_time.get("future_vs_received") or 0):
            issues.append("SOURCE_EVENT_TIME_AFTER_RECEIVE")

        report: dict[str, Any] = {
            "report_version": self.REPORT_VERSION,
            "scope": {
                "master_manifest_files": len(master_snapshots),
                "verified_master_archives": len(master_by_hash),
                "legacy_master_aliases_without_market_date": legacy_aliases,
                "expiry_cache_records": len(expiry_records),
                "rest_contracts": len(rest_contracts),
                "rest_raw_rows": sum(int(x.get("row_count") or 0) for x in rest_contracts),
                "rest_raw_dates": sorted({d for x in rest_contracts for d in (x.get("trading_dates") or [])}),
                "websocket_days": len(websocket_days),
                "websocket_unique_symbols_union": len(ws_codes),
                "websocket_orderbook_frames": int(websocket_orderbook.get("frames") or 0),
                "websocket_orderbook_unique_symbols": len(ob_symbols),
                "krx_monthly_kospi200_supported_kis_codes": int(krx_inventory.get("supported_kis_codes") or 0),
                "krx_monthly_kospi200_rows": int(krx_inventory.get("source_rows") or 0),
                "krx_monthly_kospi200_unique_isu_codes": int(krx_inventory.get("unique_isu_codes") or 0),
                "source_hash_count": len(source_hashes),
            },
            "master_snapshot_inventory": [dict(x) for x in master_snapshots],
            "expiry_cache_crosswalk": {
                "master_code_matches": sum(bool(x["master_code_found"]) for x in expiry_details),
                "exact_master_identity_matches": sum(bool(x["master_identity_match"]) for x in expiry_details),
                "krx_monthly_crosswalk_matches": sum(bool(x["krx_monthly_crosswalk_match"]) for x in expiry_details),
                "records": expiry_details,
            },
            "rest_contract_crosswalk": {
                "request_response_identity_mismatches": sum(int(x.get("request_response_mismatch_count") or 0) for x in rest_contracts),
                "krx_identity_matches": sum(bool(x["krx_crosswalk_match"]) for x in rest_details),
                "postdate_master_identity_matches": sum(bool(x["postdate_master_match"]) for x in rest_details),
                "expected_expired_contracts_absent_from_postdate_master": sum(bool(x["postdate_master_absence_expected_after_expiry"]) for x in rest_details),
                "contracts": rest_details,
            },
            "websocket_contract_crosswalk": {
                "krx_identity_matches": sum(int(x["krx_crosswalk_matches"]) for x in ws_details),
                "postdate_master_identity_matches": sum(int(x["postdate_master_identity_matches"]) for x in ws_details),
                "daily": ws_details,
            },
            "websocket_orderbook_crosswalk": {
                "frames": int(websocket_orderbook.get("frames") or 0),
                "unique_symbols": len(ob_symbols), "krx_identity_matches": ob_matches,
                "raw_hhmmss_promoted_to_event_time": False,
            },
            "cross_universe_comparison": {
                "expiry_rest_direct_code_overlap": expiry_rest_code_overlap,
                "expiry_rest_exact_side_expiry_strike_overlap": [list(x) for x in expiry_rest_identity_overlap],
                "classification": "SEPARATE_EVIDENCE_SUBSETS_NOT_IDENTITY_CONFLICT" if not expiry_rest_code_overlap and not expiry_rest_identity_overlap else "OVERLAP_REQUIRES_RECONCILIATION",
            },
            "time_alignment": source_time,
            "synthetic_validation_expiry_assignments": {
                "count": len(synthetic_details), "source_backed_anchor_contracts": len(rest_by_symbol),
                "records": synthetic_details,
            },
            "source_hashes": dict(sorted(source_hashes.items())),
            "issues": sorted(set(issues)),
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
            "synthetic_data_used": bool(synthetic_details),
        }
        report["report_sha256"] = self._hash(report)
        return report